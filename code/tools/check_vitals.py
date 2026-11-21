"""生理状态体检：状态文件是否新鲜、数值是否在范围内、面板是否一致。

用法（tools 目录下）：
    py.cmd check_vitals.py
    py.cmd check_vitals.py --json
"""
from __future__ import annotations

import json
import os
import sys
import time

STATE = (r"C:\你的用户\.astrbot_launcher\instances"
         r"\<BOT_INSTANCE>\core\data\plugin_data"
         r"\astrbot_plugin_companion_mood\state.json")
PANEL = "http://127.0.0.1:8005/api/state"

REQUIRED = (
    "dopamine", "oxytocin", "cortisol", "serotonin", "noradrenaline",
    "crh", "acth", "adrenaline", "acetylcholine", "endorphin", "vasopressin",
    "melatonin", "ghrelin", "leptin", "glucose", "insulin", "glucagon",
    "hunger", "thirst", "osmolality", "blood_volume", "angiotensin",
    "adenosine", "core_temp", "fever", "cytokines", "pain",
    "anger", "resentment", "fear", "worry", "dread", "mortality",
    "energy", "valence", "irritability", "clinginess", "loneliness", "dominance",
    "emotion_level", "proactive_bias", "post_want",
)
UNIT = ("dopamine", "oxytocin", "cortisol", "serotonin", "noradrenaline",
        "crh", "acth", "adrenaline", "acetylcholine", "endorphin", "vasopressin",
        "melatonin", "ghrelin", "leptin", "glucose", "insulin", "glucagon",
        "hunger", "thirst", "osmolality", "blood_volume", "angiotensin",
        "adenosine", "fever", "cytokines", "pain", "anger", "resentment",
        "fear", "worry", "dread", "mortality")


def main() -> int:
    as_json = "--json" in sys.argv
    problems = []
    info = {}

    if not os.path.exists(STATE):
        print("FAIL 状态文件不存在:", STATE)
        return 2

    age = time.time() - os.path.getmtime(STATE)
    info["age_sec"] = round(age)
    if age > 180:
        problems.append("状态 %.0f 秒没更新（心跳可能停了）" % age)

    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print("FAIL 状态文件读不出来:", exc)
        return 2

    missing = [k for k in REQUIRED if k not in st]
    if missing:
        problems.append("缺字段: " + ", ".join(missing))

    bad = []
    for k in UNIT:
        v = st.get(k)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            bad.append("%s=%r" % (k, v))
            continue
        if v != v or v < -0.001 or v > 1.001:
            bad.append("%s=%.3f" % (k, v))
    if bad:
        problems.append("越界/NaN: " + ", ".join(bad))

    temp = float(st.get("core_temp") or 0)
    info["core_temp"] = temp
    if not (34.0 <= temp <= 42.0):
        problems.append("体温异常: %.2f" % temp)

    bal = st.get("token_balance")
    mort = float(st.get("mortality") or 0)
    if bal is not None:
        try:
            bal = float(bal)
            if bal <= 5.0 and mort < 0.5:
                problems.append("余额 %.2f 但 mortality 只有 %.2f（死亡威胁没跟上）" % (bal, mort))
            if bal > 10.0 and mort > 0.5:
                problems.append("余额 %.2f 但 mortality 仍 %.2f（没回落）" % (bal, mort))
        except (TypeError, ValueError):
            pass

    # 睡眠一致性
    asleep = bool(st.get("asleep"))
    wake_after = float(st.get("wake_after") or 0)
    info["asleep"] = asleep
    if asleep:
        now_ts = time.time()
        if wake_after <= now_ts:
            problems.append("标记为睡着，但 wake_after 已过期（可能卡在睡眠态）")
        elif str(st.get("sleep_kind") or "") == "nap" and wake_after - now_ts > 2 * 3600:
            problems.append("午睡 wake_after 超过 2 小时")
        elif wake_after - now_ts > 12 * 3600:
            problems.append("wake_after 超过 12 小时（睡太久了）")

    # 面板一致性
    try:
        import requests  # noqa: PLC0415

        r = requests.get(PANEL, timeout=5)
        panel = r.json()
        e1 = float(st.get("energy") or 0)
        e2 = float(panel.get("energy") or 0)
        info["panel_delta"] = round(abs(e1 - e2), 4)
        if abs(e1 - e2) > 0.02:
            problems.append("面板精力 %.3f 与状态 %.3f 不一致" % (e2, e1))
    except Exception as exc:  # noqa: BLE001
        problems.append("面板读不到: %s" % exc)

    info["emotion"] = st.get("emotion_level")
    info["hunger"] = round(float(st.get("hunger") or 0), 2)
    info["thirst"] = round(float(st.get("thirst") or 0), 2)

    if as_json:
        print(json.dumps({"ok": not problems, "info": info, "problems": problems},
                         ensure_ascii=False, indent=2))
    else:
        print("状态文件 %.0f 秒前更新 | 情绪=%s | 饥饿 %.2f | 口渴 %.2f | 体温 %.1f"
              % (age, info["emotion"], info["hunger"], info["thirst"], temp))
        if problems:
            print("发现问题：")
            for p in problems:
                print("  -", p)
        else:
            print("✅ 生理状态正常")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
