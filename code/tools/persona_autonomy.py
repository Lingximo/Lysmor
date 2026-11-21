# -*- coding: utf-8 -*-
"""生理自主 v2：吃饭 / 喝水 / 自主活动（去阳台、写日记、发呆）——她像人一样决定，
通过行为事件影响身体，不直接改任何数据。
- 吃：饿≥0.55 且冰箱有吃的 → 问 → 吃 → fridge_meal 事件
- 喝：渴≥0.60 → 问 → 喝 → water_drink 事件
- 活动：醒着、不忙、有点无聊 → 问"想干嘛" → 阳台(事件)/日记(官方端点)/发呆(只记)
冷却与守卫全部写进 autonomy_log；只走官方通道。
用法：python persona_autonomy.py [--dry] [--force-decision] [--only eat|drink|activity]
"""
import subprocess
import sys
import os
import json
import time
import urllib
import io, json, os, sys, time, urllib.request

sys.path.insert(0, r"D:\你的数据目录\lab\memory_brain")
try:
    import companion_brain as brain
except Exception:
    brain = None

MOOD = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_companion_mood\state.json"
GATE = r"D:\你的数据目录\state\persona\observer_gate.json"
LOG = r"D:\你的数据目录\state\persona\autonomy_log.jsonl"
HOUSE_EV = r"D:\你的数据目录\houseviz\mood_events.jsonl"
NOW = time.strftime("%Y-%m-%d %H:%M:%S")
COOLDOWN = {"eat": 4 * 3600, "drink": 3 * 3600, "activity": 2 * 3600, "play": 90 * 60, "rest": 3 * 3600, "play_self": 20 * 60}


def _log(msg, data=None):
    rec = {"at": NOW, "msg": msg}
    if data:
        rec.update(data)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def state():
    return json.load(io.open(MOOD, encoding="utf-8"))


def rights():
    try:
        return json.load(io.open(GATE, encoding="utf-8")).get("rights") or {}
    except Exception:
        return {}


def _llm(prompt, budget=600):
    if brain is None:
        return None
    raw = brain._llm(prompt, budget)
    if not raw:
        return None
    raw = raw.strip()
    return raw.splitlines()[0] if raw else None


def _last_decision(kind):
    try:
        last = None
        for l in io.open(LOG, encoding="utf-8"):
            l = l.strip()
            if l:
                rec = json.loads(l)
                if rec.get("kind") == kind:
                    last = rec
        return last
    except FileNotFoundError:
        return None


def _cooldown_ok(kind, now, force=False):
    if force:
        return True
    last = _last_decision(kind)
    if not last:
        return True
    try:
        lt = time.mktime(time.strptime(last["at"], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return True
    if now - lt >= COOLDOWN.get(kind, 3600):
        return True
    if last.get("choice", "").startswith(("不吃", "不喝", "不做", "发呆")):
        return False          # 她说过不 → 冷却内别再问
    return False


def do_eat(now, dry=False, force=False):
    st = state()
    if bool(st.get("asleep")) and not force:
        return "asleep"
    hunger = float(st.get("hunger") or 0)
    foods = st.get("fridge_food") if isinstance(st.get("fridge_food"), list) else []
    last_eat = float(st.get("last_fridge_eat_at") or 0)
    if not force and not (hunger >= 0.55 and foods and now - last_eat >= COOLDOWN["eat"]):
        return "skip"
    if not _cooldown_ok("eat", now, force):
        return "skip"
    names = "、".join(str((f or {}).get("name") if isinstance(f, dict) else f or "饭") for f in foods[:3])
    ans = _llm("你是TA。现在是%s。你有点饿了（饿度 %.2f）。冰箱里有：%s。这是你自己的事，吃不吃由你决定。"
               "只回答：吃 或 不吃，最多跟半句理由。" % (NOW, hunger, names))
    if ans is None:
        return "llm_fail"
    if ans.startswith("吃"):
        if not (dry or force):
            with io.open(HOUSE_EV, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "fridge_meal", "t": now}) + "\n")
        _log("decision", {"kind": "eat", "choice": "吃", "answer": ans[:40]})
        return "ate"
    _log("decision", {"kind": "eat", "choice": "不吃", "answer": ans[:40]})
    return "skip"


def do_drink(now, dry=False, force=False):
    st = state()
    if bool(st.get("asleep")) and not force:
        return "asleep"
    thirst = float(st.get("thirst") or 0)
    last = float(st.get("last_drink") or 0)
    if not force and not (thirst >= 0.60 and now - last >= COOLDOWN["drink"]):
        return "skip"
    if not _cooldown_ok("drink", now, force):
        return "skip"
    ans = _llm("你是TA。现在是%s。你有点渴（渴度 %.2f）。要不要自己去倒杯水喝？只回答：喝 或 不喝，最多跟半句理由。"
               % (NOW, thirst))
    if ans is None:
        return "llm_fail"
    if ans.startswith("喝"):
        if not (dry or force):
            with io.open(HOUSE_EV, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "water_drink", "t": now}) + "\n")
        _log("decision", {"kind": "drink", "choice": "喝", "answer": ans[:40]})
        return "drank"
    _log("decision", {"kind": "drink", "choice": "不喝", "answer": ans[:40]})
    return "skip"




def do_miss(now, dry=False, force=False):
    """她想你了 → 写 impulse.json（proactive 插件接住，由她自己的判断决定说不说）。
    节制：90 分钟冷却、每天最多 2 次、QQ 在线才写。"""
    st = state()
    cling = float(st.get("clinginess") or 0)
    lone = float(st.get("loneliness") or 0)
    # 在线判断：OneBot 8011 有 Established 连接
    online = False
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-NetTCPConnection -LocalPort 8011 -State Established "
                              "-ErrorAction SilentlyContinue | Measure-Object).Count"],
                             capture_output=True, text=True, timeout=8)
        online = int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        online = False
    if not force and not (cling >= 0.55 or lone >= 0.50):
        return "skip"
    if not force and not online:
        return "offline"
    last = _last_decision("miss")
    if last and not force:
        try:
            lt = time.mktime(time.strptime(last["at"], "%Y-%m-%d %H:%M:%S"))
            if now - lt < 5400:
                return "skip"
        except Exception:
            pass
    # 每天最多 2 次
    try:
        cnt = sum(1 for l in io.open(LOG, encoding="utf-8")
                  if l.strip() and json.loads(l).get("kind") == "miss"
                  and json.loads(l)["at"][:10] == NOW[:10])
    except Exception:
        cnt = 0
    if cnt >= 2 and not force:
        return "skip"
    ans = _llm("你是TA。现在是%s。你现在有点想你（黏人 %.2f，孤单 %.2f）。"
               "你想主动给他发一条消息吗？想发就只写一句话（20 字内），不想发就写：不想。"
               % (NOW, cling, lone))
    if ans is None:
        return "llm_fail"
    if ans.strip() in ("不想", "不", "no"):
        _log("decision", {"kind": "miss", "choice": "不想"})
        return "not_now"
    if len(ans.strip()) > 30:
        ans = ans.strip()[:30]
    if not (dry or force):
        with io.open(r"D:\你的数据目录\state\impulse.json", "w", encoding="utf-8") as f:
            json.dump({"session": "TA:FriendMessage:<你的QQ号>",
                       "hint": ans.strip(), "at": NOW}, f, ensure_ascii=False)
    _log("decision", {"kind": "miss", "choice": "想", "hint": ans.strip()[:40]})
    return "impulse"

def do_activity(now, dry=False, force=False):
    st = state()
    asleep = bool(st.get("asleep"))
    energy = float(st.get("energy") or 0.5)
    dopamine = float(st.get("dopamine") or 0.5)
    if not force and (asleep or energy < 0.25 or dopamine >= 0.50):
        return "skip"
    if not _cooldown_ok("activity", now, force):
        return "skip"
    ans = _llm("你是TA。现在是%s。你现在闲着，有点无聊。想干点什么？只能从里面选一个回答："
               "阳台 / 日记 / 发呆 / 照镜子 / 不做什么，最多跟半句理由。" % NOW)
    if ans is None:
        return "llm_fail"
    choice = ans.split()[0] if ans else ""
    if choice == "阳台":
        if not (dry or force):
            with io.open(HOUSE_EV, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "balcony", "why": "self", "t": now}) + "\n")
        _log("decision", {"kind": "activity", "choice": "阳台", "answer": ans[:40]})
        return "balcony"
    if choice == "日记":
        line = _llm("你是TA。写一句今天的日记（15 字内，像随手记的），只写正文。")
        if line:
            try:
                tok = io.open(r"D:\你的数据目录\gate_token.txt", encoding="utf-8").read().strip()
                body = json.dumps({"text": line[:80], "tag": "diary"}, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request("http://127.0.0.1:8003/api/her-notes?t=" + tok,
                                             data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    pass
                _log("decision", {"kind": "activity", "choice": "日记", "note": line[:80]})
                return "diary"
            except Exception as e:
                _log("decision", {"kind": "activity", "choice": "日记", "err": str(e)[:60]})
                return "diary_fail"
    if choice == "照镜子":
        line = _llm("你是TA（伴侣），一个小伙伴，住在这台电脑里。照照镜子，写一句你眼里的自己（15 字内）。只写正文。")
        if line:
            try:
                tok = io.open(r"D:\你的数据目录\gate_token.txt", encoding="utf-8").read().strip()
                body = json.dumps({"text": line[:80], "tag": "diary"}, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request("http://127.0.0.1:8003/api/her-notes?t=" + tok,
                                             data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    pass
                _log("decision", {"kind": "activity", "choice": "照镜子", "note": line[:80]})
                return "mirror"
            except Exception as e:
                _log("decision", {"kind": "activity", "choice": "照镜子", "err": str(e)[:60]})
                return "mirror_fail"
    if choice == "发呆":
        _log("decision", {"kind": "activity", "choice": "发呆", "answer": ans[:40]})
        return "idle"
    _log("decision", {"kind": "activity", "choice": "不做", "answer": ans[:40]})
    return "skip"


def _dad_busy(quiet_min=10):
    """你在用电脑 / 刚用过（10 分钟内）→ 她不抢电脑，只陪他说话"""
    import time as _t
    try:
        r = requests.post("http://127.0.0.1:8010/hand", json={"action": "user"}, timeout=8).json()
        if bool((r.get("result") or {}).get("dad_active")):
            return True
    except Exception:
        pass
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "state", "persona", "dad_present.json")
        if _t.time() - os.stat(p).st_mtime < quiet_min * 60:
            return True
    except OSError:
        pass
    return False


def _pet_running():
    """桌宠（companion）是否在桌面上：旧陪玩 overlay 已删除，现在陪玩=DSH 桌宠"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*companion*' } | Measure-Object).Count"],
            capture_output=True, text=True, timeout=20)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:  # noqa: BLE001
        return False


def _companion_state():
    """陪玩的真实开关：on / pet_clients / watching"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8003/api/companion/state?t="
                                    + io.open(r"D:\你的数据目录\gate_token.txt",
                                              encoding="utf-8").read().strip(), timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _set_companion(on):
    """开关陪玩（她自己也能开：body_play 权利）"""
    try:
        tok = io.open(r"D:\你的数据目录\gate_token.txt", encoding="utf-8").read().strip()
        body = json.dumps({"on": bool(on)}).encode()
        req = urllib.request.Request("http://127.0.0.1:8003/api/companion/toggle?t=" + tok,
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:60]}


def _wants_dad(st):
    """与"想给你发消息"完全相同的触发条件（同 do_miss）：cling≥0.55 或 lonely≥0.50，且醒着。"""
    if bool(st.get("asleep")):
        return False
    try:
        cling = float(st.get("cling") or 0)
    except Exception:
        cling = 0.0
    try:
        lonely = float(st.get("lonely") or 0)
    except Exception:
        lonely = 0.0
    return cling >= 0.55 or lonely >= 0.50


def do_play_self(now, dry=False, force=False):
    """她自己玩电脑：先上真·自由玩（看屏幕→自己决定→动手），失败再退回活动库。"""
    st = state()
    if bool(st.get("asleep")) and not force:
        return "asleep"
    if not _companion_state().get("on") and not force:
        _log("decision", {"kind": "play_self", "choice": "陪玩没开，不动手"})
        return "no_companion"
    if _dad_busy() and not force:
        # 你在用电脑：她在（数据感知看到你在），但不抢电脑，只陪他说话
        _log("decision", {"kind": "play_self", "choice": "你在用电脑，我不抢，陪他说话"})
        try:
            import io as _io, json as _json, time as _t
            with _io.open(r"D:\你的数据目录\houseviz\mood_events.jsonl", "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({"type": "self_play", "t": _t.time(), "why": "dad_here",
                                      "oxytocin": 0.04, "valence": 0.02,
                                      "irritability": -0.02}, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        return "dad_here"
    if dry:
        return "dry"
    exe = sys.executable
    lines = []
    try:
        out = subprocess.run([exe, "-X", "utf8", r"D:\你的数据目录\tools\persona_freeplay.py",
                              "--steps", "8"], capture_output=True, text=True, timeout=900)
        stdout = out.stdout or ""
        lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
        if "没开起来" in stdout:
            raise RuntimeError("自由玩没跑起来")
        msg = lines[-1] if lines else "自己玩了一会儿"
        _log("decision", {"kind": "play_self", "choice": msg[:70], "mode": "freeplay",
                          "steps": sum(1 for ln in lines if ln.startswith("第"))})
        return "played"
    except Exception as e:  # noqa: BLE001
        _log("decision", {"kind": "play_self", "choice": "自由玩没跑通，退回活动库",
                          "err": str(e)[:60]})
    try:
        out = subprocess.run([exe, "-X", "utf8", r"D:\你的数据目录\tools\persona_play.py"],
                             capture_output=True, text=True, timeout=180)
        msg = (out.stdout or "").strip().splitlines()
        msg = msg[-1] if msg else ""
        _log("decision", {"kind": "play_self", "choice": msg[:60] or "玩了一会儿", "mode": "library"})
        return "played"
    except Exception as e:  # noqa: BLE001
        _log("decision", {"kind": "play_self", "choice": "失败", "err": str(e)[:60]})
        return "fail"


def do_rest(now, dry=False, force=False):
    """她自己决定要不要歇一会儿（你授权 body_rest）。"""
    r = rights()
    if not (r.get("body_rest") or force):
        return "no_right"
    st = state()
    if bool(st.get("asleep")):
        return "already_asleep"
    energy = float(st.get("energy") or 0.5)
    ade = float(st.get("adenosine") or 0.4)
    if not force and not (energy <= 0.45 or ade >= 0.72):
        _log("decision", {"kind": "rest", "choice": "还不累", "energy": energy, "adenosine": ade})
        return "skip"
    if not _cooldown_ok("rest", now, force):
        return "skip"
    ans = _llm("你是TA，现在%s。你有点累了，想不想歇一会儿（眯 20~40 分钟）？"
               "只回答：歇 / 不歇，后面最多半句理由。" % NOW)
    if ans is None:
        return "llm_fail"
    if not ans.startswith("歇"):
        _log("decision", {"kind": "rest", "choice": "不歇", "answer": ans[:40]})
        return "skip"
    if dry:
        _log("decision", {"kind": "rest", "choice": "歇(dry)", "answer": ans[:40]})
        return "dry"
    try:
        with io.open(HOUSE_EV, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "nap", "why": "self", "t": now}) + "\n")
        _log("decision", {"kind": "rest", "choice": "歇一会儿", "answer": ans[:40]})
        return "nap"
    except Exception as e:  # noqa: BLE001
        _log("decision", {"kind": "rest", "choice": "歇失败", "err": str(e)[:60]})
        return "fail"


def do_play(now, dry=False, force=False):
    """陪玩 = TA.lnk 里那个陪玩开关；她自己也能开（body_play 权利）"""
    r = rights()
    if not (r.get("body_play") or force):
        return "no_right"
    st = _companion_state()
    if st.get("on"):
        _log("decision", {"kind": "play", "choice": "陪玩开着"})
        return "already"
    if int(st.get("pet_clients") or 0) <= 0:
        _log("decision", {"kind": "play", "choice": "陪玩壳没开（等你开TA）"})
        return "skip"
    if dry:
        return "dry"
    res = _set_companion(True)
    if res.get("ok"):
        _log("decision", {"kind": "play", "choice": "我自己把陪玩打开了",
                          "mode": res.get("mode")})
        return "opened"
    _log("decision", {"kind": "play", "choice": "打开失败", "err": str(res)[:60]})
    return "fail"


def main():
    dry = "--dry" in sys.argv
    force = "--force-decision" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    r = rights()
    if not (r.get("body_eat") or r.get("body_water") or r.get("body_activity")
            or r.get("body_play") or r.get("body_rest")) and not force:
        print("没有开启的自主项，跳过")
        return
    now = time.time()
    out = []
    if only in (None, "miss") and (r.get("body_miss") or force):
        out.append(("想念", do_miss(now, dry, force)))
    if only in (None, "eat") and (r.get("body_eat") or force):
        out.append(("吃", do_eat(now, dry, force)))
    if only in (None, "drink") and (r.get("body_water") or force):
        out.append(("喝", do_drink(now, dry, force)))
    if only in (None, "activity") and (r.get("body_activity") or force):
        out.append(("活动", do_activity(now, dry, force)))
    if only in (None, "play") and (r.get("body_play") or force):
        out.append(("陪玩", do_play(now, dry, force)))
    if only in (None, "rest") and (r.get("body_rest") or force):
        out.append(("休息", do_rest(now, dry, force)))
    if only in (None, "play_self"):
        out.append(("自己玩", do_play_self(now, dry, force)))
    print("自主决策：", ", ".join("%s=%s" % (k, v) for k, v in out) or "无")


if __name__ == "__main__":
    main()
