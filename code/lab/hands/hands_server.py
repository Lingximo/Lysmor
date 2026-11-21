# -*- coding: utf-8 -*-
"""TA的手 · 受限电脑操作服务（端口 8010，只监听本机）

设计原则（低风险版）：
  · 只有白名单动作，不接受任意命令/任意代码
  · 只允许操作白名单里的程序，不允许关系统窗口
  · 每个动作都写日志：logs\\hands.log（时间 / 动作 / 参数 / 结果）
  · 急停：存在 logs\\hands.stop 文件时，所有动作一律拒绝（POST /stop 创建，/resume 删除）

接口：
  GET  /health                     → {"ok":true,"stopped":false}
  GET  /actions                    → 可用动作列表
  GET  /windows                    → 当前可见窗口标题
  GET  /volume                     → 当前音量 0~100
  POST /do {"action":"...", ...}   → 执行
  POST /stop                       → 急停
  POST /resume                     → 解除急停

动作（全部低风险）：
  open_app     {"app":"notepad"}                 打开白名单程序
  switch_window{"title":"记事本"}                 切到包含该标题的窗口
  close_window {"title":"记事本"}                 只关白名单程序自己的窗口
  volume       {"delta":10} / {"set":30} / {"mute":true}
  media        {"key":"play|next|prev"}          播放/下一首/上一首
  lock                                           锁屏
  screenshot   {"width":960}                     截屏（base64 jpg，给视觉用）
"""
from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = r"D:\你的数据目录\logs"
LOG = os.path.join(LOG_DIR, "hands.log")
STOP_FLAG = os.path.join(LOG_DIR, "hands.stop")
PORT = 8010

# ---- 白名单程序（key → 启动命令）----
APPS = {
    "notepad": ["notepad.exe"],
    "记事本": ["notepad.exe"],
    "calc": ["calc.exe"],
    "计算器": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "资源管理器": ["explorer.exe"],
    "mspaint": ["mspaint.exe"],
    "画图": ["mspaint.exe"],
    "cmd": ["cmd.exe"],          # 只是开一个窗口，不执行任何东西
    "任务管理器": ["taskmgr.exe"],
    # 2026-11-09 部署者给了她玩绝区零的权利（只许开，不许关，怕丢进度）
    "zenless": [r"D:\miHoYo Launcher\games\ZenlessZoneZero Game\ZenlessZoneZero.exe"],
    "绝区零": [r"D:\miHoYo Launcher\games\ZenlessZoneZero Game\ZenlessZoneZero.exe"],
    "米哈游启动器": [r"D:\miHoYo Launcher\launcher.exe"],
    # 2026-11-10：部署者说她不会开 QQ 音乐
    "qqmusic": [r"C:\Program Files (x86)\Tencent\QQMusic\QQMusic.exe"],
    "QQ音乐": [r"C:\Program Files (x86)\Tencent\QQMusic\QQMusic.exe"],
    "qq音乐": [r"C:\Program Files (x86)\Tencent\QQMusic\QQMusic.exe"],
}
# 只允许关这些进程的窗口
CLOSE_ALLOWED = ("notepad.exe", "calc.exe", "mspaint.exe", "notepad", "记事本", "计算器",
                 "QQ音乐", "QQMusic")
# 游戏运行中一律不许关（ZenlessZoneZero 不在 CLOSE_ALLOWED 里，这里再显式挡一层）
NEVER_CLOSE = ("zenless", "绝区零", "ZenlessZoneZero", "YuanShen", "GenshinImpact")


def log(action: str, detail, ok: bool, note: str = "") -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\t%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), action,
                json.dumps(detail, ensure_ascii=False)[:200],
                "ok" if ok else "fail", note[:200]))
    except Exception:
        pass


def stopped() -> bool:
    return os.path.exists(STOP_FLAG)


# ---------------- 动作实现 ----------------

def _pygetwindow():
    import pygetwindow as gw
    return gw


def act_open_app(p):
    app = str(p.get("app") or "").strip().lower()
    cmd = APPS.get(app) or APPS.get(str(p.get("app") or "").strip())
    if not cmd:
        return False, "不在白名单：%s" % app
    subprocess.Popen(cmd, close_fds=True)
    return True, "已打开 %s" % app


def act_switch_window(p):
    gw = _pygetwindow()
    title = str(p.get("title") or "").strip()
    if not title:
        return False, "缺少 title"
    for w in gw.getAllWindows():
        try:
            if w.title and title.lower() in w.title.lower() and not w.isMinimized:
                w.activate()
                return True, "已切到：%s" % w.title[:40]
        except Exception:
            continue
    return False, "没找到窗口：%s" % title


# 2026-11-10：QQ 音乐这类程序，窗口标题是歌名，按标题找不到。
# 补一条"按进程关"：只关白名单 exe 的窗口（WM_CLOSE，不强杀）。
CLOSE_ALLOWED_EXE = ("qqmusic.exe", "mspaint.exe", "notepad.exe", "calc.exe")
APP_ALIAS = {
    "qqmusic": "QQMusic.exe", "qq音乐": "QQMusic.exe", "qq 音乐": "QQMusic.exe",
    "mspaint": "mspaint.exe", "画图": "mspaint.exe",
    "notepad": "notepad.exe", "记事本": "notepad.exe",
    "calc": "calc.exe", "计算器": "calc.exe",
}


def _visible_windows_pid(pid):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    count = [0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        pp = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pp))
        if pp.value == pid and user32.IsWindowVisible(hwnd):
            count[0] += 1
        return True

    user32.EnumWindows(cb, 0)
    return count[0]


def _wm_close_pid(pid):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    count = [0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        pp = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pp))
        if pp.value == pid and user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            count[0] += 1
        return True

    user32.EnumWindows(cb, 0)
    return count[0]


def _close_by_process(name):
    import psutil
    exe = APP_ALIAS.get((name or "").strip().lower(), name)
    exe = (exe or "").strip()
    if exe.lower() not in CLOSE_ALLOWED_EXE:
        return False, "不在可关名单：%s" % exe
    pids = [x.pid for x in psutil.process_iter(["name"])
            if (x.info.get("name") or "").lower() == exe.lower()]
    if not pids:
        return False, "%s 没在运行" % exe
    import time as _t
    total = 0
    for pid in pids:
        total += _wm_close_pid(pid)
    if total:
        _t.sleep(1.2)
        # 有的程序（QQ 音乐）关窗口只是缩到托盘，进程还在
        left = []
        for x in psutil.process_iter(["name", "pid"]):
            if (x.info.get("name") or "").lower() == exe.lower():
                if _visible_windows_pid(x.info["pid"]):
                    continue
                try:
                    x.terminate()
                except Exception:
                    pass
                left.append(x.info["pid"])
        extra = ("，托盘里的 %d 个也退了" % len(left)) if left else ""
        return True, "已关闭 %s（%d 个窗口%s）" % (exe, total, extra)
    return False, "%s 没有可关的窗口" % exe


def act_close_window(p):
    gw = _pygetwindow()
    title = str(p.get("title") or "").strip()
    if not title:
        return False, "缺少 title"
    for w in gw.getAllWindows():
        try:
            if not w.title or title.lower() not in w.title.lower():
                continue
            if any(a.lower() in w.title.lower() for a in NEVER_CLOSE):
                return False, "游戏窗口不许关，会丢进度：%s" % w.title[:40]
            if not any(a.lower() in w.title.lower() for a in CLOSE_ALLOWED):
                return False, "不是白名单程序的窗口，拒绝关闭：%s" % w.title[:40]
            w.close()
            return True, "已关闭：%s" % w.title[:40]
        except Exception as exc:  # noqa: BLE001
            return False, "关闭失败：%s" % exc
    # 标题没命中（比如 QQ 音乐窗口标题是歌名）：按进程再试
    ok, msg = _close_by_process(title)
    if ok:
        return True, msg
    return False, "没找到窗口：%s" % title


def _speakers():
    """新版 pycaw：AudioUtilities.GetSpeakers() 直接给 AudioDevice，
    真正的音量接口在 .EndpointVolume 上（旧代码的 Activate 已经没了）。"""
    import comtypes
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    from pycaw.utils import AudioUtilities

    dev = AudioUtilities.GetSpeakers()
    return dev, dev.EndpointVolume


def act_volume(p):
    _dev, vol = _speakers()
    cur = vol.GetMasterVolumeLevelScalar()
    if p.get("mute") is not None:
        vol.SetMute(bool(p.get("mute")), None)
        return True, "已静音" if p.get("mute") else "已取消静音"
    if p.get("set") is not None:
        target = max(0.0, min(1.0, float(p["set"]) / 100.0))
    else:
        delta = float(p.get("delta", 10)) / 100.0
        target = max(0.0, min(1.0, cur + delta))
    vol.SetMasterVolumeLevelScalar(target, None)
    return True, "音量 %d%%" % round(target * 100)


def act_media(p):
    key = str(p.get("key") or "play").lower()
    codes = {"play": 0xB3, "next": 0xB0, "prev": 0xB1}
    vk = codes.get(key)
    if not vk:
        return False, "不支持的媒体键：%s" % key
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    return True, {"play": "播放/暂停", "next": "下一首", "prev": "上一首"}[key]


def _paint_window():
    import pygetwindow as gw
    for w in gw.getAllWindows():
        t = (w.title or "")
        if "画图" in t or "Paint" in t:
            return w
    return None


def _ensure_paint():
    import psutil
    import subprocess
    import time as _t

    running = any((p.info.get("name") or "").lower() == "mspaint.exe"
                  for p in psutil.process_iter(["name"]))
    if running:
        # 旧窗口里可能留着"选择"工具或上一张的残留，直接换一个干净的
        try:
            subprocess.run(["taskkill", "/F", "/IM", "mspaint.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        _t.sleep(0.8)
    subprocess.Popen(["mspaint.exe"], close_fds=True)
    _t.sleep(2.5)
    for _ in range(20):
        w = _paint_window()
        if w is not None:
            try:
                if w.isMinimized:
                    w.restore()
                w.activate()
                w.maximize()
            except Exception:
                pass
            _t.sleep(1.5)
            # 画布固定 800x600（Ctrl+E），几何确定，避免默认尺寸与最大化打架
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "e")
                _t.sleep(0.9)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite("800", interval=0.04)
                pyautogui.press("tab")
                pyautogui.hotkey("ctrl", "a")
                pyautogui.typewrite("600", interval=0.04)
                pyautogui.press("enter")
                _t.sleep(0.8)
            except Exception:
                pass
            w2 = _paint_window()
            return w2 or w
        _t.sleep(0.5)
    return None


def _strokes(pattern: str):
    """归一化 0~1 的笔画点列。"""
    import math

    pts = []
    if pattern == "heart":
        for t in [i / 40.0 * 2 * math.pi for i in range(41)]:
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((0.5 + x / 40.0, 0.5 + y / 40.0))
        return [pts]
    if pattern == "fish":
        body = [(0.5 + 0.30 * math.cos(t), 0.5 + 0.16 * math.sin(t))
                for t in [i / 36.0 * 2 * math.pi for i in range(37)]]
        tail = [(0.82, 0.42), (0.98, 0.34), (0.92, 0.52), (0.98, 0.66), (0.82, 0.58)]
        eye = [(0.295, 0.455), (0.315, 0.455)]
        return [body, tail, eye]
    if pattern == "star":
        pts = []
        for i in range(11):
            ang = -math.pi / 2 + i * 2 * math.pi / 5
            r = 0.30 if i % 2 == 0 else 0.13
            pts.append((0.5 + r * math.cos(ang), 0.5 + r * math.sin(ang)))
        return [pts]
    # wave：默认，三道波浪
    out = []
    for row, yy in enumerate((0.38, 0.52, 0.66)):
        line = []
        for i in range(41):
            x = i / 40.0
            line.append((0.12 + 0.76 * x, yy + 0.05 * math.sin(x * 6.28 * 1.5 + row)))
        out.append(line)
    return out


def act_draw(p):
    """在画图里真的画出来：开画图 → 选中窗口 → 鼠标拖动画线 → 截一张成品。"""
    import time as _t

    pattern = str(p.get("pattern") or "fish").lower()
    if pattern not in ("fish", "heart", "star", "wave"):
        pattern = "fish"
    w = _ensure_paint()
    if w is None:
        return False, "画图没打开"

    import pyautogui
    import ctypes
    pyautogui.FAILSAFE = False
    left, top = int(w.left), int(w.top)
    right, bottom = left + int(w.width), top + int(w.height)

    # 必须是画图在前台，否则笔画会落到别的窗口
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    if "画图" not in (buf.value or "") and "Paint" not in (buf.value or ""):
        try:
            w.activate(); _t.sleep(0.6)
        except Exception:
            pass
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        if "画图" not in (buf.value or ""):
            return False, "画图不在前台，没画"

    _t.sleep(1.2)   # 等最大化/重绘稳定，否则画布位置会变
    box = _canvas_bbox(left, top, right, bottom)
    if not box:
        return False, "没找到画布"
    raw_box = box   # 截图用原始画布范围
    x0, y0, x1, y1 = box
    # 留边距（按画布比例留 8%），避免图案顶到画布外被截掉
    _w, _h = x1 - x0, y1 - y0
    _mx, _my = max(20, int(_w * 0.08)), max(20, int(_h * 0.08))
    x0, y0, x1, y1 = x0 + _mx, y0 + _my, x1 - _mx, y1 - _my
    if x1 - x0 < 120 or y1 - y0 < 120:
        return False, "画布太小"

    def to_screen(nx, ny):
        return int(x0 + nx * (x1 - x0)), int(y0 + ny * (y1 - y0))

    # 选一支粗一点的笔：先点工具栏画笔（位置随版本不同，用快捷键更稳：Ctrl+E 不用）
    # 直接用默认铅笔/画笔，鼠标拖动即可
    count = 0
    for line in _strokes(pattern):
        if not line:
            continue
        sx, sy = to_screen(*line[0])
        pyautogui.moveTo(sx, sy, duration=0.15)
        pyautogui.mouseDown()
        for nx, ny in line[1:]:
            px, py = to_screen(nx, ny)
            pyautogui.moveTo(px, py, duration=0.012)
            count += 1
        pyautogui.mouseUp()
        _t.sleep(0.25)

    # 成品截图存起来
    try:
        from PIL import ImageGrab
        import os as _os
        gal = r"D:\你的数据目录\art\gallery"
        _os.makedirs(gal, exist_ok=True)
        path = _os.path.join(gal, "doodle_%s.jpg" % _t.strftime("%Y%m%d_%H%M%S"))
        # 只截画布，别把工具栏/色板截进去（不然 ComfyUI 会照着 UI 画）
        img = ImageGrab.grab(bbox=(x0, y0, x1, y1))
        img.convert("RGB").save(path, "JPEG", quality=88)
    except Exception:
        path = ""

    return True, "画好了（%s，%d 个点，窗口%dx%d 画布%dx%d）%s" % (
        pattern, count, right - left, bottom - top, x1 - x0, y1 - y0,
        ("：" + path) if path else "")


def _canvas_bbox(left, top, right, bottom):
    """在窗口截图里找最大的白色矩形（画布），返回绝对坐标。"""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    px = img.load()

    def white(x, y):
        r, g, b = px[x, y]
        return r > 244 and g > 244 and b > 244

    # 从中间往两边扩：先找中间一行里最长的白色连续段
    mid_y = h // 2
    best = (0, 0)
    run_start = None
    for x in range(w):
        if white(x, mid_y):
            if run_start is None:
                run_start = x
        else:
            if run_start is not None:
                if x - run_start > best[1] - best[0]:
                    best = (run_start, x)
                run_start = None
    if run_start is not None and w - run_start > best[1] - best[0]:
        best = (run_start, w)
    if best[1] - best[0] < 100:
        return None
    cx0, cx1 = best
    # 垂直方向：在中线附近找白色上/下边界
    cy = mid_y
    while cy > 0 and white((cx0 + cx1) // 2, cy - 1):
        cy -= 1
    ty = cy
    while cy < h - 1 and white((cx0 + cx1) // 2, cy + 1):
        cy += 1
    by = cy
    if by - ty < 100:
        return None
    return (left + cx0, top + ty, left + cx1, top + by)


def act_lock(p):
    ctypes.windll.user32.LockWorkStation()
    return True, "已锁屏"


def act_screenshot(p):
    from PIL import ImageGrab

    width = int(p.get("width") or 960)
    img = ImageGrab.grab()
    img.thumbnail((width, width))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=72, optimize=True)
    return True, base64.b64encode(buf.getvalue()).decode()


# ---------------- 自由玩电脑：鼠标/键盘原语（只在「她的小电脑」窗口里生效） ----------------
PLAY_TITLE = "她的小电脑"
KEYMAP = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "enter": "enter", "space": "space", "tab": "tab", "esc": "esc",
    "backspace": "backspace", "delete": "delete", "home": "home", "end": "end",
    "pageup": "pageup", "pagedown": "pagedown", "win": "win",
    "f4": "f4", "f5": "f5", "ctrl+f": ("ctrl", "f"),
}


def _play_window():
    gw = _pygetwindow()
    try:
        cands = [w for w in gw.getAllWindows()
                 if getattr(w, "title", "") and PLAY_TITLE in w.title
                 and getattr(w, "visible", True) and not getattr(w, "isMinimized", False)]
    except Exception:
        return None
    return cands[0] if cands else None


def _foreground_title():
    try:
        fg = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(fg)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(fg, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def _focus_play():
    """确保她的小电脑在最前面；返回 (window, err)"""
    w = _play_window()
    if not w:
        return None, "她的小电脑没开"
    try:
        if PLAY_TITLE not in _foreground_title():
            w.activate()
            time.sleep(0.35)
    except Exception:
        pass
    return w, ""


def act_focus(p):
    w, err = _focus_play()
    if err:
        return False, err
    return True, "已把她的小电脑提到最前"


def act_win_info(p):
    w = _play_window()
    if not w:
        return False, "她的小电脑没开"
    return True, {"title": w.title, "left": w.left, "top": w.top,
                  "width": w.width, "height": w.height,
                  "foreground": PLAY_TITLE in _foreground_title()}


def act_win_shot(p):
    from PIL import ImageGrab
    w = _play_window()
    if not w:
        return False, "她的小电脑没开"
    img = ImageGrab.grab(bbox=(w.left, w.top, w.right, w.bottom))
    width = int(p.get("width") or 960)
    if img.width > width:
        img.thumbnail((width, width))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=70, optimize=True)
    return True, {"png": base64.b64encode(buf.getvalue()).decode(),
                  "width": img.width, "height": img.height,
                  "scale": round(img.width / max(1, w.width), 4)}


def act_click(p):
    import pyautogui
    w, err = _focus_play()
    if err:
        return False, err
    try:
        x = int(p["x"]); y = int(p["y"])
    except Exception:
        return False, "需要 x/y 坐标（窗口内像素）"
    if not (0 <= x <= w.width and 0 <= y <= w.height):
        return False, "坐标超出她的小电脑范围"
    pyautogui.FAILSAFE = False
    pyautogui.click(w.left + x, w.top + y)
    return True, "点了(%d,%d)" % (x, y)


def act_key(p):
    import pyautogui
    w, err = _focus_play()
    if err:
        return False, err
    key = str(p.get("key") or "").strip().lower()
    if key not in KEYMAP:
        return False, "不支持的键：%s" % key
    pyautogui.FAILSAFE = False
    pyautogui.press(KEYMAP[key])
    return True, "按了%s" % key


def act_type(p):
    import pyautogui
    w, err = _focus_play()
    if err:
        return False, err
    text = str(p.get("text") or "")[:200]
    if not text:
        return False, "没有要输入的文字"
    pyautogui.FAILSAFE = False
    try:
        pyautogui.write(text, interval=0.03)
        return True, "输入了%d个字" % len(text)
    except Exception as exc:  # noqa: BLE001
        return False, "输入失败：%s" % exc


def act_scroll(p):
    import pyautogui
    w, err = _focus_play()
    if err:
        return False, err
    clicks = int(p.get("clicks") or 3)
    pyautogui.FAILSAFE = False
    pyautogui.scroll(clicks, x=w.left + w.width // 2, y=w.top + w.height // 2)
    return True, "滚了%d格" % clicks


ACTIONS = {
    "open_app": act_open_app,
    "switch_window": act_switch_window,
    "close_window": act_close_window,
    "volume": act_volume,
    "media": act_media,
    "draw": act_draw,
    "lock": act_lock,
    "screenshot": act_screenshot,
}


# ---------------- 物理通道：只用鼠标键盘（不给软件功能 API） ----------------
PHYS_KEYS = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "enter": "enter", "space": "space", "tab": "tab", "esc": "esc",
    "backspace": "backspace", "delete": "delete", "home": "home", "end": "end",
    "pageup": "pageup", "pagedown": "pagedown", "win": "win", "f4": "f4", "f5": "f5",
    "shift": "shift", "ctrl+space": "ctrl+space",
}
PHYS_COMBOS = {
    "ctrl+a": ("ctrl", "a"), "ctrl+c": ("ctrl", "c"), "ctrl+v": ("ctrl", "v"),
    "ctrl+z": ("ctrl", "z"), "ctrl+s": ("ctrl", "s"), "ctrl+x": ("ctrl", "x"),
}
# 只保护部署者会话窗口；NVIDIA/Program Manager 这种全屏壳不能算禁区（否则整屏都点不了）
PHYS_FORBID_TITLE = ("DeepSeek Harness",)
# 这些窗口里不许她打字/按键（怕误发消息、误操作）
SENSITIVE_TITLES = ("微信", "WeChat", "QQ", "钉钉", "企业微信", "WPS", "支付宝",
                    "银行", "密码", "任务管理器", "命令提示符", "PowerShell", "cmd.exe",
                    "设置", "DeepSeek Harness")
# 允许拖拽的窗口（画图/记事本/浏览器里拖是安全的；资源管理器里拖会移动文件，不行）
DRAG_SAFE_TITLES = ("画图", "Paint", "记事本", "Notepad", "Edge", "Chrome", "Firefox")


def _screen_size():
    import pyautogui
    return pyautogui.size()


def _forbidden_rects():
    w, h = _screen_size()
    # 只保护右下角托盘/系统图标区；左下角"开始"按钮允许点（她要开程序）
    rects = [(max(0, w - 720), max(0, h - 70), w, h)]
    try:
        gw = _pygetwindow()
        for win in gw.getAllWindows():
            try:
                t = getattr(win, "title", "") or ""
                if not t or not getattr(win, "visible", True):
                    continue
                if any(k in t for k in PHYS_FORBID_TITLE):
                    rects.append((win.left, win.top, win.right, win.bottom))
            except Exception:
                continue
    except Exception:
        pass
    return rects


def _in_forbidden(x, y):
    # 她自己的窗口优先：只要点在「她的小电脑」里就允许，哪怕和别的窗口重叠
    w = _play_window()
    if w and (w.left <= x <= w.right and w.top <= y <= w.bottom):
        return False
    for (l, t, r, b) in _forbidden_rects():
        if l <= x <= r and t <= y <= b:
            return True
    return False


def _click_at(p, kind="single"):
    import pyautogui
    _touch_synthetic()
    try:
        x = int(p["x"]); y = int(p["y"])
    except Exception:
        return False, "需要屏幕坐标 x/y"
    w, h = _screen_size()
    if not (0 <= x < w and 0 <= y < h):
        return False, "坐标超出屏幕"
    if _in_forbidden(x, y):
        return False, "那是禁区（任务栏/部署者的窗口），不去点"
    pyautogui.FAILSAFE = False
    if kind == "double":
        pyautogui.doubleClick(x, y)
        return True, "双击了(%d,%d)" % (x, y)
    if kind == "right":
        pyautogui.rightClick(x, y)
        return True, "右键点(%d,%d)" % (x, y)
    pyautogui.click(x, y)
    return True, "点了(%d,%d)" % (x, y)


def phys_shot(p):
    from PIL import ImageGrab
    img = ImageGrab.grab()
    width = int(p.get("width") or 1024)
    if img.width > width:
        img.thumbnail((width, width))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=68, optimize=True)
    return True, {"png": base64.b64encode(buf.getvalue()).decode(),
                  "width": img.width, "height": img.height}


def phys_info(p):
    import pyautogui
    w, h = pyautogui.size()
    pos = pyautogui.position()
    out = {"screen": [int(w), int(h)], "mouse": [int(pos.x), int(pos.y)],
           "foreground": _foreground_title(), "play_window": None}
    try:
        win = _play_window()
        if win:
            out["play_window"] = {"left": int(win.left), "top": int(win.top),
                                  "right": int(win.right), "bottom": int(win.bottom)}
    except Exception:
        pass
    return True, out


def phys_move(p):
    import pyautogui
    _touch_synthetic()
    try:
        x = int(p["x"]); y = int(p["y"])
    except Exception:
        return False, "需要 x/y"
    w, h = _screen_size()
    if not (0 <= x < w and 0 <= y < h):
        return False, "坐标超出屏幕"
    pyautogui.FAILSAFE = False
    pyautogui.moveTo(x, y, duration=0.2)
    return True, "鼠标移到(%d,%d)" % (x, y)


def _sensitive_foreground():
    t = _foreground_title()
    # 开始菜单/搜索框的前台标题通常是空或"搜索"，那里打字是安全的
    if not t.strip() or "搜索" in t or "Start" in t:
        return False, t
    return any(k in t for k in SENSITIVE_TITLES), t


def phys_type(p):
    import pyautogui
    _touch_synthetic()
    bad, t = _sensitive_foreground()
    if bad:
        return False, "当前窗口是「%s」，不许在里面打字" % t[:20]
    text = str(p.get("text") or "")[:300]
    if not text:
        return False, "没有文字"
    pyautogui.FAILSAFE = False
    try:
        if True:   # 一律粘贴：输入法会把英文字母变成拼音候选，paste 不会
            import subprocess
            ps = "Set-Clipboard -Value ([System.IO.File]::ReadAllText('%s'))"
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            ps % path], capture_output=True, text=True, timeout=20)
            pyautogui.hotkey("ctrl", "v")
            try:
                os.remove(path)
            except OSError:
                pass
            return True, "粘贴了%d个字" % len(text)
        pyautogui.write(text, interval=0.03)
        return True, "打了%d个字" % len(text)
    except Exception as exc:  # noqa: BLE001
        return False, "没打进去：%s" % exc


def phys_key(p):
    import pyautogui
    _touch_synthetic()
    key = str(p.get("key") or "").strip().lower()
    # win / alt+tab 是"换窗口"用的，任何窗口里都允许（否则一进敏感窗口就出不来）
    if key not in ("win", "alt+tab"):
        bad, t = _sensitive_foreground()
        if bad:
            return False, "当前窗口是「%s」，不许在里面按键" % t[:20]
    if key == "ctrl+space":
        pyautogui.FAILSAFE = False
        pyautogui.hotkey("ctrl", "space")
        return True, "切换输入法"
    if key == "alt+tab":
        pyautogui.FAILSAFE = False
        pyautogui.hotkey("alt", "tab")
        return True, "切到另一个窗口"
    if key in PHYS_COMBOS:
        mod, k = PHYS_COMBOS[key]
        pyautogui.FAILSAFE = False
        pyautogui.hotkey(mod, k)
        return True, "按了%s" % key
    if key not in PHYS_KEYS:
        return False, "这个键不在白名单：%s" % key
    pyautogui.FAILSAFE = False
    pyautogui.press(PHYS_KEYS[key])
    return True, "按了%s" % key


def phys_scroll(p):
    import pyautogui
    _touch_synthetic()
    w, h = _screen_size()
    x = int(p.get("x") or (w // 2)); y = int(p.get("y") or (h // 2))
    clicks = int(p.get("clicks") or 3)
    pyautogui.FAILSAFE = False
    pyautogui.scroll(clicks, x=x, y=y)
    return True, "滚了%d格" % clicks




def phys_drag(p):
    import pyautogui
    try:
        x1 = int(float(p["x1"])); y1 = int(float(p["y1"]))
        x2 = int(float(p["x2"])); y2 = int(float(p["y2"]))
    except Exception:
        return False, "需要 x1/y1/x2/y2"
    gw = _pygetwindow()
    target = None
    try:
        for win in gw.getAllWindows():
            try:
                t = getattr(win, "title", "") or ""
                if not t or not getattr(win, "visible", True):
                    continue
                if not any(k in t for k in DRAG_SAFE_TITLES):
                    continue
                if win.left <= x1 <= win.right and win.top <= y1 <= win.bottom:
                    target = win
                    break
            except Exception:
                continue
    except Exception:
        target = None
    if not target:
        return False, "这里不能拖（只能在画图/记事本/浏览器里拖）"
    for (x, y) in ((x1, y1), (x2, y2)):
        if not (target.left <= x <= target.right and target.top <= y <= target.bottom):
            return False, "拖动要整个落在同一个窗口里"
    pyautogui.FAILSAFE = False
    pyautogui.moveTo(x1, y1, duration=0.12)
    pyautogui.mouseDown()
    pyautogui.moveTo(x2, y2, duration=0.35)
    pyautogui.mouseUp()
    return True, "从(%d,%d)拖到(%d,%d)" % (x1, y1, x2, y2)




# ---------------- 操控权闸门：陪玩开着，她才允许用鼠标键盘 ----------------
COMPANION_STATE = "http://127.0.0.1:8003/api/companion/state"
GATE_TOKEN = r"D:\你的数据目录\gate_token.txt"
_companion_cache = {"t": 0.0, "on": False}


def _read_token():
    try:
        with open(GATE_TOKEN, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def companion_on(force=False):
    """读陪玩的真实开关（5 秒缓存）；你开或她自己开都算"""
    import time as _t
    now = _t.time()
    if not force and now - _companion_cache["t"] < 5:
        return _companion_cache["on"]
    try:
        import urllib.request
        url = COMPANION_STATE + "?t=" + _read_token()
        with urllib.request.urlopen(url, timeout=6) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        on = bool(j.get("on"))
    except Exception:
        on = False
    _companion_cache["t"] = now
    _companion_cache["on"] = on
    return on




UI_SCRIPT = r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = [System.Windows.Automation.Condition]::TrueCondition
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
$result = @()
foreach ($w in $wins) {
  try {
    $wc = $w.Current
    $rect = $wc.BoundingRectangle
    if (-not $wc.Name) { continue }
    if ($rect.Width -lt 150 -or $rect.X -lt -1000) { continue }
    $items = @()
    $kids = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
    $n = 0
    foreach ($e in $kids) {
      try {
        $c = $e.Current
        if (-not $c.Name) { continue }
        $tp = $c.ControlType.ProgrammaticName
        if ($tp -notmatch 'Button|Edit|ListItem|MenuItem|TabItem|CheckBox|Hyperlink|ComboBox|RadioButton') { continue }
        $r = $c.BoundingRectangle
        if ($r.Width -lt 6 -or $r.Height -lt 6) { continue }
        $nm = ($c.Name -replace '\s+', ' ')
        if ($nm.Length -gt 40) { $nm = $nm.Substring(0, 40) }
        $items += [pscustomobject]@{
          name = $nm
          type = ($tp -replace 'ControlType\.', '')
          x = [int]($r.X + $r.Width / 2)
          y = [int]($r.Y + $r.Height / 2)
        }
        $n++
        if ($n -ge 30) { break }
      } catch {}
    }
    if ($items.Count -gt 0) {
      $result += [pscustomobject]@{ window = $wc.Name; items = $items }
    }
  } catch {}
}
if ($result.Count -eq 0) { $json = "[]" } else { $json = $result | ConvertTo-Json -Depth 5 -Compress }
[System.IO.File]::WriteAllText($env:DSH_UI_OUT, $json, (New-Object System.Text.UTF8Encoding($false)))
'''


def phys_ui(p):
    import subprocess
    import tempfile
    try:
        fd, path = tempfile.mkstemp(suffix=".ps1")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(UI_SCRIPT)
        out_path = path + ".json"
        env = dict(os.environ)
        env["DSH_UI_OUT"] = out_path
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", path], capture_output=True, text=True, timeout=25, env=env)
        try:
            os.remove(path)
        except OSError:
            pass
        raw = ""
        try:
            with io.open(out_path, encoding="utf-8") as f:
                raw = f.read().strip()
            os.remove(out_path)
        except OSError:
            raw = ""
        data = json.loads(raw) if raw else []
    except Exception as exc:  # noqa: BLE001
        return False, {"error": "看不到界面元素：%s" % exc}
    if isinstance(data, dict):
        data = [data]
    slim = []
    for w in data[:5]:
        items = (w.get("items") or [])[:8]
        slim.append({"window": str(w.get("window") or "")[:30], "items": items})
    return True, slim


def phys_zoom(p):
    from PIL import ImageGrab
    try:
        x = int(p["x"]); y = int(p["y"])
        w = int(p.get("w") or 360); h = int(p.get("h") or 240)
    except Exception:
        return False, "需要 x/y（宽高可选）"
    sw, sh = _screen_size()
    left = max(0, min(max(0, sw - 20), x - w // 2))
    top = max(0, min(max(0, sh - 20), y - h // 2))
    right = min(sw, left + w)
    bottom = min(sh, top + h)
    img = ImageGrab.grab(bbox=(left, top, right, bottom))
    img = img.resize((img.width * 2, img.height * 2))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=72, optimize=True)
    return True, {"png": base64.b64encode(buf.getvalue()).decode(),
                  "left": left, "top": top, "width": right - left, "height": bottom - top}




FULL_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = [System.Windows.Automation.Condition]::TrueCondition
$fg = [System.Windows.Automation.AutomationElement]::FocusedElement
$win = $fg
$guard = 0
while ($win -ne $null -and $guard -lt 12) {
  $guard++
  try {
    $parent = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($win)
  } catch { $parent = $null }
  if ($parent -eq $null -or $parent -eq $root) { break }
  $win = $parent
}
if ($null -eq $win -or $win -eq $root) { $win = $root }
$items = @()
$n = 0
$kids = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
foreach ($e in $kids) {
  try {
    $c = $e.Current
    $r = $c.BoundingRectangle
    if ($r.Width -lt 6 -or $r.Height -lt 6) { continue }
    $nm = ($c.Name -replace '\s+', ' ')
    if (-not $nm) { continue }
    if ($nm.Length -gt 50) { $nm = $nm.Substring(0, 50) }
    $tp = ($c.ControlType.ProgrammaticName -replace 'ControlType\.', '')
    $items += [pscustomobject]@{
      name = $nm; type = $tp
      x = [int]($r.X + $r.Width / 2); y = [int]($r.Y + $r.Height / 2)
    }
    $n++
    if ($n -ge 60) { break }
  } catch {}
}
if ($items.Count -eq 0) { $json = "[]" } else {
  $json = @([pscustomobject]@{ window = $win.Current.Name; items = $items }) | ConvertTo-Json -Depth 5 -Compress
}
[System.IO.File]::WriteAllText($env:DSH_UI_OUT, $json, (New-Object System.Text.UTF8Encoding($false)))
"""


def phys_winlist(p):
    """数据版"看到什么"：窗口标题 + 位置 + 前台（不截屏、不用视觉模型）"""
    gw = _pygetwindow()
    fg = _foreground_title()
    out = []
    try:
        for win in gw.getAllWindows():
            try:
                t = (getattr(win, "title", "") or "").strip()
                if not t or not getattr(win, "visible", True) or getattr(win, "isMinimized", False):
                    continue
                if win.width < 80 or win.height < 60:
                    continue
                out.append({"title": t[:60], "left": int(win.left), "top": int(win.top),
                            "width": int(win.width), "height": int(win.height),
                            "foreground": t == fg})
            except Exception:
                continue
    except Exception:
        pass
    return True, out[:20]


def _run_uia(script):
    import subprocess
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(script)
    out_path = path + ".json"
    env = dict(os.environ)
    env["DSH_UI_OUT"] = out_path
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                   capture_output=True, text=True, timeout=25, env=env)
    try:
        os.remove(path)
    except OSError:
        pass
    raw = ""
    try:
        with io.open(out_path, encoding="utf-8") as f:
            raw = f.read().strip()
        os.remove(out_path)
    except OSError:
        raw = ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        data = [data]
    return data


def phys_uifull(p):
    """前台窗口的全部可点元素（最多 60 个）"""
    try:
        return True, _run_uia(FULL_SCRIPT)[:1]
    except Exception as exc:  # noqa: BLE001
        return False, {"error": str(exc)[:120]}


def phys_close_win(p):
    """按标题激活某个窗口再关掉它（她收工时用；不碰宠物/部署者窗口）"""
    import pyautogui
    title = str(p.get("title") or "").strip()
    if not title:
        return False, "没说关哪个"
    skip = ("TA桌宠", "DSH 伴侣", "DeepSeek Harness", "Program Manager", "NVIDIA")
    if any(k in title for k in skip):
        return False, "这个不能关"
    gw = _pygetwindow()
    for w in gw.getAllWindows():
        try:
            if title[:12] in (w.title or "") and getattr(w, "visible", True):
                w.activate()
                time.sleep(0.35)
                pyautogui.FAILSAFE = False
                pyautogui.hotkey("alt", "f4")
                time.sleep(0.5)
                return True, "关掉了：%s" % (w.title or "")[:20]
        except Exception:
            continue
    return False, "没找到这个窗口"


LAST_SYNTHETIC = {"t": __import__("time").time()}


def _touch_synthetic():
    import time as _t
    LAST_SYNTHETIC["t"] = _t.time()


def phys_dad(p):
    """你在不在用电脑：最近 150 秒有输入，且不是她自己刚打的（她自己的输入不算）。"""
    import time as _t
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    li = LASTINPUTINFO()
    li.cbSize = ctypes.sizeof(LASTINPUTINFO)
    idle_sec = 9999.0
    try:
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            tick = ctypes.windll.kernel32.GetTickCount64()
            idle_sec = max(0.0, (tick - li.dwTime) / 1000.0)
    except Exception:
        pass
    since_her = _t.time() - float(LAST_SYNTHETIC.get("t") or 0)
    # 你 = 最近有输入（<120s）且这次输入发生在"她最后一次动手"之后
    dad_active = (idle_sec < 120) and (since_her > idle_sec + 2)
    return True, {"idle_sec": round(idle_sec, 1),
                  "since_her_input": round(since_her, 1),
                  "dad_active": bool(dad_active)}


PHYS_ACTIONS = {
    "shot": phys_shot,
    "info": phys_info,
    "move": phys_move,
    "click": lambda p: _click_at(p, "single"),
    "dclick": lambda p: _click_at(p, "double"),
    "rclick": lambda p: _click_at(p, "right"),
    "type": phys_type,
    "key": phys_key,
    "scroll": phys_scroll,
    "drag": phys_drag,
    "ui": phys_ui,
    "zoom": phys_zoom,
    "winlist": phys_winlist,
    "uifull": phys_uifull,
    "close_win": phys_close_win,
    "dad": phys_dad,
}


def list_windows():
    gw = _pygetwindow()
    out = []
    for w in gw.getAllWindows():
        try:
            if w.title and w.visible and not w.isMinimized:
                out.append(w.title.strip()[:80])
        except Exception:
            continue
    return out[:40]


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
        path = urlparse(self.path).path
        if path == "/health":
            return self._json({"ok": True, "stopped": stopped()})
        if path == "/hand":
            return self._json({"ok": True, "physical_actions": sorted(PHYS_ACTIONS),
                               "companion_on": companion_on(force=True)})
        if path == "/actions":
            return self._json({"ok": True, "actions": sorted(ACTIONS),
                               "apps": sorted(APPS)})
        if path == "/windows":
            try:
                return self._json({"ok": True, "windows": list_windows()})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:160]}, 500)
        if path == "/running":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            exe = (q.get("exe") or ["ZenlessZoneZero.exe"])[0]
            try:
                import psutil
                hit = [p.info["name"] for p in psutil.process_iter(["name"])
                       if (p.info.get("name") or "").lower() == exe.lower()]
                return self._json({"ok": True, "exe": exe, "running": bool(hit)})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:120]}, 500)
        if path == "/volume":
            try:
                _d, v = _speakers()
                return self._json({"ok": True,
                                   "volume": round(v.GetMasterVolumeLevelScalar() * 100),
                                   "muted": bool(v.GetMute())})
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:160]}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}

        if path == "/hand":
            if not companion_on():
                return self._json({"ok": False,
                                   "error": "陪玩没开，她的手现在不该动（操控权只在陪玩开启时）"}, 403)
            act = str(body.get("action") or "").lower()
            fn = PHYS_ACTIONS.get(act)
            if not fn:
                return self._json({"ok": False, "error": "物理通道不支持：%s" % act}, 400)
            if stopped():
                return self._json({"ok": False, "error": "已急停"}, 403)
            try:
                ok, res = fn(body)
            except Exception as exc:  # noqa: BLE001
                ok, res = False, "动作出错：%s" % exc
            log("hand:" + act, body, ok, res if isinstance(res, str) else "")
            return self._json({"ok": ok, "result": res})

        if path == "/stop":
            open(STOP_FLAG, "w").write(str(time.time()))
            log("stop", {}, True)
            return self._json({"ok": True, "stopped": True})
        if path == "/resume":
            try:
                os.remove(STOP_FLAG)
            except OSError:
                pass
            log("resume", {}, True)
            return self._json({"ok": True, "stopped": False})

        if path != "/do":
            return self._json({"ok": False, "error": "not found"}, 404)

        if stopped():
            log("blocked", body, False, "急停中")
            return self._json({"ok": False, "error": "已急停"}, 403)

        action = str(body.get("action") or "").strip()
        fn = ACTIONS.get(action)
        if not fn:
            log("unknown", body, False)
            return self._json({"ok": False, "error": "不支持的动作：%s" % action}, 400)

        try:
            ok, result = fn(body)
        except Exception as exc:  # noqa: BLE001
            log(action, body, False, str(exc)[:160])
            return self._json({"ok": False, "error": str(exc)[:200]}, 500)

        log(action, body, ok, result if isinstance(result, str) else "")
        return self._json({"ok": ok, "result": result if action != "screenshot" else "shot",
                           "image": result if action == "screenshot" and ok else None})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.makedirs(LOG_DIR, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("TA的手：http://127.0.0.1:%d（白名单 %d 个动作）" % (PORT, len(ACTIONS)), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
