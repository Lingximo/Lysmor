# -*- coding: utf-8 -*-
"""TA的眼睛 · HTTP 服务（端口 8801，只监听本机）

给聊天入口用：她说"看看我"的时候，上层调这里取一帧 + 描述。

    GET /look           → {"ok":true,"desc":"...","faces":1,"bright":150}
    GET /look?fresh=0   → 允许复用 3 秒内的结果
    GET /health         → {"ok":true}

为什么单独起服务：
    · cv2 + onnxruntime 只在这一个进程里加载，不污染聊天进程
    · 摄像头是独占资源，集中在这里取帧，避免互相抢

隔离：只读写 lab\\vision 下的临时图，不碰 state/记忆。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PYLIBS = os.path.join(HERE, "pylibs")
if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

import eye  # noqa: E402

PORT = 8801
CACHE_SECONDS = 3.0

_lock = threading.Lock()
_cache = {"t": 0.0, "data": None}


def get_look(fresh: bool = True) -> dict:
    with _lock:
        now = time.time()
        if (not fresh) and _cache["data"] and now - _cache["t"] < CACHE_SECONDS:
            return _cache["data"]
        data = eye.look()
        data.pop("frame", None)          # 不把图塞进 JSON
        _cache.update({"t": time.time(), "data": data})
        return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/health":
            return self._json({"ok": True})
        if u.path == "/look":
            q = parse_qs(u.query)
            fresh = (q.get("fresh") or ["1"])[0] not in ("0", "false")
            try:
                return self._json(get_look(fresh=fresh))
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:160]}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("TA的眼睛：http://127.0.0.1:%d/look" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
