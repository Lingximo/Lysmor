"""校准TA的饥饿状态（一次性修补用）。

用来处理"你喂了但系统没记"的情况：按实际进食时间把饥饿值拉回去，
并顺便把饭后的激素状态（副交感、心满意足）一起摆正。

用法:
  python fix_hunger.py --meal "2026-10-29 20:38" --level 0.10
  python fix_hunger.py --show
"""
import argparse
import json
import os
import time

STATE = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>-4d81-"
         r"4fe1-a8e7-e504fbdc999b\core\data\plugin_data"
         r"\astrbot_plugin_companion_mood\state.json")


def load():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def show():
    s = load()
    print("饥饿: %.2f（%s）" % (s.get("hunger", 0), "很饿" if s.get("hunger", 0) > 0.8 else "还行"))
    print("上次进食:", time.strftime("%m-%d %H:%M", time.localtime(s.get("last_meal") or 0)))
    for k in ("cortisol", "serotonin", "noradrenaline", "dopamine", "oxytocin"):
        print(f"  {k}: {s.get(k):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--meal", help="实际进食时间，如 2026-10-29 20:38")
    ap.add_argument("--level", type=float, default=0.10, help="吃完后的饥饿值（默认 0.10）")
    args = ap.parse_args()

    if args.show or not args.meal:
        show()
        return 0

    meal_ts = time.mktime(time.strptime(args.meal, "%Y-%m-%d %H:%M"))
    if meal_ts > time.time():
        print("进食时间不能在未来")
        return 1

    s = load()
    before = s.get("hunger", 0)
    s["hunger"] = max(0.03, min(1.0, args.level))
    s["last_meal"] = meal_ts
    # 刚吃完的副交感状态：皮质醇低、血清素高、去甲平稳、多巴胺略升
    s["cortisol"] = min(s.get("cortisol", 0.2), 0.17)
    s["serotonin"] = max(s.get("serotonin", 0.65), 0.67)
    s["noradrenaline"] = min(max(s.get("noradrenaline", 0.5), 0.45), 0.58)
    s["dopamine"] = max(s.get("dopamine", 0.5), 0.52)
    s["last_update"] = time.time()
    save(s)

    print("已校准")
    print("  饥饿 %.2f -> %.2f" % (before, s["hunger"]))
    print("  上次进食:", time.strftime("%m-%d %H:%M", time.localtime(meal_ts)))
    print("  皮质醇 %.2f / 血清素 %.2f / 去甲 %.2f / 多巴胺 %.2f"
          % (s["cortisol"], s["serotonin"], s["noradrenaline"], s["dopamine"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
