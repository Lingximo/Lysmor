# -*- coding: utf-8 -*-
"""记忆星图（通用骨架）

把记忆库里的记忆按主题聚类画成星图：点 = 记忆，连线 = 同主题关联。

接口：
  GET /api/memories  -> 节点与连线 JSON
  GET /              -> 星图页（口令门禁 ?t=口令）

数据来源：
  data/memories.json（不存在时退回 data/memories.example.json 演示数据）。
  接你自己的记忆系统：把记忆导出成同样的 JSON 即可（见 README）。

用法：
    python server.py [--port 8006] [--token 口令] [--config ../../config/config.json]
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
CONFIG = {"gate_token": "", "port": 8006}


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


def load_memories():
    """读记忆数据；接你自己的记忆系统时，把导出改到这里。"""
    real = os.path.join(DATA, "memories.json")
    demo = os.path.join(DATA, "memories.example.json")
    path = real if os.path.exists(real) else demo
    if not os.path.exists(path):
        return {"nodes": [], "links": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"nodes": [], "links": [], "error": str(exc)[:80]}
    nodes = data.get("nodes") or []
    # 同主题之间生成连线（星图的"关联"）
    links = []
    by_topic = {}
    for n in nodes:
        by_topic.setdefault(n.get("topic") or "其他", []).append(n)
    for topic, group in by_topic.items():
        order = sorted(group, key=lambda n: (n.get("id") or 0))
        for a, b in zip(order, order[1:]):
            links.append({"source": a.get("id"), "target": b.get("id")})
    return {"nodes": nodes, "links": links}


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-brain/0.1"

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
        if parsed.path == "/api/memories":
            if not self._authed():
                return self._deny()
            return self._json(load_memories())
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
    port = args.port or int(CONFIG.get("port") or 8006)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print("开发模式：本次口令 t=%s" % CONFIG["gate_token"])

    srv = ThreadingHTTPServer((args.host, port), Handler)
    print("记忆星图已启动：http://%s:%d/?t=%s" % (args.host, port, CONFIG["gate_token"]))
    print("数据：%s（不存在则用 example 演示数据）" % os.path.join(DATA, "memories.json"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
