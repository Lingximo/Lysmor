# -*- coding: utf-8 -*-
"""TA的手 · 客户端与指令解析

给各聊天入口共用：
    from hands_client import parse, call, hint_text
    act = parse("打开记事本")        # → {"action": "open_app", "app": "notepad"}
    res = call(act)                  # → {"ok": True, "result": "已打开 notepad"}
    hint_text(act, res)              # → 给模型的提示："（你刚帮他打开了记事本，成功）"

设计成"解析 → 执行 → 交给她说"，而不是让她自由发挥：
  · 只认少量固定句式，认不出就不拦（交给正常聊天）
  · 所有动作走 8010 的白名单，危险动作根本不存在
"""
from __future__ import annotations

import json
import re

import requests

BASE = "http://127.0.0.1:8010"

APPS = {
    "记事本": "notepad", "notepad": "notepad",
    "计算器": "calc", "calc": "calc",
    "资源管理器": "explorer", "文件管理器": "explorer",
    "画图": "mspaint", "mspaint": "mspaint",
    "任务管理器": "任务管理器",
    "QQ音乐": "qqmusic", "qq音乐": "qqmusic", "qqmusic": "qqmusic",
}

# 关窗口时，"关掉 X" 里的 X 必须能对上这些名字
CLOSE_NAMES = ("记事本", "计算器", "画图", "notepad", "calc", "mspaint",
               "QQ音乐", "qq音乐", "qqmusic")

_PATTERNS = [
    (re.compile(r"(玩|打开|启动|开一下)\s*(绝区零|zzz)"), lambda m: {"action": "open_app", "app": "zenless"}),
    (re.compile(r"(打开|启动|开一下)\s*(记事本|计算器|资源管理器|文件管理器|画图|任务管理器|QQ音乐|qq音乐)"),
     lambda m: {"action": "open_app", "app": APPS[m.group(2)]}),
    (re.compile(r"(音量|声音).*(大|加|调高)"), lambda m: {"action": "volume", "delta": 10}),
    (re.compile(r"(音量|声音).*(小|减|调低)"), lambda m: {"action": "volume", "delta": -10}),
    (re.compile(r"(静音|别出声|mute)"), lambda m: {"action": "volume", "mute": True}),
    (re.compile(r"(取消静音|解除静音|开声音)"), lambda m: {"action": "volume", "mute": False}),
    (re.compile(r"(下一首|切歌|下个歌)"), lambda m: {"action": "media", "key": "next"}),
    (re.compile(r"(上一首|上个歌)"), lambda m: {"action": "media", "key": "prev"}),
    (re.compile(r"(播放|暂停|继续放)"), lambda m: {"action": "media", "key": "play"}),
    (re.compile(r"(锁屏|锁定屏幕)"), lambda m: {"action": "lock"}),
    (re.compile(r"(切到|切换到|回到)\s*([^\s，。]{1,12})"),
     lambda m: {"action": "switch_window", "title": m.group(2)}),
    (re.compile(r"(关掉|关闭|关一下)\s*(%s)" % "|".join(CLOSE_NAMES)),
     lambda m: {"action": "close_window", "title": m.group(2)}),
    (re.compile(r"(把|将)?\s*(%s)\s*(关了|关掉|关一下|退掉|退出)" % "|".join(CLOSE_NAMES)),
     lambda m: {"action": "close_window", "title": m.group(2)}),
]

_PLAY_RULE = re.compile(r"(打一套|按刚才|按你学的|试一下你学的|练一下|来一套|玩一下你学的)")
_LIVE = re.compile(r"(允许你真的按|可以真的按|真按吧|开始真按)")
_DRY = re.compile(r"(先演练|别真按|演练模式|只说不按键)")

_DRAW = re.compile(r"(画个|画一张|画张|画只|画朵|画条|画颗|画幅|给我画|你画)")
_DRAW_PAT = (("鱼", "fish"), ("心", "heart"), ("星", "star"), ("浪", "wave"), ("水", "wave"))

_STOP = re.compile(r"(急停|停手|别动|停止操作|hands stop)")
_RESUME = re.compile(r"(恢复操作|可以动了|hands resume)")

_SET_VOL = re.compile(r"音量.*?(\d{1,3})\s*%?")


def parse(text: str):
    """认出"操作电脑"的指令；认不出返回 None。"""
    t = (text or "").strip()
    if not t or len(t) > 40:
        return None
    if _DRAW.search(t):
        pat = "fish"
        for k, v in _DRAW_PAT:
            if k in t:
                pat = v
                break
        return {"action": "__draw__", "pattern": pat}

    if _PLAY_RULE.search(t):
        return {"action": "__play_rule__", "query": t}
    if _LIVE.search(t):
        return {"action": "__live__"}
    if _DRY.search(t):
        return {"action": "__dry__"}
    if _STOP.search(t):
        return {"action": "__stop__"}
    if _RESUME.search(t):
        return {"action": "__resume__"}
    m = _SET_VOL.search(t)
    if m:
        try:
            v = max(0, min(100, int(m.group(1))))
            return {"action": "volume", "set": v}
        except ValueError:
            pass
    for pat, build in _PATTERNS:
        m = pat.search(t)
        if m:
            return build(m)
    return None


def call(act: dict) -> dict:
    """执行动作；返回 {"ok":bool,"result":str,"error":str}"""
    if not act:
        return {"ok": False, "error": "empty"}
    a = act.get("action")
    try:
        if a == "__stop__":
            r = requests.post(BASE + "/stop", timeout=10)
            return {"ok": r.ok, "result": "已急停，我停手了"}
        if a == "__draw__":
            pattern = act.get("pattern") or "fish"
            r = requests.post("http://127.0.0.1:8010/do",
                              json={"action": "draw", "pattern": pattern},
                              timeout=180)
            j = r.json() if r.content else {}
            if not j.get("ok"):
                return {"ok": False, "error": str(j.get("error") or "没画成")}
            doodle = str(j.get("result") or "画好了")
            # 2026-11-10：草稿交给 ComfyUI 上色（失败不影响草稿）
            import os as _os
            import re as _re
            import subprocess as _sp
            m = _re.search(r"([A-Za-z]:\\[^：]+?\.jpg)", doodle)
            if m and _os.path.exists(m.group(1)):
                import sys as _sys
                py = _sys.executable
                try:
                    out = _sp.run(
                        [py or "python", r"D:\你的数据目录\art\sketch2art.py",
                         "--input", m.group(1), "--pattern", pattern],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=420,
                        # 子进程 stdout 默认用系统编码，父进程按 UTF-8 读会乱码
                        env={**_os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
                    # 不在中文上做判断，直接找成品路径（更抗编码问题）
                    _sm = _re.search(r"sketch_[0-9_]+\.[a-z]+", out.stdout or "")
                    if _sm:
                        return {"ok": True, "result": "%s；又让 ComfyUI 上了色：%s" % (
                            doodle, _sm.group(0))}
                    if (out.returncode or 0) != 0:
                        print("[画画] 上色失败:", (out.stderr or out.stdout or "")[-300:])
                except Exception as exc:  # noqa: BLE001
                    pass
            return {"ok": True, "result": doodle}

        if a == "__play_rule__":
            # 先把游戏窗口拉到前台，否则守卫会拒绝发键
            try:
                requests.post("http://127.0.0.1:8803/focus",
                              json={"title": "绝区零"}, timeout=15)
                time.sleep(0.6)
            except Exception:  # noqa: BLE001
                pass
            r = requests.post("http://127.0.0.1:8803/play_rule",
                              json={"query": str(act.get("query") or "")}, timeout=60)
            j = r.json() if r.content else {}
            if j.get("ok"):
                keys = "/".join(str(k) for k in (j.get("sent") or []))
                return {"ok": True, "result": "按你学的打了一套：%s（%s）" % (
                    keys or "空", "演练，没真按" if j.get("dry") else "真按了")}
            return {"ok": False, "error": str(j.get("error") or "没打成")}
        if a == "__live__":
            r = requests.post("http://127.0.0.1:8803/mode", json={"dry": False}, timeout=10)
            return {"ok": r.ok, "result": "好，接下来我真按键了"}
        if a == "__dry__":
            r = requests.post("http://127.0.0.1:8803/mode", json={"dry": True}, timeout=10)
            return {"ok": r.ok, "result": "行，先演练，只记录不按"}
        if a == "__resume__":
            r = requests.post(BASE + "/resume", timeout=10)
            return {"ok": r.ok, "result": "好，可以继续"}
        r = requests.post(BASE + "/do", json=act, timeout=30)
        j = r.json() if r.content else {}
        if j.get("ok"):
            return {"ok": True, "result": str(j.get("result") or "好了")}
        return {"ok": False, "error": str(j.get("error") or ("HTTP %d" % r.status_code))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:160]}


def hint_text(act: dict, res: dict) -> str:
    """给她的提示：让她用自己的口吻说一句。"""
    name = {
        "open_app": "打开程序", "switch_window": "切换窗口", "close_window": "关掉窗口",
        "volume": "调音量", "media": "控制播放", "lock": "锁屏",
        "__draw__": "在画图里画一张", "__play_rule__": "按学过的键位打一套", "__live__": "允许真按键", "__dry__": "切回演练",
        "__stop__": "停止操作", "__resume__": "恢复操作",
    }.get(act.get("action"), act.get("action"))
    if res.get("ok"):
        return "（你刚替他做了：%s，结果：%s）用一句话自然回应，不要提工具、接口。" % (
            name, res.get("result"))
    return "（你想替他做：%s，但失败了：%s）用一句话告诉他没成功，别编理由。" % (
        name, res.get("error"))


if __name__ == "__main__":
    for s in ["打开记事本", "音量调到30", "切到记事本", "关掉记事本", "下一首", "锁屏", "急停", "胡言乱语"]:
        print(s, "→", parse(s))
