# -*- coding: utf-8 -*-
"""Phase D：自我情绪——反思时"审视自己"，对自己产生情绪，并和自己和解。

关键：只对"她自己的责任/作为"产生自我情绪，
不因"发生在她身上的难过（肚疼、饿）"扣分——那不是她的错。

每天 04:00 反思后跑一次：
  - 成就：今天画了 / 做了东西（source=art）→ 骄傲
  - 陪伴：今天好好陪了爸爸（video_call/companion 正向）→ 安心
  - 过错：答应了还在期、还没做（nails 活跃承诺）→ 内疚/自责
  - 和上次平滑（和解：不因一天坏心情永久压垮自己）

写 state/self_emotion.json，供情绪插件/提示词读取。
"""
import io
import json
import os
import sqlite3
import time

ROOT = r"D:\你的数据目录"
STATE = os.path.join(ROOT, "state")
OUT = os.path.join(STATE, "self_emotion.json")
NAILS = os.path.join(STATE, "persona", "nails.json")
DB = os.path.join(ROOT, "livingmemory", "livingmemory.db")


def _today_stats():
    """今天 0 点起的记忆：成就(art) / 陪伴(正向 video·companion) / 正负向。"""
    now = time.time()
    lt = time.localtime(now)
    day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    st = {"art": 0, "company": 0, "pos": 0, "neg": 0}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True,
                              timeout=3)
        for (m,) in con.execute(
                "SELECT metadata FROM documents ORDER BY created_at DESC LIMIT 200"):
            try:
                md = json.loads(m)
                if float(md.get("create_time") or 0) < day0:
                    continue
                src = md.get("source")
                vs = (md.get("mood_snapshot") or {}).get("valence")
                if vs is not None:
                    if float(vs) >= 0.1:
                        st["pos"] += 1
                    elif float(vs) <= -0.1:
                        st["neg"] += 1
                if src == "art":
                    st["art"] += 1
                if src in ("video_call", "companion") and vs is not None and float(vs) >= 0.1:
                    st["company"] += 1
            except Exception:  # noqa: BLE001
                pass
        con.close()
    except Exception:  # noqa: BLE001
        pass
    return st


def _active_promises():
    try:
        d = json.load(io.open(NAILS, encoding="utf-8"))
        now = time.time()
        return sum(1 for p in d.get("promises", []) if float(p.get("until") or 0) > now)
    except Exception:  # noqa: BLE001
        return 0


def evaluate():
    st = _today_stats()
    prom = _active_promises()
    # 自我价值：0.5 起步（中性）
    raw = 0.5
    raw += 0.06 * min(3, st["art"])        # 今天画了/做了东西 → 骄傲
    raw += 0.02 * min(5, st["company"])    # 今天好好陪了爸爸 → 安心
    raw -= 0.08 * min(3, prom)             # 答应了还在期、还没做 → 内疚
    # 注意：不因"发生在她身上的难过(肚疼/饿)"扣分——那不是她的错
    raw = max(0.0, min(1.0, raw))
    # 和解：和上次平滑（不因一天好坏大起大落）——"能原谅自己"
    prev = 0.5
    try:
        prev = float(json.load(io.open(OUT, encoding="utf-8")).get("worth") or 0.5)
    except Exception:  # noqa: BLE001
        pass
    worth = round(0.6 * raw + 0.4 * prev, 3)
    if worth >= 0.65:
        emo = "骄傲"
    elif worth >= 0.45:
        emo = "平静"
    elif worth >= 0.30:
        emo = "自责"
    else:
        emo = "内疚"
    return worth, emo, {"art": st["art"], "company": st["company"],
                        "pos": st["pos"], "neg": st["neg"],
                        "promises": prom, "raw": round(raw, 3)}


def main():
    worth, emo, why = evaluate()
    os.makedirs(STATE, exist_ok=True)
    try:
        with io.open(OUT, "w", encoding="utf-8") as f:
            json.dump({"worth": worth, "emotion": emo, "why": why,
                       "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    print("自我情绪: %s 自我价值=%.3f 依据=%s" % (emo, worth, why))


if __name__ == "__main__":
    main()
