# -*- coding: utf-8 -*-
"""记忆库维护：检查点 / 重复统计 / 清理重复（默认只看不动）

用法：
    python tools\\memory_maintenance.py            # 体检 + 报告，不改数据
    python tools\\memory_maintenance.py --apply    # 真的清理重复（留最早一条）
    python tools\\memory_maintenance.py --checkpoint  # 只做 WAL 检查点

清理规则：
  · 只处理"文本完全相同"的重复记忆
  · 每组保留 created_at 最早的那条（最原始），其余删除
  · 同时删掉 graph_documents 里 source_memory_id 指向它们的行
  · 删前自动备份 db 到 logs\\backup-memory-<时间>.db
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
import sys

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from memory_ledger import retire_many as _retire_ledger
except Exception:  # 账本工具不在时不阻断去重
    _retire_ledger = None

PLUGIN_DATA = (r"C:\你的用户\.astrbot_launcher\instances"
               r"\<BOT_INSTANCE>\core\data\plugin_data"
               r"\astrbot_plugin_livingmemory")
DB = os.path.join(PLUGIN_DATA, "livingmemory.db")
GRAPH_DB = os.path.join(PLUGIN_DATA, "livingmemory_graph_documents.db")
LOG_DIR = r"D:\你的数据目录\logs"


def size(p):
    return os.path.getsize(p) / 1e6 if os.path.exists(p) else 0.0


def checkpoint(db):
    con = sqlite3.connect(db, timeout=20)
    try:
        con.execute("pragma wal_checkpoint(TRUNCATE)")
    finally:
        con.close()


def report(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = con.cursor()
    total = cur.execute("select count(*) from documents").fetchone()[0]
    dup_groups = cur.execute(
        "select count(*) from (select text from documents group by text having count(*)>1)"
    ).fetchone()[0]
    dup_rows = cur.execute(
        "select coalesce(sum(c-1),0) from (select count(*) c from documents group by text having c>1)"
    ).fetchone()[0]
    active = cur.execute(
        "select count(*) from documents where coalesce(json_extract(metadata,'$.status'),'active')='active'"
    ).fetchone()[0]
    print("记忆总数 %d（active %d）" % (total, active))
    print("重复文本 %d 组，多余 %d 条" % (dup_groups, dup_rows))
    rows = cur.execute(
        "select count(*), substr(text,1,36) from documents group by text "
        "having count(*)>1 order by count(*) desc limit 5"
    ).fetchall()
    for n, t in rows:
        print("  %2d× %s" % (n, t))
    con.close()
    return dup_groups, dup_rows


def apply(db, graph_db):
    os.makedirs(LOG_DIR, exist_ok=True)
    bak = os.path.join(LOG_DIR, "backup-memory-%s.db" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(db, bak)
    print("已备份:", bak)

    con = sqlite3.connect(db, timeout=30)
    cur = con.cursor()
    groups = cur.execute(
        "select text, group_concat(id) from documents group by text having count(*)>1"
    ).fetchall()
    removed = 0
    ids_to_drop = []
    for text, ids in groups:
        id_list = sorted(int(x) for x in str(ids).split(","))
        keep = id_list[0]
        drop = id_list[1:]
        if not drop:
            continue
        ids_to_drop.extend(drop)
        q = ",".join("?" * len(drop))
        cur.execute(f"delete from documents where id in ({q})", drop)
        try:
            cur.execute(f"delete from documents_fts where rowid in ({q})", drop)
        except Exception as exc:  # noqa: BLE001
            print("  FTS 删除失败（忽略）:", exc)
        removed += len(drop)
        print("  保留 #%d，删除 %s：%s" % (keep, drop, (text or "")[:40]))
    con.commit()
    con.close()
    print("主库删除 %d 条" % removed)
    if _retire_ledger is not None and ids_to_drop:
        try:
            n = _retire_ledger(
                ids_to_drop,
                reason="去重合并（完全相同文本）",
                by="memory_maintenance",
            )
            print("账本补登记: %d 条" % n)
        except Exception as exc:  # noqa: BLE001
            print("账本补登记失败（不影响去重）:", exc)

    if ids_to_drop and os.path.exists(graph_db):
        try:
            g = sqlite3.connect(graph_db, timeout=30)
            q = ",".join("?" * len(ids_to_drop))
            n = g.execute(
                f"delete from documents where json_extract(metadata,'$.source_memory_id') in ({q})",
                ids_to_drop,
            ).rowcount
            g.commit()
            g.close()
            print("图谱库删除 %d 条" % n)
        except Exception as exc:  # noqa: BLE001
            print("图谱库清理失败（不影响主库）:", exc)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--checkpoint", action="store_true")
    args = ap.parse_args()

    print("库：", DB)
    print("大小 %.1f MB，WAL %.1f MB" % (size(DB), size(DB + "-wal")))

    if args.checkpoint or not args.apply:
        before = size(DB + "-wal")
        checkpoint(DB)
        print("WAL 检查点：%.1f MB → %.1f MB" % (before, size(DB + "-wal")))

    if not args.apply:
        report(DB)
        print("\n（只检查。要清理重复请加 --apply，会先备份）")
        return

    apply(DB, GRAPH_DB)
    checkpoint(DB)
    report(DB)


if __name__ == "__main__":
    main()
