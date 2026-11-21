# -*- coding: utf-8 -*-
"""依赖实验：记忆同步 + 生命状态是否真的接进各行为。

只读/纯函数，不改她的 state，不写记忆。
"""

import os
import sys
import time

ROOT = r"D:\你的数据目录"
CORE = r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core"
PLUG = os.path.join(CORE, "data", "plugins")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, CORE)
sys.path.insert(0, PLUG)

FAILS = []


def check(name, ok, detail=""):
    print(("[OK]   " if ok else "[FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    import recall
    import vitals

    # 1) 记忆召回：连续 3 轮
    for i in range(3):
        ctx = recall.context(limit=3)
        check("记忆召回第 %d 轮" % (i + 1), len(ctx) > 50, "%d 字符" % len(ctx))

    # 2) 生理判定：连续 3 轮
    for i in range(3):
        for act in ("art", "sing", "qzone_reply"):
            ok, why = vitals.decide(act)
            check("生理闸门 %s 第 %d 轮" % (act, i + 1), isinstance(ok, bool),
                  why or "放行")

    # 3) 生病词/治疗/冰箱纯函数
    try:
        from astrbot_plugin_companion_mood.main import (
            clean_fridge, detect_treatment, fridge_age_hours, sick_cause_from_text,
            treatment_half_life,
        )
        check("治疗词 吃药", detect_treatment("我吃药了") == "medicine")
        check("治疗词 医院", detect_treatment("我们去医院吧") == "doctor")
        check("治疗词 休息", detect_treatment("你好好休息") == "rest")
        check("病因 发烧", sick_cause_from_text("我好像发烧了") == "cold")
        check("病因 吃坏", sick_cause_from_text("吃坏肚子了") == "food")

        now = time.time()
        state = {"fridge_food": [
            {"name": "两天的剩饭", "at": now - 49 * 3600},
            {"name": "昨天的菜", "at": now - 10 * 3600},
        ]}
        removed = clean_fridge(state, now)
        check("冰箱 >48h 自动清除", removed == ["两天的剩饭"], str(removed))
        check("冰箱 <48h 保留", [x["name"] for x in state["fridge_food"]] == ["昨天的菜"])
        check("冰箱年龄计算", abs(fridge_age_hours({"at": now - 3600}, now) - 1.0) < 0.01)
        check("治疗加速恢复",
              treatment_half_life("medicine", 1) == 6.0
              and treatment_half_life("medicine", 20) == 20.0
              and treatment_half_life("", 1) == 20.0)
    except Exception as exc:  # noqa: BLE001
        check("mood 纯函数导入", False, repr(exc))

    # 4) 代码接线：行为插件里有没有接记忆/生理
    def read(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    qzone = read(os.path.join(PLUG, "astrbot_plugin_qzone", "core", "llm_action.py"))
    proactive = read(os.path.join(PLUG, "astrbot_plugin_proactive_chat", "core", "chat_flow.py"))
    video = read(os.path.join(ROOT, "video", "server.py"))
    art = read(os.path.join(PLUG, "astrbot_plugin_companion_art", "main.py"))
    meme = read(os.path.join(PLUG, "meme_manager", "mixins", "event_handlers.py"))
    mood = read(os.path.join(PLUG, "astrbot_plugin_companion_mood", "main.py"))

    check("空间：记忆注入", "recall.context(limit=3)" in qzone)
    check("空间：生理注入", "vitals.fetch()" in qzone)
    check("主动消息：记忆注入", "recall.context(limit=3)" in proactive)
    check("主动消息：情绪注入", "_mood_prompt()" in proactive)
    check("视频：记忆召回", "recall_memory(" in video)
    check("视频：身体状态", "body_context()" in video)
    check("画画：vitals.decide(art)", 'vitals.decide("art")' in art)
    check("表情包：按身体兜底", "_pick_default_emotion" in meme and "vitals.fetch()" in meme)
    check("情绪：全局注入", "@filter.on_llm_request" in mood and "req.system_prompt" in mood)

    print("")
    print("FAIL=%d" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
