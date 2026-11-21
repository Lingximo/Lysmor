# -*- coding: utf-8 -*-
"""TA适配健康检查（只读）。

用途：每次改完生命状态 / P5b / 梦境 / 疤痕 / 记忆相关代码后跑一次。
只读 state、8005、8007、pending 和插件源码，不写任何东西。

用法：
    py.cmd check_adaption.py
退出码：0 全过；1 有失败项。
"""
import json
import os
import sqlite3
import sys
import urllib.request

STATE = (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data"
    r"\plugin_data\astrbot_plugin_companion_mood\state.json"
)
MAIN = (
    r"C:\你的用户\.astrbot_launcher\instances"
    r"\<BOT_INSTANCE>\core\data"
    r"\plugins\astrbot_plugin_companion_mood\main.py"
)
PENDING = r"D:\你的数据目录\video\pending_memories.json"
DB = r"D:\你的数据目录\livingmemory\livingmemory.db"

ok_count = 0
fail_count = 0


def check(name, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print("OK   " + name + ((" | " + str(detail)) if detail else ""))
    else:
        fail_count += 1
        print("FAIL " + name + ((" | " + str(detail)) if detail else ""))


def http_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    if not os.path.exists(STATE):
        print("FAIL state.json 不存在: " + STATE)
        return 1
    with open(STATE, encoding="utf-8") as f:
        st = json.load(f)

    # 1) P5b 状态
    blend = st.get("emotion_blend")
    check("P5b emotion_blend 存在", isinstance(blend, list) and len(blend) > 0,
          blend)
    if isinstance(blend, list) and blend:
        total = sum(float(x.get("weight") or 0) for x in blend if isinstance(x, dict))
        check("P5b 权重接近 1", 0.9 <= total <= 1.1, round(total, 3))
    check("P5b emotion_tone 是字符串", isinstance(st.get("emotion_tone"), str),
          repr(st.get("emotion_tone"))[:60])
    check("P5b 开关是布尔", isinstance(st.get("emotion_tone_enabled"), bool),
          st.get("emotion_tone_enabled"))
    tone = str(st.get("emotion_tone") or "")
    bad_words = ("生气", "委屈", "害羞", "经前", "焦虑", "噩梦", "美梦")
    check("P5b tone 不直接复述情绪名", not any(w in tone for w in bad_words), tone)

    # 2) 梦境 / 疤痕字段
    for key in ("dream_posted_at", "dream_at", "dream_valence", "dream_residue"):
        check("梦境字段 " + key, key in st, st.get(key))
    for key in ("scar", "scar_events", "scar_touch_at"):
        check("疤痕字段 " + key, key in st, st.get(key))
    check("疤痕权重在 0~1", 0.0 <= float(st.get("scar") or 0) <= 1.0, st.get("scar"))
    check("scar_events 是整数", isinstance(st.get("scar_events"), int), st.get("scar_events"))

    # 3) 8005 生命状态 API
    try:
        lv = http_json("http://127.0.0.1:8005/api/state")
        check("8005 /api/state 可读", True)
        check("8005 暴露 P5b blend", "emotion_blend" in lv, lv.get("emotion_blend"))
        check("8005 暴露 P5b tone", "emotion_tone" in lv, lv.get("emotion_tone"))
        check("8005 暴露疤痕", "scar" in lv, lv.get("scar"))
        check("8005 暴露梦境", "dream_residue" in lv, lv.get("dream_residue"))
    except Exception as exc:  # noqa: BLE001
        check("8005 /api/state 可读", False, exc)

    # 4) 8007 大平层
    try:
        h = http_json("http://127.0.0.1:8007/api/house")
        check("8007 /api/house 可读", True)
        check("8007 有她的位置", bool(h.get("her", {}).get("room")), h.get("her", {}).get("room"))
        check("8007 有冰箱字段", "fridge" in h.get("mood", {}), h.get("mood", {}).get("fridge"))
    except Exception as exc:  # noqa: BLE001
        check("8007 /api/house 可读", False, exc)

    # 5) 记忆队列 / 库
    try:
        with open(PENDING, encoding="utf-8") as f:
            pending = json.load(f)
        check("pending 可读且为空", pending == [], len(pending))
    except Exception as exc:  # noqa: BLE001
        check("pending 可读", False, exc)
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
        docs = con.execute("select count(*) from documents").fetchone()[0]
        con.close()
        check("记忆库可读", True, docs)
    except Exception as exc:  # noqa: BLE001
        check("记忆库可读", False, exc)

    # 6) 源码关键规则还在
    try:
        src = open(MAIN, encoding="utf-8").read()
        checks = {
            "P5b 开关": "emotion_tone_enabled" in src,
            "P5b 只写语气": "emotion_tone" in src and "不要说出情绪名" in src,
            "梦境正常 5% 美梦": "bad_chance, good_chance = 0.0, 0.05" in src,
            "梦境不错 10% 美梦": "bad_chance, good_chance = 0.0, 0.10" in src,
            "梦境差 10% 噩梦": "bad_chance, good_chance = 0.10, 0.0" in src,
            "梦境发空间": "dream_posted_at" in src and "_post_qzone_text" in src,
            "疤痕 0.7 地板": "floor = 0.70" in src,
            "疤痕再触发": "_touch_scar" in src,
        }
        for name, cond in checks.items():
            check(name, cond)
    except Exception as exc:  # noqa: BLE001
        check("读取插件源码", False, exc)

    print("")
    print("结果：OK=%d FAIL=%d" % (ok_count, fail_count))
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
