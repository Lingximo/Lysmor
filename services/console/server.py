# -*- coding: utf-8 -*-
"""控制台（整合页 · 通用骨架）

一页总览：各服务健康度 + 生命状态摘要 + 最近动态 + 最近记忆数。
只读展示，卡片点击跳转到对应服务页面。

接口：
  GET /api/overview  -> 聚合信息 JSON
  GET /              -> 控制台页（口令门禁 ?t=口令）

用法：
    python server.py [--port 8001] [--token 口令] [--config ../../config/config.json] [--services <注册表路径>]
"""

import argparse
import json
import os
import secrets
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from i18n import send_browser_asset, language_from_header, t

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CONFIG = {"gate_token": "", "port": 8009}   # 注意：别和网页聊天(8001)撞端口


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


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        # utf-8-sig：兼容 Windows 记事本/PowerShell 写出的带 BOM 的 JSON
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def probe(url, token, timeout=2):
    """GET 一个健康端点：通=ok，不通=down。部署里各服务共用同一个口令。"""
    try:
        req = urllib.request.Request(url, headers={"X-Gate-Token": token or ""})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def get_json(url, token, timeout=2):
    try:
        req = urllib.request.Request(url, headers={"X-Gate-Token": token or ""})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def overview(services_path=None):
    token = CONFIG.get("gate_token") or ""
    registry = load_json(services_path or os.path.join(DATA, "services.json"), {"services": []})
    services = []
    for s in registry.get("services") or []:
        up = probe((s.get("url") or "") + (s.get("health") or ""), token)
        services.append({"id": s.get("id"), "name": s.get("name"),
                         "url": s.get("url"), "page": s.get("page") or "/", "up": up})

    # 生命状态摘要（生命面板起来时才有）
    life = None
    for s in services:
        if s["id"] == "life" and s["up"]:
            data = get_json(s["url"] + "/api/state", token)
            if data:
                life = {"vitals": data.get("vitals"), "labels": data.get("labels")}

    # 记忆数（记忆星图起来时才有）
    memory_count = None
    for s in services:
        if s["id"] == "brain" and s["up"]:
            data = get_json(s["url"] + "/api/memories", token)
            if data:
                memory_count = len(data.get("nodes") or [])

    activities = load_json(os.path.join(DATA, "activity.json"), {"activities": []})
    return {"services": services, "life": life, "memory_count": memory_count,
            "activities": (activities.get("activities") or [])[:20], "t": time.time()}


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-console/0.1"

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
        if parsed.path == "/api/overview":
            if not self._authed():
                return self._deny()
            return self._json(overview(SERVICES_PATH))
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


SERVICES_PATH = None


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--services", default=None, help=t("services.cli.registryHelp"))
    args = ap.parse_args()

    global SERVICES_PATH
    SERVICES_PATH = args.services
    load_config(args.config)
    port = args.port or int(CONFIG.get("port") or 8009)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print(t("services.cli.developmentToken", token=CONFIG["gate_token"]))

    srv = ThreadingHTTPServer((args.host, port), Handler)
    print(t("services.cli.started", service=t("services.console.title"), host=args.host, port=port, token=CONFIG["gate_token"]))
    print(t("services.cli.registryPath", path=SERVICES_PATH or os.path.join(DATA, "services.json")))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
