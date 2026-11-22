# -*- coding: utf-8 -*-
"""给记忆标"这是事实、偏好，还是推断"（元记忆的最小版）。

为什么要有：
    她的记忆里混着三种话——
      事实：「你说期中考试考新媒体」
      偏好：「你喜欢喝杨枝甘露」
      推断：「大概是他想找人说说话」  ← 模型猜的
    现在三者在库里权重一样，她就会把"我猜的"当"他说过的"复述。

做法（2026-11-04，低风险版）：
    - 只用规则判断，不调模型、不改正文，只在 metadata 上加两个字段：
        claim_type: fact | preference | inference
        confidence: 0.0 ~ 1.0
    - 旧记忆没有这两个字段时，检索侧按 1.0 处理（不惩罚）。

用法：
    python memory_claim.py --dry-run          # 只统计 + 抽样，不写库
    python memory_claim.py --dry-run --limit 20
    python memory_claim.py --apply            # 真的写进 metadata（会先备份）

退出码：0 正常；1 出错。
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
BACKUP_DIR = r"D:\你的数据目录\livingmemory\backups"

# 推断词：出现这些，说明这句是"猜的"
INFERENCE_WORDS = (
    "大概", "可能", "应该", "似乎", "好像", "估计", "想必", "看来",
    "感觉", "恐怕", "说不定", "也许", "或许", "猜", "推测", "多半",
    "八成", "像是", "有点像", "恐怕是", "大概是",
)
# 偏好词：说明这是"她/你的口味与习惯"
PREFERENCE_WORDS = (
    "喜欢", "爱喝", "爱吃", "讨厌", "不喜欢", "偏爱", "习惯了",
    "最怕", "受不了", "合胃口", "爱吃", "爱听", "爱玩",
)
# 明确表示"没把握"的措辞，进一步降置信度
UNCERTAIN_WORDS = ("说不清", "没明说", "不确定", "好像没", "记不清")


def classify(text):
    """返回 (claim_type, confidence)。"""
    t = str(text or "")
    if any(w in t for w in INFERENCE_WORDS):
        conf = 0.55
        if any(w in t for w in UNCERTAIN_WORDS):
            conf = 0.45
        return "inference", conf
    if any(w in t for w in PREFERENCE_WORDS):
        return "preference", 0.80
    return "fact", 0.90


def load(only_missing=True):
    con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True, timeout=3)
    try:
        rows = con.execute("select id, text, metadata from documents order by id").fetchall()
    finally:
        con.close()
    out = []
    for doc_id, text, meta in rows:
        try:
            m = json.loads(meta or "{}")
        except Exception:
            m = {}
        if only_missing and m.get("claim_type"):
            continue
        out.append((doc_id, text, m))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    rows = load()
    counts = Counter()
    samples = {"inference": [], "preference": [], "fact": []}
    for doc_id, text, m in rows:
        kind, conf = classify(text)
        counts[kind] += 1
        if len(samples[kind]) < args.limit:
            samples[kind].append((doc_id, round(conf, 2), (text or "")[:70]))

    print(t("memory.pending", count=len(rows)))
    for k in ("fact", "preference", "inference"):
        print(t("memory.claim_count", kind=k, count=counts[k]))
    for k in ("inference", "preference"):
        print("\n" + t("memory.sample", kind=k))
        for doc_id, conf, text in samples[k]:
            print("  #%-4d conf=%.2f  %s" % (doc_id, conf, text))

    if args.dry_run or not args.apply:
        print("\n" + t("memory.dry_run"))
        return 0

    # 写库前先备份
    os.makedirs(BACKUP_DIR, exist_ok=True)
    snap = os.path.join(BACKUP_DIR, "before_claim_type_%s.db" % time.strftime("%Y%m%d_%H%M%S"))
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(snap)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(t("memory.backed_up", path=snap))

    con = sqlite3.connect(DB, timeout=10)
    try:
        con.execute("begin immediate")
        n = 0
        for doc_id, _, _ in rows:
            current = con.execute(
                "select text, metadata from documents where id=?", (doc_id,)
            ).fetchone()
            if current is None:
                continue
            text, metadata = current
            m = json.loads(metadata or "{}")
            if not isinstance(m, dict):
                raise ValueError(t("memory.metadata_object"))
            if m.get("claim_type"):
                continue
            kind, conf = classify(text)
            m["claim_type"] = kind
            m["confidence"] = round(conf, 2)
            con.execute("update documents set metadata=? where id=?", (json.dumps(m, ensure_ascii=False), doc_id))
            n += 1
        con.commit()
    finally:
        con.close()
    print(t("memory.written", count=n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
