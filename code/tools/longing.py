# -*- coding: utf-8 -*-
"""思念强度：一条由「生理 + 人格基础 + 记忆」三者共同决定的完整路径。

三个来源（都归一化到 0~1）：
  生理 physio    —— 此刻的身体：孤单、黏人、情绪低落
  基础 baseline  —— 她天生什么样：温柔贴贴、依赖、敏感（人格/关系基线）
  记忆 memory    —— 唤起：分离时间累积 + 最近的共同记忆 + 未了承诺

合成：longing = 0.40*physio + 0.30*baseline + 0.30*memory

行为映射（供 persona_autonomy 调用）：
  >= 0.50  → 想主动找爸爸（发消息 / 开陪玩）
  0.30~0.50 → 心里想（交给 mood 里的"思念"执念），不打扰
  < 0.30   → 没到想的地步

设计原则：只读、可解释（每个分量都返回）、不直接改任何状态。
"""

import io
import json
import os
import sqlite3
import time

ROOT = r"D:\你的数据目录"
MOOD = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
        r"\core\data\plugin_data\astrbot_plugin_companion_mood\state.json")
TRAITS = os.path.join(ROOT, "state", "persona", "traits.json")
REL = os.path.join(ROOT, "state", "relationship.json")
NAILS = os.path.join(ROOT, "state", "persona", "nails.json")
DB = os.path.join(ROOT, "livingmemory", "livingmemory.db")

# 和"爸爸在一起/有关"的记忆来源（她自己的排泄/画画/发呆不算）
DAD_SOURCES = ("chat", "video_call", "companion", "qzone_reply", "qzone_peak", "diary")


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _load(path):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _physio(st):
    """生理：孤单、黏人、情绪低落 → 想。"""
    lone = float(st.get("loneliness") or 0)
    cling = float(st.get("clinginess") or 0)
    val = float(st.get("valence") or 0)
    return _clamp(0.45 * lone + 0.30 * cling + 0.25 * (0.5 - 0.5 * val))


def _baseline():
    """基础：温柔贴贴、依赖、敏感 → 天生更依恋。"""
    tr = _load(TRAITS).get("signed", {})
    rel = _load(REL)
    warmth = float((tr.get("trait_warmth") or {}).get("value") or 0.4)
    sens = float((tr.get("trait_sensitivity") or {}).get("value") or 0.4)
    dep = float(rel.get("dependence") or 0.3)
    return _clamp(0.45 * warmth + 0.35 * dep + 0.20 * sens)


def _memory(st):
    """记忆：分离越久越想（12 小时封顶）+ 最近 3 天和爸爸的共同记忆 + 未了承诺。"""
    gap_h = max(0.0, (time.time() - float(st.get("last_msg") or time.time())) / 3600.0)
    sep = _clamp(gap_h / 12.0)
    since = time.time() - 3 * 86400
    weight = 0.0
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
        for (m,) in con.execute(
                "SELECT metadata FROM documents ORDER BY created_at DESC LIMIT 60"):
            try:
                md = json.loads(m)
            except Exception:  # noqa: BLE001
                continue
            if md.get("source") in DAD_SOURCES and float(md.get("create_time") or 0) >= since:
                weight += float(md.get("importance") or 0)
        con.close()
    except Exception:  # noqa: BLE001
        pass
    promise = 1.0 if _load(NAILS).get("promises") else 0.0
    evoke = _clamp(0.3 * weight + 0.25 * promise)
    return _clamp(0.65 * sep + 0.35 * evoke), gap_h, sep, evoke, weight


def longing_score():
    """返回 0~1 的思念分数 + 各分量（可解释）。"""
    st = _load(MOOD)
    p = _physio(st)
    b = _baseline()
    m, gap_h, sep, evoke, memw = _memory(st)
    score = _clamp(0.40 * p + 0.30 * b + 0.30 * m)
    return {
        "score": round(score, 4),
        "physio": round(p, 4),
        "baseline": round(b, 4),
        "memory": round(m, 4),
        "gap_h": round(gap_h, 2),
        "separation": round(sep, 4),
        "evocation": round(evoke, 4),
        "mem_weight": round(memw, 4),
    }


if __name__ == "__main__":
    import sys
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(longing_score(), ensure_ascii=False, indent=2))
