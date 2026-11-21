# -*- coding: utf-8 -*-
"""网页聊天服务（通用骨架）

不依赖任何 IM 平台的最小聊天通道：
  · 口令门禁：页面用 ?t=口令，接口用请求头 X-Gate-Token
  · POST /api/chat    {"text": "..."}  ->  {"reply": "..."}
  · GET  /api/history                    -> 最近消息（仅内存）
  · 静态页面 static/（聊天界面）

回复逻辑是一个"插头"：把 reply() 换成你自己的 LLM 调用
（本地 Ollama / 云端 API / 机器人框架）即可。

用法：
    python server.py [--port 8001] [--token 口令] [--config ../../config/config.json]
"""

import argparse
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")

# 默认配置（部署时用 --config 指向你的 config.json）
CONFIG = {
    "gate_token": "",          # 空 = 启动时自动生成一个开发口令并打印出来
    "port": 8001,
    "llm": {"provider": "", "api_key": "", "base_url": "", "model": ""},
}

HISTORY = []          # 最近消息（骨架版只存内存，重启即清）
MAX_HISTORY = 200

# 安全的静态文件类型
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def load_config(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in ("gate_token", "port", "llm"):
                    if k in data:
                        CONFIG[k] = data[k]
        except Exception as exc:  # noqa: BLE001
            print("! 读配置失败：%s" % exc)


def reply(text):
    """接你自己的 LLM 的地方。

    示例：没有接 LLM 时的占位行为（echo）。接入后替换成：
        - 本地：POST http://127.0.0.1:11434/api/chat （Ollama）
        - 云端：按服务商文档调用，把 CONFIG["llm"] 里的 key 带上
    """
    return "（占位回复）你说的是：" + text


def record(role, text):
    HISTORY.append({"role": role, "text": text, "t": time.time()})
    if len(HISTORY) > MAX_HISTORY:
        del HISTORY[:len(HISTORY) - MAX_HISTORY]


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-webchat/0.1"

    def _authed(self):
        token = CONFIG["gate_token"]
        if not token:
            return True                      # 未设口令 = 开发模式，全放行
        q = parse_qs(urlparse(self.path).query)
        url_tok = (q.get("t") or [""])[0]
        head_tok = self.headers.get("X-Gate-Token", "")
        return url_tok == token or head_tok == token

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
        if parsed.path == "/api/history":
            if not self._authed():
                return self._deny()
            return self._json({"history": HISTORY[-50:]})
        # 静态文件
        rel = parsed.path.strip("/") or "index.html"
        if ".." in rel or rel.startswith("/"):
            self.send_response(404)
            return self.end_headers()
        fp = os.path.join(STATIC, rel)
        if not os.path.isfile(fp):
            self.send_response(404)
            return self.end_headers()
        ext = os.path.splitext(fp)[1].lower()
        body = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_response(404)
            return self.end_headers()
        if not self._authed():
            return self._deny()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return self._json({"error": "请求不是合法 JSON"}, 400)
        text = str(data.get("text") or "").strip()
        if not text:
            return self._json({"error": "text 不能为空"}, 400)
        if len(text) > 4000:
            return self._json({"error": "太长了"}, 400)
        record("user", text)
        ans = reply(text)
        record("bot", ans)
        self._json({"reply": ans})

    def log_message(self, fmt, *args):  # 安静一点
        pass


def main():
    if sys.stdout is not None:  # pythonw 下是 None
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default="127.0.0.1", help="默认只监听本机；开局域网前先设口令并读 SECURITY.md")
    args = ap.parse_args()

    load_config(args.config)
    port = args.port or int(CONFIG.get("port") or 8001)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print("开发模式：本次口令 t=%s" % CONFIG["gate_token"])

    srv = ThreadingHTTPServer((args.host, port), Handler)
    print("网页聊天已启动：http://%s:%d/  （口令 t=%s）" % (args.host, port, CONFIG["gate_token"]))
    print("接 LLM：改 reply()（见文件顶部说明）。Ctrl+C 退出。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
