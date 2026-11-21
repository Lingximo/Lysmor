# -*- coding: utf-8 -*-
"""TA玩游戏·手眼调度器（端口 8803）

A（手）：按她学过的键位打一套
B（眼）：每隔几秒看一眼屏幕，做慢节奏判断（血量/战斗/菜单）
C（实时反应）：明确不做

设计要害（部署者问过"A 和 B 会不会打架"）：
  · 只有本服务能发按键，A 和 B 都是"请求方"
  · 一把锁：同一时刻只允许一套动作在跑
  · 优先级：high（生存类：喝药/停手）可以抢占 low（连招），
            抢占 = 干净地中止整套，不是插进中间
  · 前台守卫：当前窗口不是绝区零，一个字都不发
  · dry 模式：默认只记录不按键；确认没问题再切 live

接口：
  GET  /state                     → 运行状态
  POST /mode {"dry":true|false}   → 切换演练/真发键
  POST /play {"keys":[...],"priority":"low|high","reason":""}
  POST /stop                      → 立刻停手
  GET  /health
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = 8803
LOG_DIR = r"D:\你的数据目录\logs"
LOG = os.path.join(LOG_DIR, "game_player.log")
STOP_FLAG = os.path.join(LOG_DIR, "hands.stop")     # 和她的手共用急停
GAME_TITLES = ("绝区零", "Zenless", "ZENLESS")

PLAYER_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player.json")


def _load_cfg() -> dict:
    try:
        with open(PLAYER_CFG, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


_CFG = _load_cfg()

STATE = {
    "dry": bool(_CFG.get("dry", True)),   # 默认演练：只记录，不发键
    "auto_replay": bool(_CFG.get("auto_replay", True)),
    "locked": False,
    "owner": "",             # combo / heal / manual
    "seq": [],
    "last_action_at": 0.0,
    "count": 0,
    "observer": {"on": False, "last_at": 0.0, "hp": None, "in_fight": None,
                 "menu": None, "verdict": "", "errors": 0},
}


def log(tag: str, detail) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), tag,
                json.dumps(detail, ensure_ascii=False)[:400]))
    except Exception:
        pass


def stopped() -> bool:
    return os.path.exists(STOP_FLAG)


def _enum_windows() -> list:
    """用 Win32 API 枚举可见窗口标题（pygetwindow 偶尔为空时的兜底）。"""
    out = []
    try:
        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            out.append((int(hwnd), buf.value))
            return True

        user32.EnumWindows(EnumProc(_cb), 0)
    except Exception:
        pass
    return out


def _focus_by_title(title: str) -> str:
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if w.title and title.lower() in w.title.lower():
                if w.isMinimized:
                    w.restore()
                w.activate()
                return w.title
    except Exception:
        pass
    for hwnd, t in _enum_windows():
        if title.lower() in t.lower():
            try:
                ctypes.windll.user32.ShowWindow(hwnd, 9)      # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                return t
            except Exception:
                continue
    return ""


def foreground_title() -> str:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value or ""
    except Exception:
        return ""


def game_foreground() -> bool:
    t = foreground_title()
    return any(k.lower() in t.lower() for k in GAME_TITLES)


# ---------------- A：键位回放 ----------------

KEY_ALIAS = {
    "shift": "shift", "ctrl": "ctrl", "alt": "alt", "space": "space",
    "j": "j", "k": "k", "l": "l", "u": "u", "i": "i", "o": "o", "p": "p",
    "q": "q", "e": "e", "r": "r", "f": "f", "g": "g", "h": "h",
    "w": "w", "a": "a", "s": "s", "d": "d", "z": "z", "x": "x", "c": "c",
    "v": "v", "b": "b", "n": "n", "m": "m",
    "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
    "esc": "esc", "tab": "tab", "delete": "delete",
}

_cancel = threading.Event()


def _press_token(token: str, dry: bool) -> None:
    """token: 'j' / 'shift' / 'shift+j'（组合键按住再点）"""
    import pyautogui
    parts = [p.strip().lower() for p in token.split("+") if p.strip()]
    parts = [KEY_ALIAS.get(p, p) for p in parts]
    if dry:
        return
    if len(parts) == 1:
        pyautogui.press(parts[0], interval=0)
    else:
        for p in parts[:-1]:
            pyautogui.keyDown(p)
        pyautogui.press(parts[-1], interval=0)
        for p in reversed(parts[:-1]):
            pyautogui.keyUp(p)


def run_sequence(keys, priority: str, reason: str, gap: float = 0.06) -> dict:
    if stopped():
        return {"ok": False, "error": "急停中"}
    if not game_foreground():
        return {"ok": False, "error": "绝区零不在前台，不发键", "foreground": foreground_title()[:40]}
    if STATE["locked"] and priority != "high":
        return {"ok": False, "error": "正在执行别的动作"}
    if STATE["locked"] and priority == "high":
        _cancel.set()          # 抢占：让低优先级干净地退出
        time.sleep(0.05)
    _cancel.clear()
    STATE["locked"] = True
    STATE["owner"] = reason or "combo"
    STATE["seq"] = list(keys)[:24]
    dry = bool(STATE["dry"])
    sent = []
    try:
        for k in STATE["seq"]:
            if _cancel.is_set() or stopped():
                log("abort", {"reason": reason, "at": k})
                return {"ok": False, "error": "被抢占/急停", "sent": sent}
            _press_token(str(k), dry)
            sent.append(str(k))
            time.sleep(max(0.02, gap))
        STATE["count"] += 1
        STATE["last_action_at"] = time.time()
        log("play", {"keys": sent, "dry": dry, "priority": priority, "reason": reason})
        return {"ok": True, "dry": dry, "sent": sent}
    finally:
        STATE["locked"] = False
        STATE["owner"] = ""
        STATE["seq"] = []


# ---------------- B：低频观察 ----------------

OBSERVE_EVERY = 6.0


def _grab_jpeg(width=720):
    from PIL import ImageGrab
    import io as _io
    img = ImageGrab.grab()
    img.thumbnail((width, width))
    buf = _io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=68)
    import base64
    return base64.b64encode(buf.getvalue()).decode()


def _ask_vision(b64: str) -> str:
    import requests
    prompt = ("这是电脑游戏画面。只用一行回答三个值，格式："
              "血量=<0-100 的整数> 战斗=<是/否> 菜单=<是/否>")
    r = requests.post("http://127.0.0.1:11434/api/generate", json={
        "model": "qwen3-vl:4b", "prompt": prompt, "images": [b64],
        "stream": False, "options": {"num_predict": 900, "temperature": 0.1}},
        timeout=120)
    return str((r.json() or {}).get("response") or "").strip()


def _parse_vision(text: str) -> dict:
    out = {"hp": None, "in_fight": None, "menu": None, "raw": text[:120]}
    m = re.search(r"血量\s*[=:：]?\s*(\d{1,3})", text)
    if m:
        out["hp"] = max(0, min(100, int(m.group(1))))
    m = re.search(r"战斗\s*[=:：]?\s*(是|否|有|无)", text)
    if m:
        out["in_fight"] = m.group(1) in ("是", "有")
    m = re.search(r"菜单\s*[=:：]?\s*(是|否)", text)
    if m:
        out["menu"] = m.group(1) == "是"
    return out


def observer_loop():
    """背景线程：只有游戏在前台时才看，看一次约 4~6 秒。"""
    while True:
        time.sleep(OBSERVE_EVERY)
        try:
            if stopped() or not game_foreground():
                continue
            b64 = _grab_jpeg()
            text = _ask_vision(b64)
            info = _parse_vision(text)
            STATE["observer"].update({
                "on": True, "last_at": time.time(), "hp": info["hp"],
                "in_fight": info["in_fight"], "menu": info["menu"],
                "verdict": info["raw"],
            })
            log("observe", info)
            # 生存类判断 → 高优先级抢占
            # 只有明确在战斗里、且血量低才喝药（加载界面常被读成 0 血）
            if (info["in_fight"] is True and info["hp"] is not None
                    and info["hp"] < 30 and not STATE["locked"]):
                run_sequence(["1"], "high", "heal")
            if info["menu"] and STATE["locked"]:
                run_sequence(["esc"], "high", "menu")
        except Exception as exc:  # noqa: BLE001
            STATE["observer"]["errors"] += 1
            log("observe_error", {"error": str(exc)[:150]})


# ---------------- HTTP ----------------

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
        if path == "/state":
            return self._json({"ok": True, "state": STATE, "config": PLAYER_CFG,
                               "foreground": foreground_title()[:60],
                               "game": game_foreground()})
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}

        if path == "/mode":
            STATE["dry"] = bool(body.get("dry", True))
            log("mode", {"dry": STATE["dry"]})
            return self._json({"ok": True, "dry": STATE["dry"]})

        if path == "/stop":
            _cancel.set()
            try:
                open(STOP_FLAG, "w").write(str(time.time()))
            except Exception:
                pass
            log("stop", {})
            return self._json({"ok": True, "stopped": True})

        if path == "/play_rule":
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import playbook
                q = str(body.get("query") or "")
                rules = playbook.search(q, 1) if q else []
                if not rules:
                    # 泛泛一句"打一套"搜不到具体招式 → 退回最近学的那条
                    rules = playbook.recent(1)
                if not rules:
                    return self._json({"ok": False, "error": "还没学过玩法"}, 409)
                rule = rules[0]
                keys = list(rule.get("keys") or [])
                if not keys:
                    return self._json({"ok": False, "error": "这条玩法没记键位"}, 409)
                res = run_sequence(keys, "low", "rule:%s" % rule.get("id"))
                res["rule"] = {"id": rule.get("id"), "summary": rule.get("summary", "")[:60]}
                return self._json(res, 200 if res.get("ok") else 409)
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:150]}, 500)

        if path == "/focus":
            try:
                title = str(body.get("title") or "绝区零")
                got = _focus_by_title(title)
                time.sleep(0.4)
                if got:
                    return self._json({"ok": True, "focused": got[:40],
                                       "foreground": foreground_title()[:40]})
                return self._json({"ok": False, "error": "没找到游戏窗口",
                                   "titles": [t for _, t in _enum_windows()][:20]}, 404)
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": str(exc)[:150]}, 500)

        if path == "/windows":
            return self._json({"ok": True, "titles": [t for _, t in _enum_windows()][:40]})

        if path == "/play":
            keys = body.get("keys") or []
            if not isinstance(keys, list) or not keys:
                return self._json({"ok": False, "error": "keys 为空"}, 400)
            keys = [str(k) for k in keys][:24]
            priority = str(body.get("priority") or "low")
            reason = str(body.get("reason") or "combo")[:40]
            res = run_sequence(keys, priority if priority in ("low", "high") else "low", reason)
            return self._json(res, 200 if res.get("ok") else 409)

        return self._json({"ok": False, "error": "not found"}, 404)


def main():
    for s in (sys.stdout,):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.makedirs(LOG_DIR, exist_ok=True)
    threading.Thread(target=observer_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("TA玩游戏的调度器：http://127.0.0.1:%d（默认演练 dry=true）" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
