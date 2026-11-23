# -*- coding: utf-8 -*-
"""情绪一致性召回（拟人化）：让她"难过时想起难过的事，安心时想起温暖的回忆"。

人类记忆不是硬盘检索，而是"一种感觉，被相似的感觉再次点燃"（状态依赖 /
情绪一致性记忆，Tulving 的编码特异性）。她的每条记忆 metadata 里已经存了
mood_snapshot（当时的情绪+生理快照）——这里把它用起来：召回时把"记忆里的感觉"
和"此刻的她"做相似度，感觉越接近越容易被想起。

设计原则：
- 只读、可解释、权重可调（MOOD_WEIGHT=0 即关闭 = 完全回滚到原召回）。
- 保守：只做"重排"（在已拉到的候选里调整顺序），不改变"能不能想起"，
  保证永远不会把她的嘴封死。
"""

import io
import json
import os
import time

MOOD = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
        r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")

# 情绪一致性的权重：0 = 关闭/回滚；0.25 = 轻微偏向；想更强可调到 0.4
MOOD_WEIGHT = 0.25

SHADOW = r"D:\你的数据目录\logs\mood_recall_shadow.jsonl"


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def cur_feeling():
    """此刻的她：归一化到和 mood_snapshot 相同的字段名。失败返回 {}。"""
    try:
        st = json.load(io.open(MOOD, encoding="utf-8"))
        return {
            "emotion": st.get("emotion_type") or "",
            "emotion_blend": st.get("emotion_blend") or [],
            "valence": float(st.get("valence") or 0),
            "energy": float(st.get("energy") or 0.5),
            "clinginess": float(st.get("clinginess") or 0),
            "loneliness": float(st.get("loneliness") or 0),
        }
    except Exception:  # noqa: BLE001
        return {}


def _blend_sim(a, b):
    """两个 emotion_blend 的重合度（0~1）。缺数据返回 None（不偏向）。"""
    da = {str(x.get("key")): float(x.get("weight") or 0)
          for x in (a or []) if isinstance(x, dict)}
    db = {str(x.get("key")): float(x.get("weight") or 0)
          for x in (b or []) if isinstance(x, dict)}
    if not da or not db:
        return None
    keys = set(da) | set(db)
    return sum(min(da.get(k, 0.0), db.get(k, 0.0)) for k in keys)


def feeling_sim(snapshot, cur=None):
    """记忆里的感觉 vs 此刻的她，0~1（越接近越像）。失败返回 0（不偏向）。"""
    snap = snapshot if isinstance(snapshot, dict) else {}
    cur = cur if cur is not None else cur_feeling()
    if not cur:
        return 0.0
    score = 0.0
    # 情绪标签一致（占 0.18）
    se = (snap.get("emotion") or "").strip()
    ce = (cur.get("emotion") or "").strip()
    if se and se == ce:
        score += 0.18
    # 混色重合（Phase A 新字段；旧记忆没有就跳过）
    bs = _blend_sim(snap.get("emotion_blend"), cur.get("emotion_blend"))
    if bs is not None:
        score += 0.12 * bs
    # 数值字段接近（valence 0.25 / energy 0.15 / clinginess 0.18 / loneliness 0.12）
    for f, w in (("valence", 0.25), ("energy", 0.15), ("clinginess", 0.18), ("loneliness", 0.12)):
        try:
            a = float(snap.get(f))
        except Exception:
            continue
        b = float(cur.get(f, 0.5))
        score += w * (1.0 - min(1.0, abs(a - b)))
    return _clamp(score)


def shadow_log(query, cur, top_sims):
    """只记录：此刻感觉 + 想起的记忆感觉（用于验证规律，不改行为）。"""
    try:
        rec = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "query": (query or "")[:60],
            "cur": cur,
            "top_sims": (top_sims or [])[:6],
        }
        os.makedirs(os.path.dirname(SHADOW), exist_ok=True)
        with io.open(SHADOW, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    import sys
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    cur = cur_feeling()
    print("此刻的她:", cur)
    print("自测（相同感觉→1.0）:", round(feeling_sim(cur, cur), 3))
    print("自测（空快照→0.0）:", round(feeling_sim({}, cur), 3))
