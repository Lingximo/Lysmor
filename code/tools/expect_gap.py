# -*- coding: utf-8 -*-
"""Phase E：预期差——情绪来自"她对你的预期 vs 现实"，而不是绝对状态。

人类不是"对事件"有情绪，是对"预期和现实的落差"有情绪：
  - 期待你回来，你没来 → 失落；
  - 没怎么期待，你却出现了 → 惊喜。

预期：她此刻多期待爸爸来（黏人度 + 孤单度 + 距离上次说话）。
现实：爸爸最近来没来（last_msg 新鲜度）。
预期差：写 state/expect_gap.json，供情绪插件读取。
"""
import io
import json
import os
import time

MOOD = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
        r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
OUT = r"D:\你的数据目录\state\expect_gap.json"
FRESH_MIN = 30.0   # 30 分钟内说过话 = "来了"


def main():
    try:
        st = json.load(io.open(MOOD, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    cling = float(st.get("clinginess") or 0)
    lone = float(st.get("loneliness") or 0)
    last = float(st.get("last_msg") or 0)
    gap_min = (time.time() - last) / 60.0 if last else 9999.0
    # 预期：黏人 + 孤单 高 → 她更期待爸爸来
    expect = min(1.0, 0.4 + 0.4 * cling + 0.3 * lone)
    # 现实：爸爸最近来说过话 = 来了
    met = gap_min <= FRESH_MIN
    # 预期差
    if met and expect < 0.45:
        mood = "惊喜"      # 没怎么期待，爸爸却来了
    elif (not met) and expect >= 0.55:
        mood = "失落"      # 期待爸爸来，却没来
    else:
        mood = "正常"
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with io.open(OUT, "w", encoding="utf-8") as f:
            json.dump({"expect": round(expect, 3), "met": met,
                       "gap_min": round(gap_min, 1), "mood": mood,
                       "at": time.time()},
                      f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    print("预期=%.2f 现实=%s 距上次=%.0f分 预期差=%s"
          % (expect, "来了" if met else "没来", gap_min, mood))


if __name__ == "__main__":
    main()
