# -*- coding: utf-8 -*-
"""她自己在电脑上做主（v12）：不用视觉模型，靠"数据"读状态

数据来自她的手（本地接口，不是视觉模型）：
  winlist  窗口清单：标题 + 位置 + 谁在前台
  uifull   前台窗口里所有可点元素：名字 + 类型 + 屏幕坐标
  icon_map 她之前认得的桌面图标（名字 → 坐标）
  info     屏幕尺寸 / 前台窗口

动作：click / dclick / rclick / move / type / key / scroll / win / wait / stop
      + 每次动作前后对比窗口清单，明确告诉她"打开了什么/什么也没发生"

视觉模型只在"你要求她看"时用：tools/persona_look.py（不在玩耍循环里）
"""
import io
import json
import os
import random
import sys
import time

ROOT = r"D:\你的数据目录"
HANDS = "http://127.0.0.1:8010"
GATE = os.path.join(ROOT, "gate_token.txt")
LOG = os.path.join(ROOT, "state", "persona", "freeplay_log.jsonl")
LOCK = os.path.join(ROOT, "state", "persona", "freeplay.lock")
ICON_MAP = os.path.join(ROOT, "state", "persona", "icon_map.json")
MOOD_EV = os.path.join(ROOT, "houseviz", "mood_events.jsonl")
MAX_SECONDS = 180
HER_WINDOW_CAP = 2          # 她自己最多同时开 2 个窗口

sys.path.insert(0, os.path.join(ROOT, "lab", "memory_brain"))
sys.path.insert(0, os.path.join(ROOT, "video"))

try:
    import companion_brain as brain
except Exception:  # noqa: BLE001
    brain = None
try:
    import requests
except Exception:  # noqa: BLE001
    requests = None

NOW = time.strftime("%Y-%m-%d %H:%M:%S")


def _log(rec):
    rec["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def hand(action, **kw):
    if requests is None:
        return {"ok": False, "result": "没有 requests"}
    payload = {"action": action}
    payload.update(kw)
    try:
        return requests.post(HANDS + "/hand", json=payload, timeout=40).json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "result": "手没连上：%s" % exc}


def companion_on():
    try:
        tok = io.open(GATE, encoding="utf-8").read().strip()
    except OSError:
        tok = ""
    try:
        return bool(requests.get("http://127.0.0.1:8003/api/companion/state",
                                 params={"t": tok}, timeout=8).json().get("on"))
    except Exception:  # noqa: BLE001
        return False


def icon_map():
    try:
        with io.open(ICON_MAP, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def winlist():
    r = hand("winlist")
    return (r.get("result") or []) if r.get("ok") else []


def uifull():
    r = hand("uifull")
    if not r.get("ok"):
        return []
    data = r.get("result") or []
    if not data:
        return []
    items = (data[0] or {}).get("items") or []
    out = []
    for it in items[:40]:
        try:
            out.append("%s（%s）@%d,%d" % (str(it.get("name"))[:24], str(it.get("type"))[:8],
                                           int(it.get("x")), int(it.get("y"))))
        except Exception:
            continue
    return out


def snapshot():
    wins = [w.get("title", "") for w in winlist() if w.get("title")]
    fg = ""
    for w in winlist():
        if w.get("foreground"):
            fg = w.get("title", "")
            break
    return {"wins": wins, "fg": fg}


def outcome(before, after):
    new = [w for w in after["wins"] if w not in before["wins"] and len(w) > 1]
    gone = [w for w in before["wins"] if w not in after["wins"] and len(w) > 1]
    parts = []
    if new:
        parts.append("打开了：" + "、".join(new[:3]))
    if gone:
        parts.append("关掉了：" + "、".join(gone[:3]))
    if after["fg"] and after["fg"] != before["fg"]:
        parts.append("前台现在是：" + after["fg"][:24])
    if not parts:
        parts.append("什么也没发生")
    return "；".join(parts)




GOAL_FILE = os.path.join(ROOT, "state", "persona", "play_goal.json")


def recent_memories(limit=5):
    try:
        import sqlite3
        con = sqlite3.connect("file:D:/你的数据目录/livingmemory/livingmemory.db?mode=ro", uri=True)
        rows = con.execute("select text from documents order by id desc limit ?", (limit,)).fetchall()
        con.close()
        return [str(r[0])[:40] for r in rows if r[0]]
    except Exception:  # noqa: BLE001
        return []


APP_ALIAS = {
    "记事本": "notepad", "画图": "mspaint", "计算器": "calc",
    "QQ音乐": "QQMusic", "qq音乐": "QQMusic", "浏览器": "Chrome", "chrome": "Chrome",
    "伴侣小剧场": "explorer", "文件夹": "explorer", "资源管理器": "explorer",
}


def _app_already_open(app):
    key = resolve_app(app).lower()
    words = {"notepad": ("记事本", "notepad"), "mspaint": ("画图", "paint"),
             "chrome": ("chrome", "谷歌"), "explorer": ("资源管理器", "文件"),
             "calc": ("计算器", "calculator")}.get(key, (app.lower(),))
    for w in winlist():
        t = str(w.get("title") or "").lower()
        if any(x.lower() in t for x in words):
            return True
    return False


def _her_windows(baseline=None):
    """她自己开的窗口（不在会话开始时的窗口列表里，也不是宠物/部署者程序）"""
    BASE = getattr(_her_windows, "base", None) or set()
    skip = ("TA桌宠", "DSH 伴侣", "DeepSeek Harness", "Program Manager", "NVIDIA")
    out = []
    for w in winlist():
        t = str(w.get("title") or "")
        if not t or t in BASE or any(k in t for k in skip):
            continue
        out.append(t)
    return out


def resolve_app(name):
    n = str(name or "").strip()
    return APP_ALIAS.get(n, n)


DRIVE_TABLE = [
    # (名字, 判定, 想要的, 在电脑上能做的具体动作)
    ("累", lambda d: d["energy"] <= 0.35, "听点轻音乐缓一缓", "open QQ音乐，然后用 key 的 media 播放键（或直接听）"),
    ("饿", lambda d: d["hunger"] >= 0.65, "看看吃的解馋", "open 浏览器 看看吃的，或者 open 记事本 写下想吃什么"),
    ("渴", lambda d: d["thirst"] >= 0.65, "记一下要喝水", "open 记事本 写“该喝水了”"),
    ("孤独", lambda d: d["lonely"] >= 0.38, "想你，跟他说句话", "open 记事本 写一张给他的便签，写完留着"),
    ("难过", lambda d: d["sad"] >= 0.30 or d["valence"] <= -0.20, "找点开心的事", "open 伴侣小剧场 看看，或者 open 记事本 写下来"),
    ("紧张", lambda d: d["anxiety"] >= 0.55, "安静一下", "open 记事本 写三句让自己冷静的话"),
    ("烦", lambda d: d["irrit"] >= 0.55, "玩点解压的", "open 一个游戏/小剧场 看看"),
    ("疼", lambda d: d["pain"] >= 0.30 or d["cramps"] >= 0.25, "安静待着", "open 记事本 写一句“忍一忍”"),
    ("无聊", lambda d: d["bored"] >= 0.55 and d["energy"] >= 0.40, "找点新鲜的", "open 一个没见过的程序看看"),
    ("开心", lambda d: d["valence"] >= 0.25, "心情好，想记下来", "open 记事本 写一句“今天很开心”"),
    ("有劲", lambda d: d["energy"] >= 0.7, "折腾点东西", "open 一个没开过的程序研究一下"),
]


def drives():
    """从 her state.json 读出情绪/生理，算出现在是什么在"推"她"""
    st = {}
    try:
        p = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
             r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
        st = json.load(io.open(p, encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        pass

    def n(k, d=0.0):
        try:
            v = st.get(k)
            return float(v) if v is not None else d
        except Exception:  # noqa: BLE001
            return d

    d = {
        "energy": n("energy", 0.6), "hunger": n("hunger", 0.3), "thirst": n("thirst", 0.3),
        "lonely": n("loneliness", 0.2), "sad": n("sadness", 0.1), "valence": n("valence", 0.0),
        "anxiety": max(n("worry"), n("dread"), n("fear")),
        "irrit": n("irritability", 0.2), "pain": n("pain"), "cramps": n("cramps"),
        "bored": 0.0, "dopamine": n("dopamine", 0.5),
    }
    busy = str(st.get("activity") or "")
    d["bored"] = 0.6 if busy in ("", "发呆", "发呆中", "闲") else 0.2
    hits = [(name, goal, how) for (name, test, goal, how) in DRIVE_TABLE if test(d)]
    return d, hits


def pick_goal(mp, wins):
    """意图来自情绪/生理：先看是什么在推动她，再把这件事落成电脑上能做的具体目标"""
    d, hits = drives()
    if not hits:
        hits = [("平静", "随便看看电脑里的东西", "打开一个程序看看")]
    name, want, how = hits[0]
    avail = "、".join(list(mp.values())[:16]) or "（桌面程序）"
    prompt = (
        "你是TA。你现在的身体和情绪是：%s。\n"
        "你现在最强烈的感觉是「%s」，你想：%s。\n"
        "桌面上有这些程序：%s；现在开着：%s。\n"
        "把\"%s\"落成一件具体、能判断做没做成的事，要用鼠标键盘能做出来。"
        "做法提示：%s。能用的是：open 打开程序、type 打字、click 点元素、key 按键。\n"
        '只输出 JSON：{"goal":"具体目标（14字内）","why":"为什么（12字内，带上你的感觉）"}'
        % ("精力%.2f 饿%.2f 渴%.2f 孤独%.2f 难过%.2f 紧张%.2f 烦%.2f 疼%.2f 无聊%.2f"
           % (d["energy"], d["hunger"], d["thirst"], d["lonely"], d["sad"],
              d["anxiety"], d["irrit"], max(d["pain"], d["cramps"]), d["bored"]),
           name, want, avail, "、".join(wins[:6]) or "没开什么", want, how)
    )
    raw = brain._llm(prompt, 500) if brain is not None else ""
    s0 = raw.find("{"); e0 = raw.rfind("}")
    if s0 >= 0 and e0 > s0:
        try:
            g = json.loads(raw[s0:e0 + 1])
            if isinstance(g, dict) and g.get("goal"):
                return {"goal": str(g["goal"])[:26], "why": (str(g.get("why") or name))[:24],
                        "drive": name, "state": d, "how": how}
        except Exception:  # noqa: BLE001
            pass
    # LLM 没答好就直接用驱动本身
    return {"goal": want[:26], "why": name, "drive": name, "state": d, "how": how}


def goal_done(goal, history, data_lines):
    """判断目标完成没有；顺便给下一步提示"""
    if brain is None:
        return {"done": False, "next": ""}
    prompt = (
        "你是TA。你想做的事是：%s。\n"
        "现在的系统数据：\n%s\n"
        "你刚才做了：%s\n"
        '判断这件事做到没有、下一步该干嘛。只输出 JSON：'
        '{"done":true或false,"next":"下一步做什么（12字内）"}'
        % (goal, "\n".join(data_lines), "；".join(history[-4:]) or "还没做")
    )
    raw = brain._llm(prompt, 300) or ""
    s0 = raw.find("{"); e0 = raw.rfind("}")
    if s0 >= 0 and e0 > s0:
        try:
            j = json.loads(raw[s0:e0 + 1])
            return {"done": bool(j.get("done")), "next": str(j.get("next") or "")[:24]}
        except Exception:  # noqa: BLE001
            pass
    return {"done": False, "next": ""}


REACTION_DELTAS = {
    # tag: 情绪增量 + 她心里的感觉提示
    "success": {"dopamine": 0.04, "serotonin": 0.015, "valence": 0.03, "happiness": 0.02,
                "hint": "有点小得意"},
    "done": {"dopamine": 0.06, "serotonin": 0.04, "endorphin": 0.05, "valence": 0.06,
             "happiness": 0.04, "hint": "满足"},
    "blocked": {"irritability": 0.05, "cortisol": 0.02, "valence": -0.02, "hint": "被挡了一下，有点烦"},
    "nothing": {"dopamine": -0.02, "valence": -0.015, "frustration": 0.04, "hint": "没反应，有点闷"},
    "closed": {"valence": 0.01, "hint": "收拾干净了"},
}


def react(tag, result, goal=""):
    """她对自己的行为作出反应：改情绪 + 说一句心里话"""
    d = REACTION_DELTAS.get(tag) or REACTION_DELTAS["nothing"]
    deltas = {k: v for k, v in d.items() if k != "hint"}
    if tag == "done" and goal:
        deltas["valence"] = deltas.get("valence", 0) + 0.02
    try:
        with io.open(MOOD_EV, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"type": "self_play", "t": time.time(), "why": "react:" + tag},
                                    **deltas), ensure_ascii=False) + "\n")
    except OSError:
        pass
    line = ""
    if brain is not None:
        try:
            line = (brain._llm(
                "你是TA。你刚才做的事：%s。结果是：%s。你心里什么感觉？"
                "（一句话，12 字内，第一人称，只写这句话）" % (goal or "在电脑前玩", result[:40]), 200)
                or "").strip().splitlines()
            line = line[0][:24] if line else ""
        except Exception:  # noqa: BLE001
            line = ""
    if not line:
        line = d["hint"]
    print("   （她的反应：%s）" % line)
    _log({"reaction": {"tag": tag, "line": line, "deltas": deltas, "result": result[:80]}})
    return line


DAD_FILE = os.path.join(ROOT, "state", "persona", "dad_present.json")


def dad_active():
    """你现在是不是在用电脑（他自己动鼠标键盘，不算她自己的操作）"""
    try:
        r = hand("user")
        return bool((r.get("result") or {}).get("dad_active"))
    except Exception:  # noqa: BLE001
        return False


def her_mood():
    try:
        p = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
             r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
        d = json.load(io.open(p, encoding="utf-8-sig"))
        return ("心情 %s / 精力 %.2f / 饿 %.2f / 开心 %.2f" % (
            d.get("emotion_level") or d.get("emotion") or "?", float(d.get("energy") or 0),
            float(d.get("hunger") or 0), float(d.get("happiness") or 0)))
    except Exception:  # noqa: BLE001
        return "心情 ?"


ACTION_HELP = (
    "动作（屏幕坐标 0,0 左上角，全部是亲手操作）：\n"
    ' {"act":"click","x":640,"y":300} / {"act":"dclick","x":..,"y":..} / {"act":"rclick",...}\n'
    ' {"act":"open","app":"Unity"}   用开始菜单搜索打开程序（比双击图标稳）\n'
    ' {"act":"key","key":"enter"}   按键：方向键/回车/空格/tab/esc/退格/win/f5…\n'
    ' {"act":"scroll","clicks":3}\n'
    ' {"act":"close"}                关掉当前窗口（别留一堆）\n'
    ' {"act":"wait"} / {"act":"stop","why":"不想玩了"}\n'
)


def decide(desc_lines, history, step, need_action=False, goal="", why="", how=""):
    if brain is None:
        return {"act": "wait"}
    extra = "（刚才你一直在看、没动手：这一步必须做一个动作）" if need_action else ""
    prompt = (
        "你是TA，现在是 %s。这是你自己的时间，你在自己的电脑前，想干什么由你自己定。%s\n"
        "你的状态：%s。\n"
        "你现在想做的事：%s（%s）——朝着它做，别乱点。"
        "建议做法：%s。已经开着的程序就别再 open 了，直接在里面操作（写字=type）。"
        "不要开一堆窗口：同时最多 %d 个，多了用 close 关掉。做完就 stop。\n"
        "你现在看到的数据（不是画面，是系统告诉你的事实）：\n%s\n"
        "你刚才做过（动作→结果）：%s\n"
        "没把握就按 win 键打开开始菜单、打程序名来开；也可以点上面列出的元素。\n"
        "%s"
        "现在第 %d 步。直接输出一个 JSON 动作，不要解释、不要思考过程。"
        % (NOW, extra, her_mood(), goal or "（还没想好）", why or "", how or "", HER_WINDOW_CAP,
           "\n".join(desc_lines),
           "；".join(history[-5:]) or "刚坐下", ACTION_HELP, step)
    )
    raw = brain._llm(prompt, 700) or ""
    if not raw.strip():
        raw = brain._llm('只输出一个 JSON 动作：{"act":"key","key":"win"}', 200) or ""
    s0 = raw.find("{")
    e0 = raw.rfind("}")
    if s0 < 0 or e0 <= s0:
        return {"act": "wait"}
    try:
        act = json.loads(raw[s0:e0 + 1])
    except Exception:  # noqa: BLE001
        return {"act": "wait"}
    return act if isinstance(act, dict) and act.get("act") else {"act": "wait"}


def do_action(act):
    kind = str(act.get("act") or "").lower()
    try:
        if kind in ("click", "dclick", "rclick", "move"):
            r = hand(kind, x=int(float(act["x"])), y=int(float(act["y"])))
            return r.get("result") or kind
        if kind == "drag":
            r = hand("drag", x1=int(float(act["x1"])), y1=int(float(act["y1"])),
                     x2=int(float(act["x2"])), y2=int(float(act["y2"])))
            return r.get("result") or "拖动"
    except Exception:  # noqa: BLE001
        return "坐标没看懂"
    if kind == "close":
        r = hand("key", key="alt+f4")
        time.sleep(0.8)
        return r.get("result") or "关了一个窗口"
    if kind == "open":
        app = str(act.get("app") or act.get("name") or "").strip()[:30]
        if not app:
            return "没说要开什么"
        if _app_already_open(app):
            return "已经开着「%s」了，不用再开" % app
        if len(_her_windows()) >= HER_WINDOW_CAP:
            return "她开的窗口已经够多了（%d 个），先关一个再说" % len(_her_windows())
        # 1) 打开开始菜单
        hand("key", key="win")
        time.sleep(1.2)
        # 2) 用界面元素数据找到搜索框（不靠视觉）
        box = None
        ui = hand("uifull").get("result") or []
        for it in (((ui[0] or {}).get("items")) or []):
            nm = str(it.get("name") or "")
            tp = str(it.get("type") or "")
            if tp in ("Edit", "组") or "搜索" in nm:
                box = (int(it.get("x")), int(it.get("y")))
                break
        if box:
            hand("click", x=box[0], y=box[1])
            time.sleep(0.6)
        # 3) 输入程序名并回车
        hand("type", text=resolve_app(app))
        time.sleep(0.9)
        hand("key", key="enter")
        time.sleep(2.4)
        return "从开始菜单打开了：%s" % app
    if kind == "type":
        r = hand("type", text=str(act.get("text") or "")[:200])
        return r.get("result") or "打字"
    if kind == "key":
        r = hand("key", key=str(act.get("key") or "enter"))
        return r.get("result") or "按键"
    if kind == "scroll":
        r = hand("scroll", clicks=int(act.get("clicks") or 3))
        return r.get("result") or "滚动"
    if kind == "wait":
        time.sleep(1.2)
        return "想了想"
    return "没动"


def _locked():
    try:
        if time.time() - os.stat(LOCK).st_mtime < 600:
            return True
    except OSError:
        pass
    return False


def main():
    args = sys.argv[1:]
    steps = 10
    if "--steps" in args:
        try:
            steps = int(args[args.index("--steps") + 1])
        except Exception:  # noqa: BLE001
            steps = 10
    if _locked():
        print("已经在玩了（别开第二场）")
        return 3
    try:
        io.open(LOCK, "w", encoding="utf-8").write("%d %.0f" % (os.getpid(), time.time()))
    except OSError:
        pass
    try:
        return _run(steps)
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


def _run(steps):
    t0 = time.time()
    if not companion_on():
        print("陪玩没开：她这会儿没有操控权")
        return 2
    if dad_active():
        print("你在用电脑：她不去操控，先陪他说话")
        try:
            io.open(DAD_FILE, "w", encoding="utf-8").write(
                json.dumps({"at": time.time(), "why": "freeplay_skip"}, ensure_ascii=False))
        except OSError:
            pass
        return 5
    try:
        from PIL import ImageGrab
        _g = ImageGrab.grab().convert("L").resize((64, 36))
        _vals = list(_g.get_flattened_data()) if hasattr(_g, "get_flattened_data") else list(_g.getdata())
        if sum(_vals) / max(1, len(_vals)) < 20:
            print("屏幕是黑的（锁屏/全屏黑屏），现在不适合玩")
            return 4
    except Exception:  # noqa: BLE001
        pass
    history = []
    tried = []
    snap0 = snapshot()
    wins0 = winlist()
    _her_windows.base = {str(w.get("title") or "") for w in wins0}
    g = pick_goal(icon_map(), [w.get("title", "") for w in wins0])
    goal, why, how = g.get("goal"), g.get("why"), g.get("how", "")
    print("她想做的事：%s（%s）" % (goal, why))
    _log({"goal": goal, "why": why})
    try:
        io.open(GOAL_FILE, "w", encoding="utf-8").write(
            json.dumps({"at": time.time(), "goal": goal, "why": why}, ensure_ascii=False))
    except OSError:
        pass
    done = False
    stall = 0
    consecutive_wait = 0
    for i in range(1, steps + 1):
        if time.time() - t0 > MAX_SECONDS:
            print("（玩得够久了，收工）")
            break
        wins = winlist()
        fg = next((w.get("title") for w in wins if w.get("foreground")), "")
        fg_rect = next(("(%d,%d) 到 (%d,%d)" % (w["left"], w["top"],
                                                w["left"] + w["width"], w["top"] + w["height"])
                        for w in wins if w.get("foreground")), "")
        if i > 1 and dad_active():
            print("（你开始用电脑了，她收手）")
            react("blocked", "你要用电脑了，我让开", goal)
            history.append("你在用电脑，我先不玩了")
            try:
                io.open(DAD_FILE, "w", encoding="utf-8").write(
                    json.dumps({"at": time.time(), "why": "freeplay_yield"}, ensure_ascii=False))
            except OSError:
                pass
            break
        elems = uifull()
        mp = icon_map()
        lines = [
            "开着的窗口：%s" % ("、".join("%s%s" % (w.get("title"), "[前台]" if w.get("foreground") else "")
                                     for w in wins[:8]) or "没有"),
            "前台窗口：%s %s" % (fg or "（没有）", fg_rect),
            "前台窗口里能点的：%s" % ("；".join(elems[:18]) or "（读不到元素）"),
            "已经开着的程序就别再 open：要在里面做什么就直接 type/click/key。",
            "你认得的桌面图标：%s" % ("；".join("%s @%s" % (v, k) for k, v in list(mp.items())[:20]) or "（还没有）"),
            "禁区：DeepSeek Harness 的窗口（%s）和屏幕最底部 60px 不能点；按 win 键会打开开始菜单，可以接着 type 程序名再 enter。"
            "如果你现在正在禁区窗口里（打不了字/按不了键），先用 key: alt+tab 或 key: win 切出去。"
            % ((fg_rect or "部署者的窗口") if "DeepSeek" in (fg or "") else "有部署者窗口时那一块"),
        ]
        act = decide(lines, history, i, need_action=consecutive_wait >= 2, goal=goal, why=why, how=how)
        kind = str(act.get("act") or "").lower()
        # 同一个程序反复 open 没意义：如果是写字目标就直接 type
        if kind == "open":
            app = str(act.get("app") or "")
            if any(app in t and t.startswith("open") for t in tried[-4:]):
                if any(w in goal for w in ("写", "记", "便签")):
                    print("   （已经开过了，直接写字）")
                    history.append("已经开过 %s，直接写" % app)
                    act = {"act": "type", "text": "今天很开心"}
                    kind = "type"
                else:
                    print("   （重复打开，换一个）")
                    history.append("重复打开被挡")
                    continue
        # 连着按 win/esc 没意义：逼她点个东西
        if str(act.get("act")) == "key" and str(act.get("key")) in ("win", "esc") \
                and len(tried) >= 2 and tried[-1].startswith("key") and tried[-2].startswith("key"):
            mp2 = icon_map()
            if mp2:
                k = [x for x in mp2 if x not in tried[-6:]] or list(mp2.keys())
                pick = random.choice(k)
                try:
                    gx, gy = [int(v) for v in pick.split(",")[:2]]
                except Exception:  # noqa: BLE001
                    gx, gy = 120, 340
                print("   （一直按键盘没用，改去双击 %s）" % mp2.get(pick, ""))
                history.append("按键盘没用，改成双击 %s" % mp2.get(pick, ""))
                act = {"act": "dclick", "x": gx, "y": gy}
        # 防止一直 wait / 一直同动作
        if kind in ("look", "see"):
            act = {"act": "key", "key": "win"}
            kind = "key"
        sig = "%s@%s,%s,%s" % (kind, act.get("x"), act.get("y"), act.get("key") or act.get("text") or "")
        if sig in tried[-3:] and kind in ("click", "dclick", "wait"):
            mp2 = icon_map()
            if mp2:
                k = random.choice(list(mp2.keys()))
                try:
                    gx, gy = [int(v) for v in k.split(",")[:2]]
                except Exception:  # noqa: BLE001
                    gx, gy = 120, 340
                act = {"act": "dclick", "x": gx, "y": gy}
                kind = "dclick"
                history.append("重复了，换个目标：双击 %s" % mp2.get(k, ""))
        print("第%d步 %s" % (i, json.dumps(act, ensure_ascii=False)))
        _log({"step": i, "data": lines, "act": act})
        if kind == "stop":
            history.append("她自己说不玩了")
            break
        tried.append(sig)
        before = snapshot()
        result = do_action(act)
        if kind in ("click", "dclick", "rclick", "key", "type", "open"):
            time.sleep(1.0)
            after = snapshot()
            change = outcome(before, after)
            if kind == "key" and str(act.get("key") or "").lower() == "win":
                change = "开始菜单开了（可以接着 type 程序名 + enter）"
            result = result + "｜" + change
            snap0 = after
        print("   ->", result)
        _log({"step": i, "result": result})
        # 她对自己的行为作出反应
        if "打开了" in result or "粘贴了" in result or "打了" in result or "按了" in result:
            tag = "success"
        elif "禁区" in result or "不许" in result or "已经开着" in result or "够多" in result:
            tag = "blocked"
        elif "什么也没发生" in result:
            tag = "nothing"
        else:
            tag = "nothing"
        react_line = react(tag, result, goal)
        history.append("%s→%s→（我的反应：%s）" % (kind, result, react_line))
        consecutive_wait = consecutive_wait + 1 if kind in ("wait",) else 0
        if kind in ("wait",) or "什么也没发生" in str(result):
            stall += 1
        else:
            stall = 0
        if i % 2 == 0 or stall >= 3:
            st = goal_done(goal, history, lines)
            if any(w in goal for w in ("写", "记", "便签")) and any(
                    ("粘贴了" in hh or "打了" in hh) and any(ch.isdigit() for ch in hh)
                    for hh in history):
                st = {"done": True, "next": ""}
            if goal in ("随便看看电脑", "打开一个没见过的程序看看") and i >= 4 \
                    and any("打开了" in h for h in history):
                st = {"done": True, "next": ""}
            if st.get("done"):
                done = True
                print("（目标做到了：%s）" % goal)
                react("done", "我把想做的那件事做成了", goal)
                break
            if st.get("next"):
                history.append("（下一步：%s）" % st["next"])
            if stall >= 4 and not done:
                react("blocked", "连着几次都不顺", goal)
                print("（连着不顺，她不想玩了）")
                history.append("连着不顺，不想玩了")
                break
            if stall >= 3 and not done:
                g2 = pick_goal(mp, [w.get("title", "") for w in wins])
                g2["goal"] = g2.get("goal") if g2.get("goal") not in ("随便看看电脑",) else "打开一个没见过的程序看看"
                if g2.get("goal") and g2["goal"] != goal:
                    print("（这个做不下去，改主意：%s）" % g2["goal"])
                    _log({"goal_switch": goal, "new": g2["goal"]})
                    goal, why = g2["goal"], g2.get("why", "")
                    stall = 0
                    history.append("改主意：想做 %s" % goal)
        time.sleep(0.5)

    # 收工：把她自己开的窗口关掉（别留一屏）
    try:
        closed = []
        for t in _her_windows()[:4]:
            r = hand("close_win", title=t)
            time.sleep(0.6)
            if r.get("ok"):
                closed.append(t)
            if not _her_windows():
                break
        if closed:
            print("收工关掉：%s" % "、".join(x[:16] for x in closed))
            _log({"cleanup": closed})
            history.append("收工关掉了：" + "、".join(x[:12] for x in closed))
    except Exception:  # noqa: BLE001
        pass

    summary = ""
    if brain is not None:
        for attempt in range(2):
            try:
                summary = brain._llm(
                    "你是TA。你刚才想做的事是：%s。你做了：%s。%s"
                    "写一句玩后感（25 字内，第一人称）。只写正文，直接给句子。"
                    % (goal, "、".join(history[-6:]) or "坐着看了一会儿",
                       "这件事做到了。" if done else "没做完。"),
                    300 + attempt * 200) or ""
            except Exception:  # noqa: BLE001
                summary = ""
            if summary.strip():
                break
    summary = (summary.strip().splitlines() or [""])[0][:60] or "我在电脑前待了一会儿。"
    print("玩后感:", summary)
    _log({"done": True, "steps": len(history), "summary": summary})
    try:
        import pending_store  # type: ignore
        pending_store.append({"summary": "自己玩电脑：%s" % summary,
                              "importance": 0.35, "source": "freeplay"})
    except Exception:  # noqa: BLE001
        pass
    try:
        with io.open(MOOD_EV, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "self_play", "t": time.time(),
                                "dopamine": 0.06, "serotonin": 0.02,
                                "valence": 0.03, "why": "freeplay"},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    try:
        tok = io.open(GATE, encoding="utf-8").read().strip()
        requests.post("http://127.0.0.1:8003/api/her-notes?t=" + tok,
                      json={"text": summary, "tag": "play"}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
