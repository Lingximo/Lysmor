# -*- coding: utf-8 -*-
"""画廊（通用骨架）

角色产出的画作按时间陈列：网格 + 详情。

接口：
  GET /api/works     -> 作品清单 JSON
  GET /media/<file>  -> 图片/视频文件（只允许 media 目录内的文件）
  GET /              -> 画廊页（口令门禁 ?t=口令）

数据：data/index.json（作品清单）+ media/（图片/视频文件）。
本骨架只带两张抽象占位图，**不含任何角色形象素材**。

用法：
    python server.py [--port 8002] [--token 口令] [--config ../../config/config.json]
"""

import argparse
import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from i18n import send_browser_asset, language_from_header, t

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
MEDIA = os.path.join(BASE, "media")
CONFIG = {"gate_token": "", "port": 8002}

MEDIA_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".mp4": "video/mp4", ".webm": "video/webm",
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


def load_works():
    path = os.path.join(DATA, "index.json")
    if not os.path.exists(path):
        return {"works": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"works": [], "error": str(exc)[:80]}
    works = list(data.get("works") or [])
    works.sort(key=lambda w: str(w.get("t") or ""), reverse=True)
    return {"works": works}


class Handler(BaseHTTPRequestHandler):
    server_version = "companion-gallery/0.1"

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

    def _safe_media(self, name):
        name = unquote(name)
        if "/" in name or "\\" in name or ".." in name:
            return None
        fp = os.path.join(MEDIA, name)
        real = os.path.realpath(fp)
        if not real.startswith(os.path.realpath(MEDIA) + os.sep):
            return None
        return real if os.path.isfile(real) else None

    def do_GET(self):
        parsed = urlparse(self.path)
        if send_browser_asset(self, parsed.path):
            return
        # 只有清单接口挂门禁；静态页面与媒体文件公开——
        # <img>/<script>/<link> 加载资源时带不上口令，门禁它们页面就会死壳/裂图。
        if parsed.path == "/api/works":
            if not self._authed():
                return self._deny()
            return self._json(load_works())
        if parsed.path.startswith("/media/"):
            fp = self._safe_media(parsed.path[len("/media/"):])
            if not fp:
                self.send_response(404)
                return self.end_headers()
            body = open(fp, "rb").read()
            ext = os.path.splitext(fp)[1].lower()
            self.send_response(200)
            self.send_header("Content-Type", MEDIA_MIME.get(ext, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
    port = args.port or int(CONFIG.get("port") or 8002)
    if args.token is not None:
        CONFIG["gate_token"] = args.token
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print(t("services.cli.developmentToken", token=CONFIG["gate_token"]))

    srv = ThreadingHTTPServer((args.host, port), Handler)
    print(t("services.cli.started", service=t("services.gallery.title"), host=args.host, port=port, token=CONFIG["gate_token"]))
    print(t("services.cli.galleryPaths", index=os.path.join(DATA, "index.json"), media=MEDIA))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
