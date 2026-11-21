# -*- coding: utf-8 -*-
"""快照覆盖率体检：最近 24 小时新写的记忆，多少带了 mood_snapshot（只报告，不改库）。
用法：python check_snapshot_coverage.py
"""
import json, sqlite3, sys, time

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"


def main():
    con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 86400))
    rows = con.execute(
        "SELECT id, metadata FROM documents WHERE created_at >= ? "
        "AND (json_valid(metadata)=0 OR coalesce(json_extract(metadata,'$.status'),'active')='active')",
        (since,)).fetchall()
    con.close()
    total = len(rows)
    have = sum(1 for _, m in rows if "mood_snapshot" in (m or ""))
    selftest = sum(1 for _, m in rows if '"source": "snapshot_selftest"' in (m or ""))
    print("近 24h 新增记忆 %d 条，带 mood_snapshot %d 条（%.0f%%），其中自检 %d 条"
          % (total, have, (have * 100.0 / total) if total else 0, selftest))
    print("RESULT:", "OK" if total == 0 or have >= total - 1 else "GAP")
    sys.exit(0 if total == 0 or have >= total - 1 else 1)


if __name__ == "__main__":
    main()
