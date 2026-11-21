# -*- coding: utf-8 -*-
"""陪玩看屏幕：采样 → 只在换镜头时看一组 → 写 state.json / event.json。

和旧版的区别（2026-11-02 改）：
  旧：每 12 秒抓一张整屏 → 每次调用 num_predict=600（实测 7.2 秒，回答常是空的）
  新：每秒采缩略图算帧间差 → 只在换镜头/大变化时，把最近几帧拼成一张带编号和
      时间的宫格图，一次推理看一段（1.5~2.5 秒）
      · 画面不动就不调用，GPU 不再常驻；
      · 一次看一组，"从菜单进对局、血量掉了一半"这种变化才说得出来；
      · 每格有时间戳，下游可以引用"第 3 格 21:04:12"。

对外接口没变：GET /api/state、POST /api/watch，state.json 字段只增不改。
"""

import base64
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
import win32gui
from PIL import ImageGrab

import scene_watch

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state.json")
EVENT = os.path.join(ROOT, "event.json")
SHEET_DIR = os.path.join(ROOT, "sheets")
PORT = 8782
OLLAMA = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3-vl:4b"
VISION_TOKENS = int(os.environ.get("SCREEN_VISION_TOKENS", "200"))
KEEP_SHEETS = 10

LOCK = threading.Lock()
WATCHING = False
# 2026-11-09：防"孤儿观察"——陪玩关掉/服务重启后 watching 可能残留，
# 视频服务每 30 秒发一次 /api/watch/ping；超过 WATCH_IDLE_SECS 没心跳就自己关。
WATCH_LAST_PING = 0.0
WATCH_IDLE_SECS = float(os.environ.get("WATCH_IDLE_SECS") or 180)
LAST_EVENT = ""
LAST_TITLE = ""
LAST_GAME = ""
LAST_SCENE = ""
LAST_SUMMARY = ""
LAST_AT = 0.0

BAD_TITLES = (
    "TA陪玩", "companion", "Microsoft Edge", "Google Chrome",
    "DeepSeek", "AstrBot", "Program Manager", "微信", "媒体播放器",
)


def _extract_json(text):
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _state(**kw):
    base = {
        "watching": WATCHING,
        "title": LAST_TITLE,
        "game": LAST_GAME,
        "scene": LAST_SCENE,
        "summary": LAST_SUMMARY,
        "event": "",
        "updated": LAST_AT,
        "sampled_at": time.time(),
    }
    base.update(kw)
    _write(STATE, base)


# ---------------------------------------------------------------- 抓窗口
def _find_target():
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) or ""
    if not title or any(k in title for k in BAD_TITLES):
        return 0, ""
    if not win32gui.IsWindowVisible(hwnd):
        return 0, ""
    return hwnd, title


def _grab():
    """2026-11-10：不再只截前台窗口。

    部署者要的是"我见即她所见"——整块主屏，包括桌面、任务栏、
    所有当时可见的窗口；没打开/最小化的窗口本来就不会出现在像素里。
    """
    hwnd, title = _find_target()
    try:
        # all_screens=False = 只截主屏，和部署者眼睛看到的一致
        img = ImageGrab.grab(all_screens=False).convert("RGB")
        img.thumbnail((1440, 1440), 1)
        return title, img
    except Exception as exc:  # noqa: BLE001
        print("grab failed:", str(exc)[:160], flush=True)
        return title, None


# ---------------------------------------------------------------- 让模型看一组
def _save_sheet(sheet):
    try:
        os.makedirs(SHEET_DIR, exist_ok=True)
        name = "sheet_%s.jpg" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SHEET_DIR, name)
        sheet.save(path, "JPEG", quality=88)
        files = sorted(f for f in os.listdir(SHEET_DIR) if f.endswith(".jpg"))
        for old in files[:-KEEP_SHEETS]:
            try:
                os.remove(os.path.join(SHEET_DIR, old))
            except OSError:
                pass
        return path
    except Exception:  # noqa: BLE001
        return ""


def _describe(sheet, meta, title=""):
    """让模型看一组图，返回 {'summary','event','scene'}。

    为什么不要 JSON：这个 4B 模型对格式要求会一直"想"，实测 160→520 token 全花在
    自我怀疑上，response 一个字节都没有。改成人话提问，然后把**思考文本**当描述用
    （视频通话那边同款做法），再做一次清洗；事件用关键词判，稳定得多。
    """
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    resp = requests.post(
        OLLAMA,
        json={
            "model": MODEL,
            "prompt": scene_watch.describe_prompt(len(meta), title),
            "images": [b64],
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.05, "num_predict": VISION_TOKENS},
        },
        timeout=120,
    )
    data = resp.json()
    raw = (data.get("response") or "").strip() or (data.get("thinking") or "").strip()
    if not raw:
        raise ValueError("模型没有输出")
    summary = _summarize(raw)
    return {
        "summary": summary,
        # 事件只看清洗后的描述：思考文本里会把我提示词里的"死亡/胜利"念一遍，
        # 拿它判事件必然假阳性（自测里就误报过一次 death）
        "event": _detect_event(summary),
        "scene": _detect_scene(summary),
        "raw_len": len(raw),
    }


META_WORDS = (
    "用户", "要求", "我需要", "首先", "让我", "提示词", "应该", "可能", "需要",
    "观察", "判断", "根据", "所以", "总结", "一句话", "组织语言", "思考", "分析", "一两句", "要说", "说画面", "现在要",
)
SCENE_WORDS = (
    "画面", "场景", "角色", "界面", "地图", "房间", "战斗", "血条", "敌人", "BOSS",
    "技能", "菜单", "结算", "文字", "图标", "鼠标", "窗口", "游戏",
)


def _summarize(text, limit=80):
    """从模型的自言自语里挑最像"画面描述"的一两句。"""
    text = (text or "").replace("<think>", " ").replace("</think>", " ").replace("\n", " ")
    text = text.strip()
    if not text:
        return ""
    # 掐掉开头的"用户想要我…"这类开场白
    head = None
    for opener in ("用户", "首先", "让我", "我需要", "根据"):
        idx = text.find(opener)
        if idx == 0:
            head = opener
            break
    if head:
        cut = max(text.find(ch) for ch in "。！？，")
        if cut > 0:
            rest = text[cut + 1:].strip()
            if len(rest) >= 10:
                text = rest
    pieces = [p.strip() for p in text.replace("！", "。").replace("？", "。").split("。")]
    scored = []
    for i, piece in enumerate(pieces):
        if not piece:
            continue
        score = 0
        if any(k in piece for k in SCENE_WORDS):
            score += 2
        if any(k in piece for k in META_WORDS):
            score -= 3
        if len(piece) < 6:
            score -= 1
        scored.append((score, i, piece))
    if not scored:
        return text[:limit]
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = [p for s, _, p in scored if s > 0][:2]
    out = "。".join(chosen).strip("。 ") if chosen else scored[0][2]
    # 掐掉句首的连接词（"不过看截图里…""然后他…"），读起来才像一句描述
    for lead in ("不过", "然后", "另外", "其实", "所以", "但是", "而且", "总的来说", "总之", "看起来"):
        if out.startswith(lead):
            out = out[len(lead):].lstrip("，,、 ")
    if len(out) > limit:
        # 别切半个词
        cut = max(out.rfind(ch, 0, limit) for ch in "。，；,;")
        out = out[: cut + 1] if cut >= 12 else out[:limit]
    return out


EVENT_WORDS = {
    "death": ("死亡", "阵亡", "死了", "倒下", "团灭", "黑屏", "复活", "失败", "没了"),
    "victory": ("胜利", "通关", "赢了", "击败", "完成任务", "通关了"),
    "low_hp": ("残血", "红血", "血量很低", "快没血", "只剩一点血", "濒死", "血条见底"),
}


def _detect_event(text):
    text = text or ""
    # 去掉括号里的解释和引号里的词：模型爱写「（比如「胜利」字样、通关界面）」，
    # 那是在解释规则，不是报告事件；不剥掉就会误报
    text = re.sub(r"[（(][^）)]{0,40}[）)]", "", text)
    text = re.sub(r"[“\"「『][^”\"」』]{0,24}[”\"」』]", "", text)
    for name, words in EVENT_WORDS.items():
        for word in words:
            idx = text.find(word)
            if idx < 0:
                continue
            # 排除否定："没有死亡""未出现胜利"不能触发事件，
            # 否则她会在人家好好活着的时候来一句"你死了？"
            # 窗口取 12 个字："未出现死亡或胜利" 里"胜利"前面 6 个字才看得到否定
            prefix = text[max(0, idx - 12):idx]
            if any(neg in prefix for neg in ("没有", "没出现", "未出现", "未见", "没", "未", "无", "不", "并非")):
                continue
            return name
    return "none"


def _detect_scene(text):
    text = text or ""
    if any(w in text for w in ("结算", "胜利", "失败", "通关")):
        return "结算"
    if any(w in text for w in ("菜单", "开始界面", "主界面", "选人")):
        return "菜单"
    return "对局"


# ---------------------------------------------------------------- 结果落地
def _clean_title(title):
    if not title:
        return ""
    for suffix in (" - Google Chrome", " - Microsoft Edge", " - Mozilla Firefox",
                   " - Visual Studio Code", " — Mozilla Firefox"):
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title.strip()


def _apply(title, obj, result):
    global LAST_EVENT, LAST_TITLE, LAST_GAME, LAST_SCENE, LAST_SUMMARY, LAST_AT

    summary = str(obj.get("summary") or "").strip()
    cells = result.get("cells") or []
    sheet_path = _save_sheet(result["sheet"]) if result.get("sheet") is not None else ""

    if not summary:
        # 什么都没看懂：不编造描述，只保留窗口标题，别让上下文凭空空掉
        _state(title=_clean_title(title), game="", scene="", summary="", event="",
               updated=LAST_AT, cells=len(cells), reason=result.get("reason"),
               sheet=sheet_path)
        return

    event = str(obj.get("event") or "none")
    LAST_TITLE = _clean_title(title)
    LAST_GAME = LAST_GAME or LAST_TITLE
    LAST_SCENE = str(obj.get("scene") or "")
    LAST_SUMMARY = summary
    LAST_AT = time.time()

    _state(
        title=LAST_TITLE,
        game=LAST_GAME,
        scene=LAST_SCENE,
        summary=summary,
        event=event,
        updated=LAST_AT,
        cells=len(cells),
        cell_times=[c.get("clock") for c in cells],
        reason=result.get("reason"),
        sheet=sheet_path,
        stats=dict(WATCHER.stats) if WATCHER else {},
    )

    if event not in ("", "none") and event != LAST_EVENT:
        LAST_EVENT = event
        _write(
            EVENT,
            {
                "id": "%d-%s" % (int(time.time() * 1000), event),
                "event": event,
                "game": LAST_GAME,
                "summary": summary,
                "cells": cells,
                "sheet": sheet_path,
                "time": time.time(),
            },
        )


# ---------------------------------------------------------------- 主循环
WATCHER = None


def _make_watcher():
    def describe(sheet, meta, title=""):
        return _describe(sheet, meta, title)

    return scene_watch.SceneWatcher(_grab, describe, log=lambda m: print("watch:", m, flush=True))


def _loop():
    global WATCHER
    if WATCHER is None:
        WATCHER = _make_watcher()
    while True:
        try:
            if WATCHING and WATCH_LAST_PING and (time.time() - WATCH_LAST_PING) > WATCH_IDLE_SECS:
                globals()["WATCHING"] = False
                try:
                    _state(watching=False)
                except Exception:
                    pass
                print("[屏幕观察] %.0f 秒没心跳，自动关掉" % WATCH_IDLE_SECS, flush=True)
            if WATCHING:
                result = WATCHER.step()
                if result.get("action") == "described":
                    _apply(result.get("title") or "", result.get("obj") or {}, result)
                elif result.get("action") == "describe-failed":
                    # 模型这次没看懂：至少把窗口标题留着，别让上下文整个空掉
                    title = result.get("title") or ""
                    if title and not LAST_SUMMARY:
                        _state(title=title, game=title, scene="游戏",
                               summary="", event="", updated=LAST_AT,
                               reason="describe-failed")
        except Exception as exc:  # noqa: BLE001
            print("screen loop:", str(exc)[:200], flush=True)
        time.sleep(scene_watch.SAMPLE_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/state":
            try:
                with open(STATE, encoding="utf-8") as f:
                    self._json(json.load(f))
            except Exception:  # noqa: BLE001
                self._json({"watching": WATCHING})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global WATCHING
        if self.path == "/api/watch/ping":
            globals()["WATCH_LAST_PING"] = time.time()
            self._json({"ok": True, "watching": WATCHING})
            return
        if self.path != "/api/watch":
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            WATCHING = bool(body.get("on"))
            globals()["WATCH_LAST_PING"] = time.time()
            if WATCHING and WATCHER is not None:
                # 重新打开时清基线，避免拿"上次的最后一帧"当对比，一开就误判成换镜头
                WATCHER._seeded = False
                WATCHER._frames = []
            _state(watching=WATCHING)
            self._json({"ok": True, "watching": WATCHING})
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": str(exc)[:200]})


if __name__ == "__main__":
    WATCHER = _make_watcher()
    try:
        _state(watching=False)   # 启动即写真实状态，清掉上次残留的 watching=true
    except Exception:
        pass
    threading.Thread(target=_loop, daemon=True).start()
    print("screen watcher (storyboard mode): http://127.0.0.1:%d" % PORT, flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
