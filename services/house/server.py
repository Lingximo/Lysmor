# -*- coding: utf-8 -*-
"""大平层（3D 房间 · 通用骨架）

一个可旋转/缩放的等距 3D 房间：家具布局来自配置文件，
点击家具看说明，房间里的"居住者"只是一个通用光点占位
（形象素材由使用者自备，本骨架不附带任何角色形象）。

接口：
  GET /api/house  -> 房间尺寸 + 家具 + 居住者位置/状态
  GET /           -> 房间页（口令门禁 ?t=口令）

用法：
    python server.py [--port 8007] [--token 口令] [--config ../../config/config.json]

布局改 data/plan.json；进阶渲染（光照/贴图/模型）可把前端换成 Three.js。
"""

import argparse
import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CONFIG = {"gate_token": "", "port": 8007}


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
            print("! 读配置失败：%s" % exc)


def load_house():
    path = os.path.join(DATA, "plan.json")
    if not os.path.exists(path):
        return {"room": {"w": 8, "d": 6}, "furniture": [],
                "occupant": {"name": "TA", "x": 4.0, "y": 3.0, "state": "idle"}}
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"room": {"w": 8, "d": 6}, "furniture": [], "error": str(exc)[:80]}
    plan.setdefault("occupant", {"name": "TA", "x": 4.0, "y": 3.0, "state": "idle"})
    return plan


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-house/0.1"

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
        self.wfile.write(json.dumps({"error": "口令不对"}, ensure_ascii=False).encode("utf-8"))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        # 数据接口挂门禁；静态壳文件公开（浏览器加载资源时带不上口令）
        if parsed.path == "/api/house":
            if not self._authed():
                return self._deny()
            return self._json(load_house())
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


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    load_config(args.config)
    port = args.port or int(CONFIG.get("port") or 8007)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print("开发模式：本次口令 t=%s" % CONFIG["gate_token"])

    srv = ThreadingHTTPServer((args.host, port), Handler)
    print("大平层已启动：http://%s:%d/?t=%s" % (args.host, port, CONFIG["gate_token"]))
    print("布局：%s" % os.path.join(DATA, "plan.json"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
