# -*- coding: utf-8 -*-
"""清理完全重复的短记忆：完全相同、且长度<80 字的，只留最新一条。

保护措施：
  · 先做整库备份（logs/backup-memory-before-dedupe-*.db）
  · 被删的行导出到 logs/deleted_duplicates_*.json，可回滚
  · 只动短句（生活流水），长总结不动
"""
from __future__ import annotations

import json
from contextlib import closing
import os
import sqlite3
import time
import sys

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from memory_ledger import retire_many as _retire_ledger
except Exception:  # 账本工具不在时不阻断去重
    _retire_ledger = None

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    if (_parent / "i18n.py").is_file():
        sys.path.insert(0, str(_parent))
        break
sys.path.insert(0, r"D:\你的数据目录")
from i18n import t

DB = (r"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>"
      r"\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db")
LOGS = r"D:\你的数据目录\logs"
MAXLEN = 80


def main() -> None:
    os.makedirs(LOGS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = os.path.join(LOGS, "backup-memory-before-dedupe-%s.db" % ts)
    con = sqlite3.connect(DB)
    try:
        with closing(sqlite3.connect(bak)) as destination:
            con.backup(destination)
            if destination.execute("pragma quick_check").fetchone()[0] != "ok":
                raise RuntimeError(t("memory.backup_invalid"))
    finally:
        con.close()
    print(t("memory.backup_size", path=bak, size=round(os.path.getsize(bak) / 1e6, 1)))

    con = sqlite3.connect(DB)
    cur = con.cursor()
    before = cur.execute("select count(*) from documents").fetchone()[0]
    rows = cur.execute("select text, count(*) c from documents group by text having c>1").fetchall()
    removed = []
    for text, cnt in rows:
        if not text or len(text) >= MAXLEN:
            continue
        ids = [r[0] for r in cur.execute(
            "select id from documents where text=? order by id desc", (text,)).fetchall()]
        keep, drop = ids[0], ids[1:]
        for i in drop:
            removed.append({"id": i, "text": text})
            cur.execute("delete from documents where id=?", (i,))
    con.commit()
    after = cur.execute("select count(*) from documents").fetchone()[0]
    cur.execute("vacuum")
    con.close()

    out = os.path.join(LOGS, "deleted_duplicates_%s.json" % ts)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(removed, f, ensure_ascii=False, indent=2)
    print(t("memory.deduped", count=len(removed), before=before, after=after))
    print(t("memory.exported", path=out))
    if _retire_ledger is not None and removed:
        try:
            n = _retire_ledger(
                [r["id"] for r in removed],
                reason="去重合并（完全相同短句）",
                by="dedupe_memories",
            )
            print(t("memory.ledger_registered", count=n))
        except Exception as exc:  # noqa: BLE001
            print(t("memory.ledger_failed", error=exc))


if __name__ == "__main__":
    main()
