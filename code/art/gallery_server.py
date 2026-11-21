# -*- coding: utf-8 -*-
"""TA · 简笔画画廊（独立网页，端口 8002）

单独一个服务，不依赖网页聊天：
  http://127.0.0.1:8002/            画廊页面
  http://127.0.0.1:8002/api/doodles 列表
  http://127.0.0.1:8002/art/<文件>   原图
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

GALLERY = r"D:\你的数据目录\art\gallery"
PORT = 8002
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "gallery.html")


def _ink_ok(path, pencil=True):
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        w, h = im.size
        if w > 2000 and h > 1000:
            return False
        if w < 120 or h < 60:
            return False
        hist = im.histogram()
        total = float(w * h)
        if pencil:
            ratio = sum(hist[:90]) / total
            if not (0.0004 <= ratio <= 0.15):
                return False
            px = im.load()
            band_y = max(2, h // 50)
            band_x = max(2, w // 50)
            edge = 0
            for y in range(band_y):
                for x in range(0, w, 3):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(0, w, 3):
                for y in range(h - band_y, h):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(band_x):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge += 1
            for x in range(w - band_x, w):
                for y in range(0, h, 3):
                    if px[x, y] < 90:
                        edge += 1
            return edge < 4
        ratio = (total - sum(hist[236:])) / total
        return 0.004 <= ratio <= 0.85
    except Exception:
        return False


def doodle_list():
    try:
        names = os.listdir(GALLERY)
    except Exception:
        return []
    doodles = sorted([n for n in names if n.startswith("doodle_") and n.lower().endswith((".jpg", ".png"))],
                     reverse=True)
    sketches = sorted([n for n in names if n.startswith("sketch_") and n.lower().endswith((".jpg", ".png"))],
                      reverse=True)

    def ts(name):
        return "".join(ch for ch in name if ch.isdigit())[:14]

    out, used = [], set()
    for d in doodles:
        if not _ink_ok(os.path.join(GALLERY, d)):
            continue
        t = ts(d)
        best = None
        for sk in sketches:
            if sk in used:
                continue
            if ts(sk) >= t and (not best or ts(sk) < ts(best)):
                best = sk
        color = ""
        if best:
            used.add(best)
            color = best if _ink_ok(os.path.join(GALLERY, best), False) else ""
        out.append({"time": t, "doodle": d, "sketch": color})
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html", "/doodle"):
            try:
                with open(PAGE, "rb") as f:
                    return self._send(f.read(), "text/html; charset=utf-8")
            except Exception:
                return self._send(b"gallery.html missing", "text/plain", 500)
        if p == "/api/doodles":
            return self._send(json.dumps(doodle_list(), ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if p.startswith("/art/"):
            name = os.path.basename(unquote(p[len("/art/"):]))
            full = os.path.normpath(os.path.join(GALLERY, name))
            if not full.startswith(os.path.normpath(GALLERY) + os.sep) or not os.path.isfile(full):
                return self._send(b"", "image/jpeg", 404)
            ctype = "image/png" if name.lower().endswith(".png") else "image/jpeg"
            with open(full, "rb") as f:
                return self._send(f.read(), ctype)
        return self._send(b"not found", "text/plain; charset=utf-8", 404)


def main():
    print("简笔画画廊：http://127.0.0.1:%d/" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
