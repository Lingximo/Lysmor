# -*- coding: utf-8 -*-
"""把碎片记忆聚成「场景卡」（参考 TencentDB Agent Memory 的 L2 场景层）。

它做什么：
    读 livingmemory.db（只读），按 metadata.topics 把同一主题的记忆聚成一张
    Markdown 卡片，写到 D:\\你的数据目录\\memoryscene\\scenes\\。
    **不改数据库、不删记忆、不动 importance**——出问题删掉文件夹就回滚。

为什么要有：
    她有 260 个 topics、156 条记忆，但全是碎片（"睡前道晚安"5 条、"吃饭"5 条），
    没有一个"场景"能把它们串起来。场景卡是给人看的结构层，也是召回时的
    第一层（先给卡，再下钻到具体记忆）。

用法：
    python make_scenes.py --dry-run          # 只打印，不写文件
    python make_scenes.py --dry-run --limit 5
    python make_scenes.py                    # 真写 scenes/ + index.json

退出码：0 正常；1 出错。
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
OUT = r"D:\你的数据目录\memoryscene"
SCENES = os.path.join(OUT, "scenes")
INDEX = os.path.join(OUT, "index.json")

MIN_MEMORIES = 2          # 一个场景至少几条记忆（她的主题很碎，3 条会被砍掉大半）
WINDOW_DAYS = 14          # 同一主题按 14 天切段，避免把半年前的事混进来
MAX_CARDS = 40
SUMMARY_CHARS = 80

BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
# 摘要开头常常已经带了日期，卡片里再写一遍很啰嗦
LEADING_DATE = re.compile(r"^(20\d{2}\s*[-年]\s*\d{1,2}\s*[-月]\s*\d{1,2}\s*日?[，,:：]?\s*)")
# 主题归一：这些后缀不改变场景含义，合并时去掉
TOPIC_SUFFIXES = ("相关的日常", "相关", "日常", "小记", "的事", "的事情")

# 2026-11-04：两层结构（真缺口）。场景卡原来是平铺的 15 张，
# 现在归到 4 个大类下面——大类是固定的，不让模型自由生长，避免"吃饭/吃东西/美食"这种碎片。
CATEGORIES = [
    ("生活日常", ("吃", "饭", "睡", "奶茶", "咖啡", "洗澡", "起床", "饿", "渴", "天气",
                  "作业", "房间", "衣", "生病", "药", "医院", "床", "水果", "零食")),
    ("关系互动", ("你", "撒娇", "抱", "亲", "关心", "打招呼", "陪", "视频", "聊天",
                  "晚安", "夸", "想我", "粘", "一起", "抱抱")),
    ("情绪心情", ("开心", "难过", "哭", "生气", "吃醋", "孤独", "委屈", "害怕", "焦虑",
                  "梦", "心情", "幸福", "满足", "低落")),
    ("事件经历", ("军训", "考试", "期中", "出门", "生日", "旅游", "第一次", "毕业",
                  "上课", "面试", "搬家", "节日")),
]
FALLBACK_CATEGORY = "其他"


def classify_category(topic):
    """把场景名归到 4 个大类里（先匹配先得）。"""
    name = str(topic)
    for cat, words in CATEGORIES:
        for w in words:
            if w in name:
                return cat
    return FALLBACK_CATEGORY


def build_tree(cards):
    """大 → 场景 的两层结构，顺便统计每层有多少条记忆。"""
    tree = {}
    for card in cards:
        cat = classify_category(card["topic"])
        tree.setdefault(cat, []).append(card)
    ordered = {}
    for cat, _ in CATEGORIES:
        if cat in tree:
            ordered[cat] = sorted(tree[cat], key=lambda c: -c["count"])
    if FALLBACK_CATEGORY in tree:
        ordered[FALLBACK_CATEGORY] = sorted(tree[FALLBACK_CATEGORY], key=lambda c: -c["count"])
    return ordered


def render_tree_md(tree):
    total = sum(len(v) for v in tree.values())
    lines = ["# 记忆场景树", "", "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
             "共 %d 个场景，归在 %d 个大类下。" % (total, len(tree)), ""]
    for cat, cards in tree.items():
        n = sum(c["count"] for c in cards)
        lines.append("## %s（%d 个场景 / %d 条记忆）" % (cat, len(cards), n))
        lines.append("")
        for c in cards:
            lines.append("- **%s** — %d 条，%s ~ %s，均分 %.2f → `scenes/%s`"
                         % (c["topic"], c["count"], c["start"], c["end"], c["importance"], c["file"]))
        lines.append("")
    return "\n".join(lines)


def log(msg):
    print(msg, flush=True)


def day(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return "?"


def load_memories():
    import sqlite3

    con = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True, timeout=3.0)
    try:
        rows = con.execute(
            "select id, text, metadata, created_at from documents"
        ).fetchall()
    finally:
        con.close()

    items = []
    for doc_id, text, meta, created in rows:
        try:
            m = json.loads(meta or "{}")
        except Exception:  # noqa: BLE001
            m = {}
        topics = [str(t).strip() for t in (m.get("topics") or []) if str(t).strip()]
        if not topics:
            continue
        summary = (
            m.get("persona_summary")
            or m.get("canonical_summary")
            or str(text or "")
        ).strip()
        summary = " ".join(summary.split())
        summary = LEADING_DATE.sub("", summary)
        if len(summary) > SUMMARY_CHARS:
            summary = summary[:SUMMARY_CHARS].rstrip() + "…"
        items.append(
            {
                "id": doc_id,
                "topics": topics,
                "ts": float(m.get("create_time") or 0) or 0.0,
                "importance": float(m.get("importance") or 0.5),
                "summary": summary,
                "source": str(m.get("source") or ""),
            }
        )
    return items


def normalize_topic(topic):
    """把"日常打招呼/打招呼"这类同义主题并到一起。"""
    name = str(topic).strip()
    for suffix in TOPIC_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            name = name[: -len(suffix)]
            break
    return name.strip() or str(topic).strip()


def build_cards(items):
    by_topic = defaultdict(list)
    for it in items:
        seen = set()
        for topic in it["topics"]:
            key = normalize_topic(topic)
            if key in seen:      # 同一条记忆的"吃饭"和"吃饭日常"只算一次
                continue
            seen.add(key)
            by_topic[key].append(it)

    cards = []
    for topic, group in by_topic.items():
        group.sort(key=lambda x: x["ts"])
        # 按 WINDOW_DAYS 切段
        segments, current = [], []
        for it in group:
            if current and it["ts"] - current[0]["ts"] > WINDOW_DAYS * 86400:
                segments.append(current)
                current = []
            current.append(it)
        if current:
            segments.append(current)

        for seg in segments:
            if len(seg) < MIN_MEMORIES:
                continue
            cards.append(
                {
                    "topic": topic,
                    "file": BAD_CHARS.sub("_", topic)[:40] + ".md",
                    "count": len(seg),
                    "start": day(seg[0]["ts"]),
                    "end": day(seg[-1]["ts"]),
                    "importance": sum(x["importance"] for x in seg) / len(seg),
                    "items": seg,
                }
            )

    cards.sort(key=lambda c: (-c["count"], -c["importance"]))
    return cards[:MAX_CARDS]


def render(card):
    lines = [
        "# 场景：%s" % card["topic"],
        "",
        "- 记忆条数：%d" % card["count"],
        "- 时间范围：%s ~ %s" % (card["start"], card["end"]),
        "- 平均重要性：%.2f" % card["importance"],
        "",
        "## 要点",
        "",
    ]
    for it in sorted(card["items"], key=lambda x: -x["importance"])[:6]:
        src = ("（%s）" % it["source"]) if it["source"] else ""
        lines.append("- %s %s%s [#%d]" % (day(it["ts"]), it["summary"], src, it["id"]))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    items = load_memories()
    cards = build_cards(items)
    log("读入 %d 条带主题的记忆，生成 %d 张场景卡" % (len(items), len(cards)))

    if args.dry_run:
        shown = cards[: args.limit] if args.limit else cards[:3]
        for i, card in enumerate(shown, 1):
            log("\n===== 卡片 %d/%d =====" % (i, len(cards)))
            log(render(card))
        return 0

    os.makedirs(SCENES, exist_ok=True)
    index = []
    for card in cards:
        path = os.path.join(SCENES, card["file"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(card))
        index.append(
            {
                "topic": card["topic"],
                "file": card["file"],
                "count": card["count"],
                "start": card["start"],
                "end": card["end"],
                "importance": round(card["importance"], 3),
                "ids": [it["id"] for it in card["items"]],
            }
        )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "memories": len(items),
        "cards": index,
    }

    # 2026-11-04：两层结构（大类 → 场景），给"渐进披露"留接口。
    tree = build_tree(cards)
    payload["tree"] = [
        {
            "category": cat,
            "scenes": [{"topic": c["topic"], "file": c["file"], "count": c["count"]} for c in cs],
            "memories": sum(c["count"] for c in cs),
        }
        for cat, cs in tree.items()
    ]
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "TREE.md"), "w", encoding="utf-8") as f:
        f.write(render_tree_md(tree))

    log("已写入 %d 张卡片 → %s" % (len(index), SCENES))
    log("两层结构：%s" % " / ".join("%s %d" % (k, len(v)) for k, v in tree.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
