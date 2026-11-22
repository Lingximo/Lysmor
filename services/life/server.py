# -*- coding: utf-8 -*-
"""生命面板（通用骨架）

一组带"半衰期回稳"的生理/情绪状态，随时间自行演化；面板只读。

接口：
  GET /api/state   -> 当前状态 JSON
  GET /api/trend   -> 最近一段时间的变化曲线
  GET /            -> 面板页（口令门禁 ?t=口令）

用法：
    python server.py [--port 8005] [--token 口令] [--config ../../config/config.json] [--demo]
    --demo：把时间加快 60 倍，方便看状态变化（演示用，别用于正式部署）

接真实世界事件（吃饭/喝水/互动/睡觉）：
    见文件底部 change() 与 EVENTS 注释——内部接口，HTTP 面始终只读。
"""

import argparse
import json
import math
import os
import random
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from i18n import send_browser_asset, language_from_header, t

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "state.json")

CONFIG = {"gate_token": "", "port": 8005}

# key: (中文名, 基线, 半衰期小时, 每小时漂移(趋于1), 说明)
VITALS = {
    "energy":       ("services.vitals.energy", 0.80, 4.0, -0.05, "services.vitalNotes.energy"),
    "hunger":       ("services.vitals.hunger", 0.15, 6.0, +0.28, "services.vitalNotes.hunger"),
    "thirst":       ("services.vitals.thirst", 0.15, 5.0, +0.22, "services.vitalNotes.thirst"),
    "sleep_pressure": ("services.vitals.sleep_pressure", 0.10, 3.0, +0.18, "services.vitalNotes.sleep_pressure"),
    "mood":         ("services.vitals.mood", 0.60, 2.0,  0.00, "services.vitalNotes.mood"),
    "stress":       ("services.vitals.stress", 0.30, 3.0, -0.10, "services.vitalNotes.stress"),
}


def load_config(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in ("gate_token", "port"):
                    if k in data:
                        CONFIG[k] = data[k]
        except Exception as exc:  # noqa: BLE001
            print(t("services.cli.configReadFailed", error=exc))


def clamp(v):
    return max(0.0, min(1.0, v))


class LifeModel:
    """状态引擎：每个状态向基线按半衰期回稳，同时叠加漂移与扰动。"""

    def __init__(self, demo=False):
        self.demo = demo
        self.lock = threading.Lock()
        self.state = {k: clamp(v[1]) for k, v in VITALS.items()}
        self.trend = []                      # [(ts, {k: v}), ...]
        self._load()
        self._last_save = time.time()
        self._last_sample = time.time()

    def _load(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for k in VITALS:
                if k in data:
                    self.state[k] = clamp(float(data[k]))
        except Exception:  # noqa: BLE001
            pass

    def _save(self):
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as exc:  # noqa: BLE001
            print(t("services.cli.stateSaveFailed", error=exc))

    # ---- 内部接口：接真实事件时用这个（HTTP 面不暴露） ----
    def change(self, key, delta, reason=""):
        with self.lock:
            if key not in self.state:
                return
            self.state[key] = clamp(self.state[key] + delta)
        print("[event] %s %+.2f %s" % (key, delta, reason))

    def tick(self, dt_hours):
        with self.lock:
            rng = random.Random()
            for k, (label, base, half, drift, note) in VITALS.items():
                v = self.state[k]
                # 半衰期回稳（连开多久就回稳多久）
                if half > 0:
                    v += (base - v) * (1.0 - math.exp(-dt_hours * math.log(2) / half))
                # 漂移
                v += drift * dt_hours
                # 情绪：少量随机扰动
                if k == "mood":
                    v += rng.uniform(-0.02, 0.02)
                if k == "sleep_pressure" and v > 0.9:      # 困到极致掉精力
                    self.state["energy"] = clamp(self.state["energy"] - 0.02 * dt_hours)
                self.state[k] = clamp(v)
        now = time.time()
        if now - self._last_sample >= 10:
            self._last_sample = now
            self.trend.append((now, dict(self.state)))
            if len(self.trend) > 240:
                del self.trend[:len(self.trend) - 240]
        if now - self._last_save >= 60:
            self._last_save = now
            self._save()

    def snapshot(self, locale=None):
        with self.lock:
            return {"vitals": dict(self.state), "labels": {k: t(v[0], locale=locale) for k, v in VITALS.items()},
                    "notes": {k: t(v[4], locale=locale) for k, v in VITALS.items()}, "t": time.time()}

    def trend_json(self):
        with self.lock:
            return {"trend": [{"t": t, "v": v} for t, v in self.trend]}


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-life/0.1"

    def _authed(self):
        token = CONFIG["gate_token"]
        if not token:
            return True
        q = parse_qs(urlparse(self.path).query)
        return (q.get("t") or [""])[0] == token or self.headers.get("X-Gate-Token", "") == token

    def _deny(self):
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps({"error": t("services.api.invalidToken", locale=language_from_header(self.headers.get("Accept-Language")))}, ensure_ascii=False).encode("utf-8"))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if send_browser_asset(self, parsed.path):
            return
        # 数据接口挂门禁；静态壳文件公开（浏览器加载资源时带不上口令）
        if parsed.path in ("/api/state", "/api/trend"):
            if not self._authed():
                return self._deny()
            if parsed.path == "/api/state":
                return self._json(MODEL.snapshot(locale=language_from_header(self.headers.get("Accept-Language"))))
            return self._json(MODEL.trend_json())
        rel = parsed.path.strip("/") or "index.html"
        if ".." in rel or rel.startswith("/"):
            self.send_response(404)
            return self.end_headers()
        fp = os.path.join(BASE, "static", rel)
        if not os.path.isfile(fp):
            self.send_response(404)
            return self.end_headers()
        mime = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8"}.get(os.path.splitext(fp)[1].lower(),
                                                       "application/octet-stream")
        body = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


MODEL = LifeModel()


def loop():
    dt = (1.0 / 3600.0) * (60.0 if MODEL.demo else 1.0)   # demo 时每 2 秒 = 2 分钟
    while True:
        MODEL.tick(dt * 2.0)                              # 每 2 秒跑一步
        time.sleep(2)


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    global MODEL
    MODEL = LifeModel(demo=args.demo)
    load_config(args.config)
    port = args.port or int(CONFIG.get("port") or 8005)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print(t("services.cli.developmentToken", token=CONFIG["gate_token"]))

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, port), Handler)
    print(t("services.cli.started", service=t("services.life.title"), host=args.host, port=port, token=CONFIG["gate_token"]))
    print(t("services.cli.lifeHelp"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
