# -*- coding: utf-8 -*-
"""把TA的视频页（panel 模式）截成 MJPEG，给 Pico 浮窗用。

只读屏幕上的那个窗口，不碰她的数据。
端口：8014
  /panel.mjpg   连续画面
  /panel.jpg    单帧
"""
from __future__ import annotations

import ctypes
import io
import json
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageGrab, ImageOps

PORT = 8014
TITLE_HINT = "和TA视频"
FPS = 15
QUALITY = 92

TOKEN = ""
try:
    TOKEN = open(r"D:\你的数据目录\gate_token.txt", encoding="utf-8").read().strip()
except OSError:
    pass

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

_rect = {"x": 0, "y": 0, "w": 0, "h": 0}
_lock = threading.Lock()
_latest = {"jpg": b"", "at": 0.0}


def _find_window():
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if TITLE_HINT in buf.value:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def _client_rect(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    with _lock:
        _rect.update(x=pt.x, y=pt.y, w=r.right, h=r.bottom)
    return _rect["x"], _rect["y"], _rect["w"], _rect["h"]


def _print_window(hwnd):
    """直接抓窗口内容，不抓屏幕区域，避免被别的窗口压住/抓到桌面。"""
    try:
        import win32gui
        import win32ui
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w < 100 or h < 100:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src_dc, w, h)
        mem_dc.SelectObject(bmp)
        ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 2)
        bits = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (w, h), bits, "raw", "BGRX", 0, 1)
        win32gui.DeleteObject(bmp.GetHandle())
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        return img
    except Exception as exc:
        print("[panel] PrintWindow failed:", exc, flush=True)
        return None


def _grab():
    hwnd = _find_window()
    if not hwnd:
        return None
    img = _print_window(hwnd)
    if img is None:
        x, y, w, h = _client_rect(hwnd)
        if w < 100 or h < 100:
            return None
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=False)
    img = img.convert("RGB")
    # 去掉标题栏（Edge 应用窗口约 30px）
    if img.height > 80:
        img = img.crop((0, 30, img.width, img.height))
    # 先裁掉黑边，让她的像素尽量占满画布（不裁会显得糊）
    try:
        mask = img.convert("L").point(lambda p: 255 if p > 10 else 0)
        box = mask.getbbox()
        if box:
            pad = 10
            img = img.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                            min(img.width, box[2] + pad), min(img.height, box[3] + pad)))
    except Exception:
        pass
    # 16:9 画布：她按比例缩放后居中，黑边留给抠像
    img.thumbnail((1280, 720))
    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
    canvas.paste(img, ((1280 - img.width) // 2, (720 - img.height) // 2))
    img = canvas
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=QUALITY)
    return buf.getvalue()


def _loop():
    while True:
        t0 = time.time()
        try:
            jpg = _grab()
            if jpg:
                with _lock:
                    _latest["jpg"] = jpg
                    _latest["at"] = time.time()
        except Exception as exc:  # noqa: BLE001
            print("grab failed:", exc, flush=True)
        dt = time.time() - t0
        time.sleep(max(0.0, 1.0 / FPS - dt))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        peer = self.client_address[0]
        if peer not in ("127.0.0.1", "::1") and TOKEN:
            given = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            if given != TOKEN:
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        if self.path.startswith("/panel/status"):
            with _lock:
                at = _latest["at"]
            return self._send(200, json.dumps({"at": at, "age": (time.time() - at) if at else 9999}).encode(), "application/json; charset=utf-8")
        if self.path.startswith("/panel.jpg"):
            with _lock:
                jpg = _latest["jpg"]
            if not jpg:
                return self._send(503, b"no window", "text/plain; charset=utf-8")
            return self._send(200, jpg, "image/jpeg")
        if self.path.startswith("/panel.mjpg"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    with _lock:
                        jpg = _latest["jpg"]
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(("Content-Length: %d\r\n\r\n" % len(jpg)).encode())
                        self.wfile.write(jpg + b"\r\n")
                    time.sleep(1.0 / FPS)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
        html = ("<!doctype html><meta charset=utf-8><body style='background:#02040a;color:#9fd3ff;"
                "font-family:sans-serif;padding:30px'><h3>TA面板流</h3>"
                "<p><a style='color:#67e8f9' href='/panel.jpg'>单帧</a> · "
                "<a style='color:#67e8f9' href='/panel.mjpg'>连续</a></p>"
                "<img src='/panel.mjpg' style='max-width:90vw;border:1px solid #164e63'></body>").encode("utf-8")
        return self._send(200, html, "text/html; charset=utf-8")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


if __name__ == "__main__":
    threading.Thread(target=_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("[panel] http://127.0.0.1:%d/panel.mjpg" % PORT, flush=True)
    srv.serve_forever()
