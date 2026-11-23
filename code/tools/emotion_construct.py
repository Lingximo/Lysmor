# -*- coding: utf-8 -*-
"""Phase B 影子：构造主义情绪（只算、只记，绝不接行为）。

人类的情绪不是"身体→标签"的固定表，而是"身体感受 + 最近上下文"当场构造的。
同一个身体（比如高唤醒），若最近都是开心事 → 兴奋；若最近都是难受事 → 焦虑。

这里只"影子"算一遍，和当前 emotion_type 对比，写日志；不改变任何行为。
"""
import io
import json
import os
import sqlite3
import time

MOOD = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
        r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
LOG = r"D:\你的数据目录\logs\emotion_construct_shadow.jsonl"
OUT = r"D:\你的数据目录\state\emotion_constructed.json"


def read_body():
    try:
        st = json.load(io.open(MOOD, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        "valence": float(st.get("valence") or 0),
        "energy": float(st.get("energy") or 0.5),
        "cortisol": float(st.get("cortisol") or 0),
        "sadness": float(st.get("sadness") or 0),
        "scar": float(st.get("scar") or 0),
        "loneliness": float(st.get("loneliness") or 0),
        "clinginess": float(st.get("clinginess") or 0),
        "emotion_type": str(st.get("emotion_type") or ""),
        "activity": str(st.get("activity") or ""),
        "asleep": bool(st.get("asleep")),
    }


def recent_memory_tone(limit=6):
    """最近几条记忆的情绪基调（mood_snapshot.valence 的平均）。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True,
                              timeout=3)
        vals = []
        for (m,) in con.execute(
                "SELECT metadata FROM documents ORDER BY created_at DESC LIMIT ?", (limit,)):
            try:
                vs = (json.loads(m).get("mood_snapshot") or {}).get("valence")
                if vs is not None:
                    vals.append(float(vs))
            except Exception:  # noqa: BLE001
                pass
        con.close()
        return (sum(vals) / len(vals) if vals else 0.0), len(vals)
    except Exception:  # noqa: BLE001
        return 0.0, 0


def construct(body, ctx_valence):
    """构造主义：感受(唤醒/愉悦) + 上下文(最近记忆基调) → 情绪。

    关键：同一个"唤醒"，上下文不同，构造出来的情绪就不同。
    """
    arousal = float(body.get("energy") or 0.5)   # 唤醒（0~1）
    pleasant = float(body.get("valence") or 0)   # 愉悦（-1~1）
    ctx = float(ctx_valence or 0)                # 最近记忆的情绪基调
    # 睡着就是睡着，不构造"低落/焦虑"（这是生理事实，不是情绪构造）
    if body.get("asleep"):
        return "困倦"
    if arousal > 0.55:
        if ctx >= 0.12:
            label = "兴奋"
        elif ctx <= -0.12:
            label = "焦虑"
        else:
            label = "紧张"
    elif arousal < 0.40:
        if ctx >= 0.12:
            label = "满足"
        elif ctx <= -0.12:
            label = "低落"
        else:
            label = "困倦"
    else:
        if ctx >= 0.12:
            label = "安心"
        elif ctx <= -0.12:
            label = "不安"
        else:
            label = "平静"
    # 身体愉悦度很低时，把正面的构造往"阴郁"压一档（人的"身体把情绪染灰"）
    if pleasant <= -0.30 and label in ("兴奋", "满足", "安心"):
        label = {"兴奋": "烦躁", "满足": "怅然", "安心": "不安"}[label]
    return label


def main():
    body = read_body()
    if not body:
        return
    ctx_val, n = recent_memory_tone()
    cur = body.get("emotion_type") or ""
    constructed = construct(body, ctx_val)
    rec = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "current": cur,
        "constructed": constructed,
        "match": constructed == cur,
        "arousal": round(body["energy"], 3),
        "pleasant": round(body["valence"], 3),
        "context_valence": round(ctx_val, 3),
        "ctx_memories": n,
        "activity": body.get("activity"),
        "asleep": body.get("asleep"),
    }
    # 置信度：上下文越明确、身体越"激活"，构造越可信
    try:
        conf = min(1.0, abs(ctx_val) * 4.0 + abs(body.get("valence") or 0) * 2.0
                   + abs(body["energy"] - 0.5) * 1.5)
    except Exception:
        conf = 0.0
    rec["confidence"] = round(conf, 3)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 写"构造情绪"给情绪插件读（Phase B 上线桥）
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with io.open(OUT, "w", encoding="utf-8") as f:
            json.dump({"constructed": constructed, "at": time.time(),
                       "confidence": rec["confidence"], "current": cur},
                      f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass
    print("当前=%s 构造=%s 上下文=%.3f(%d条) conf=%.2f match=%s"
          % (cur, constructed, ctx_val, n, rec["confidence"], rec["match"]))


if __name__ == "__main__":
    main()
