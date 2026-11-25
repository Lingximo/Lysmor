# -*- coding: utf-8 -*-
"""给 OBS「浏览器源」用的本地静态服务：把桌宠页面以透明背景提供出来。

用法（后台跑着就行）：
    python obs_overlay.py [--port 9455]

OBS 里添加「浏览器」源：
    URL     http://127.0.0.1:9455/obs-pet.html
    宽高    480 x 800（按需要调）
    其它    勾选「关闭源时关闭页面」；背景默认就是透明的
"""

import argparse
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "petweb")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        try:
            print("[obs-overlay] " + (fmt % args), flush=True)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9455)
    args = ap.parse_args()
    if not os.path.isdir(ROOT):
        print("找不到 petweb 目录: " + ROOT)
        return 2
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("[obs-overlay] http://127.0.0.1:%d/obs-pet.html" % args.port, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
