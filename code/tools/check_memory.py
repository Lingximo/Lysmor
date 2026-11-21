"""TA记忆库健康检查（只读）。

用法: python D:\\你的数据目录\\tools\\check_memory.py
不写入、不修改任何数据。
"""
import glob
import os
import sqlite3
import sys

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
BACKUP_DIR = r"D:\你的数据目录\livingmemory\backups"


def table_names(cur):
    return [r[0] for r in cur.execute(
        "select name from sqlite_master where type='table' order by name")]


def counts(cur):
    out = {}
    for t in table_names(cur):
        try:
            out[t] = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            out[t] = f"ERR {exc}"
    return out


def report(path):
    print(f"== {path}")
    if not os.path.exists(path):
        print("   文件不存在")
        return None
    print(f"   大小: {os.path.getsize(path)} bytes")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = con.cursor()
    integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"   integrity_check: {integrity}")
    c = counts(cur)
    for t in ("documents", "documents_fts", "atoms", "graph_entries", "graph_nodes",
              "graph_edges", "vectors", "memory_atoms"):
        if t in c:
            print(f"   {t}: {c[t]}")
    # 孤儿检查（表存在才查）
    def q(sql):
        try:
            return cur.execute(sql).fetchone()[0]
        except Exception:  # noqa: BLE001
            return None
    orphan_atoms = q("select count(*) from atoms where document_id not in (select id from documents)")
    if orphan_atoms is not None:
        print(f"   孤儿 atoms: {orphan_atoms}")
    orphan_fts = q("select count(*) from documents_fts where rowid not in (select id from documents)")
    if orphan_fts is not None:
        print(f"   孤儿 fts: {orphan_fts}")
    hi = q("select count(*) from documents where importance >= 0.99")
    if hi is not None:
        print(f"   重要性>=0.99 文档: {hi}")
    con.close()
    return c


def main():
    main_counts = report(DB)
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db")))
    print(f"\n本地备份数量: {len(backups)}")
    for b in backups:
        report(b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
