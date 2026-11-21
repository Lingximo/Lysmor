# -*- coding: utf-8 -*-
"""记忆一致性体检：各通道写进来的、读出去的，是不是同一批。

用法（在 D:\\你的数据目录\\tools 下）：
    .\\py.cmd check_memory_sync.py

检查：
  1) 库的总量 / active / 归档
  2) 视频端两条读路是否过滤归档（这是最典型的"QQ 想不起、视频说得出"）
  3) 每个通道最近有没有在写
  4) 我自己给的权重有没有被改写
  5) 待写队列有没有积压/丢件
"""
import json
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
PEND = r"D:\你的数据目录\video\pending_memories.json"
STAT = r"D:\你的数据目录\video\memory_sync_status.json"
ACTIVE = ("(json_valid(metadata) = 0 "
          " OR coalesce(json_extract(metadata, '$.status'), 'active') = 'active')")
fails = 0


def check(name, ok, extra=""):
    global fails
    if not ok:
        fails += 1
    print("  %s %-44s %s" % ("✅" if ok else "❌", name, extra))


con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
total = con.execute("select count(*) from documents").fetchone()[0]
active = con.execute("select count(*) from documents where " + ACTIVE).fetchone()[0]
rows = con.execute("SELECT id, text, metadata FROM documents ORDER BY id DESC").fetchall()

print("=== 1) 库 ===")
print("  总 %d，active %d，已归档 %d" % (total, active, total - active))

print("\n=== 1b) 两条读路只认 active ===")
# 源码级检查：这两处是"不走 livingmemory 钩子"的直连读路，一旦漏掉归档过滤，
# 就会出现"QQ 那头想不起、视频/空间/主动消息却翻出来说"的错位。
# 2026-11-05：video/server.py 一直有，tools/recall.py 漏了，已补上（灾后复活 §44）。
READERS = (
    ("空间/主动消息 recall.py 过滤归档", r"D:\你的数据目录\tools\recall.py"),
    ("视频/陪玩 server.py 过滤归档", r"D:\你的数据目录\video\server.py"),
)
for name, path in READERS:
    try:
        src = open(path, encoding="utf-8").read()
        ok = ("$.status" in src) and ("active" in src)
    except Exception as exc:
        ok = False
        name = name + "（读源码失败 %s）" % str(exc)[:30]
    check(name, ok, "")

print("\n=== 2) 各通道 ===")
agg = defaultdict(list)
for (i, t, meta) in rows:
    d = json.loads(meta or "{}")
    agg[d.get("source") or "(无来源-QQ反思)"].append((i, d.get("importance"), t))
for src in ("food", "water", "sleep", "toilet", "taste", "video_call", "companion"):
    items = agg.get(src) or []
    last = max(items) if items else (0, 0, "")
    check("通道 %-10s" % src, bool(items),
          "%d 条，最新 #%s「%s」" % (len(items), last[0], (last[2] or "")[:14]))

print("\n=== 3) 权重没被改写 ===")
# 区间取"记忆节律允许的真实范围"，不是建卡那一刻的快照：
#   非保护区（<0.70）会被 memoryrhythm 衰减（地板 FLOOR=0.05），
#   也会被"想起"加固（每次 +REINFORCE 0.02，上限 REINFORCE_CAP=0.68）。
#   scar 在保护区（>=0.70）既不衰减也不加固，所以照旧卡 0.85~0.95。
# 2026-11-05：#91 由 0.60 被加固到 0.6163，旧上限 0.60 把正常加固报成了红；
# 数据本身没问题，改的是检查口径（见灾后复活 §43）。
EXPECT = {"food": (0.05, 0.68), "scar": (0.85, 0.95), "dream": (0.05, 0.68),
          "dream_place": (0.05, 0.68), "obsession": (0.05, 0.68)}
for src, (lo, hi) in EXPECT.items():
    vals = [float(v) for _, v, _ in (agg.get(src) or []) if v is not None]
    if not vals:
        print("  ⏭  %-12s 还没有样本" % src)
        continue
    check("%-12s 权重在 [%.2f, %.2f]" % (src, lo, hi),
          all(lo - 0.001 <= v <= hi + 0.001 for v in vals),
          str([round(v, 2) for v in vals]))

print("\n=== 4) 写队列 ===")
try:
    pend = json.load(open(PEND, encoding="utf-8"))
    stt = json.load(open(STAT, encoding="utf-8"))
    check("队列不积压", len(pend) == 0, "%d 条" % len(pend))
    check("没有丢件/失败", int(stt.get("dropped", 0)) == 0 and int(stt.get("failed", 0)) == 0,
          "dropped=%s failed=%s" % (stt.get("dropped"), stt.get("failed")))
    check("没有卡住的残留", int(stt.get("queue_after", 0)) == 0)
except Exception as exc:
    check("队列文件可读", False, str(exc)[:40])

print("\n=== 5) 元数据完整 ===")
bad = 0
for (_, _, meta) in rows:
    d = json.loads(meta or "{}")
    if d.get("create_time") is None or d.get("importance") is None:
        bad += 1
check("create_time / importance 齐全", bad == 0, "缺 %d 条" % bad)

print("\n%s" % ("全部通过 ✅" if fails == 0 else "有 %d 条没过 ❌" % fails))
sys.exit(0 if fails == 0 else 1)
