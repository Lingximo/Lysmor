# -*- coding: utf-8 -*-
"""记忆召回的两个新维度是否还正常（2026-11-03 P0/P1）。

P0 时间半衰期：recency = exp(-ln2 / 半衰期天数 × 记忆年龄)
P1 情绪一致性：同向加分、反向不加、双负减半、心情太淡不动
P2 显式线索：查询里出现"昨天/视频"这类词才给分，且要和记忆的日期/来源对上

只读、纯函数：不连数据库、不写记忆、不读她的 state（只有一条会读 8005）。
改完 livingmemory 的检索逻辑后跑一次，全 [OK] 才算没打坏。

    python check_memory_affect.py
    python check_memory_affect.py --live   # 顺便打印她此刻的情绪坐标

退出码：0 全过；1 有失败。
"""
import os
import sys
import time

CORE = (r"C:\你的用户\.astrbot_launcher\instances"
        r"\<BOT_INSTANCE>\core")
os.environ.setdefault("ASTRBOT_ROOT", CORE)
sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(CORE, "data", "plugins"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from astrbot_plugin_livingmemory.core.retrieval.affect import (  # noqa: E402
    current_affect,
    match_score,
    memory_valence,
)
from astrbot_plugin_livingmemory.core.retrieval.hybrid_retriever import (  # noqa: E402
    HybridRetriever,
)
from astrbot_plugin_livingmemory.core.retrieval.rrf_fusion import FusedResult  # noqa: E402

NOW = time.time()
FAILS = []


def check(name, ok, detail=""):
    print(("[OK]   " if ok else "[FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


class Dummy:
    pass


def fused(doc_id, days_old, importance=0.5, sentiment="neutral", emotion=None):
    meta = {
        "importance": importance,
        "create_time": NOW - days_old * 86400,
        "last_access_time": 0,
        "sentiment": sentiment,
    }
    if emotion:
        meta["emotion"] = emotion
    return FusedResult(
        doc_id=doc_id, rrf_score=1.0, bm25_score=1.0, vector_score=1.0,
        content="记忆%d" % doc_id, metadata=meta,
    )


def make(half_life, affect_weight=0.0, cue_weight=0.0):
    return HybridRetriever(
        Dummy(), Dummy(), Dummy(),
        {
            "recency_half_life_days": half_life,
            "decay_rate": 0.0,          # 与线上 importance_decay.decay_rate 一致
            "affect_weight": affect_weight,
            "cue_weight": cue_weight,
            "score_alpha": 0.5, "score_beta": 0.25, "score_gamma": 0.25,
        },
    )


def main():
    # P0 时间半衰期
    out = make(30)._apply_weighting([fused(1, 0.2), fused(2, 45)], NOW)
    check("P0 新记忆排在旧记忆前面", out[0].doc_id == 1,
          "%.3f vs %.3f" % (out[0].final_score, out[1].final_score))
    check("P0 45 天记忆的 recency < 0.5",
          out[1].score_breakdown["recency_weight"] < 0.5,
          "recency=%.3f" % out[1].score_breakdown["recency_weight"])

    out0 = make(0)._apply_weighting([fused(1, 0.2), fused(2, 45)], NOW)
    check("P0 半衰期=0 时保持旧行为",
          all(abs(x.score_breakdown["recency_weight"] - 1.0) < 1e-9 for x in out0))

    scores = [make(30)._apply_weighting([fused(9, d)], NOW)[0].final_score
              for d in (0, 7, 30, 90)]
    check("P0 分数随年龄单调下降", scores == sorted(scores, reverse=True),
          " ".join("%.3f" % s for s in scores))

    # P1 情绪一致性
    happy = {"valence": 0.7, "arousal": 0.5, "labels": ["满足"]}
    sad = {"valence": -0.7, "arousal": 0.3, "labels": ["生病"]}
    pos, neg, neu = {"sentiment": "positive"}, {"sentiment": "negative"}, {"sentiment": "neutral"}

    check("P1 开心 + 正面记忆 = 高匹配", match_score(happy, pos) > 0.4,
          "%.3f" % match_score(happy, pos))
    check("P1 开心 + 负面记忆 = 0", match_score(happy, neg) == 0.0)
    check("P1 难过 + 负面记忆被减半", match_score(sad, neg) <= 0.35,
          "%.3f" % match_score(sad, neg))
    check("P1 中性记忆不加分", match_score(happy, neu) == 0.0)
    check("P1 没有心情不加分", match_score(None, pos) == 0.0)
    check("P1 心情太淡不加分", match_score({"valence": 0.01}, pos) == 0.0)
    check("P1 写侧 emotion 优先于 sentiment",
          memory_valence({"emotion": {"valence": -0.9}, "sentiment": "positive"}) == -0.9)

    # 线上那份权重不该把当前排序打乱
    a = make(30, 0.0)._apply_weighting([fused(1, 1, sentiment="positive")], NOW)[0].final_score
    b = make(30, 0.15)._apply_weighting([fused(1, 1, sentiment="positive")], NOW)[0].final_score
    check("P1 情绪项不改变量级（<=0.15）", abs(a - b) <= 0.15 + 1e-9,
          "%.4f vs %.4f" % (a, b))

    # P2 显式线索
    r_cue = make(30, 0.0, 0.15)
    yday = {"create_time": NOW - 86400, "source": "video_call"}
    old = {"create_time": NOW - 3 * 86400, "source": "video_call"}
    check("P2 昨天+视频 命中", r_cue._cue_bonus("昨天的视频还开吗", yday, NOW) >= 1.0)
    check("P2 日期对不上不给分", r_cue._cue_bonus("今天吃了什么", old, NOW) == 0.0)
    check("P2 没有线索词不给分", r_cue._cue_bonus("随便聊聊呀", yday, NOW) == 0.0)
    check("P2 来源对不上不给分",
          r_cue._cue_bonus("上次画画的那个", {"create_time": NOW - 86400, "source": "video_call"}, NOW) == 0.0)

    no_cue = make(30, 0.0, 0.0)._apply_weighting([fused(1, 1, sentiment="neutral")], NOW, "昨天的视频")[0].final_score
    with_cue = r_cue._apply_weighting([fused(1, 1, sentiment="neutral")], NOW, "昨天的视频")[0].final_score
    check("P2 线索只加不超过 0.15", 0.0 < with_cue - no_cue <= 0.15 + 1e-9,
          "%.4f vs %.4f" % (no_cue, with_cue))

    # P3 元记忆：推断类降权，旧记忆不降
    r_meta = make(30)

    def with_meta(**kw):
        meta = {"importance": 0.5, "create_time": NOW - 86400, "last_access_time": 0}
        meta.update(kw)
        return FusedResult(doc_id=7, rrf_score=1.0, bm25_score=1.0, vector_score=1.0,
                           content="x", metadata=meta)

    plain = r_meta._apply_weighting([with_meta()], NOW)[0].score_breakdown["claim_factor"]
    inf = r_meta._apply_weighting(
        [with_meta(claim_type="inference", confidence=0.55)], NOW
    )[0].score_breakdown["claim_factor"]
    fact = r_meta._apply_weighting(
        [with_meta(claim_type="fact", confidence=0.9)], NOW
    )[0].score_breakdown["claim_factor"]
    check("P3 旧记忆（无 claim_type）不降权", plain == 1.0, "%.3f" % plain)
    check("P3 事实不降权", fact == 1.0, "%.3f" % fact)
    check("P3 推断降权到 0.874", abs(inf - 0.874) < 0.001, "%.3f" % inf)

    from memory_claim import classify

    check("P3 分类：事实", classify("你说期中考试考新媒体")[0] == "fact")
    check("P3 分类：偏好", classify("你喜欢喝杨枝甘露")[0] == "preference")
    check("P3 分类：推断", classify("大概是他想找人说说话")[0] == "inference")

    if "--live" in sys.argv:
        print("\n她此刻的情绪坐标:", current_affect())

    print("\n结论：%s" % ("全部通过" if not FAILS else "失败 %d 项：%s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
