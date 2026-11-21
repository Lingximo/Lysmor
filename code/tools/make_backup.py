"""为TA记忆库生成完整备份，验证通过后轮换旧备份（本地只保留一份）。

用法:
  python make_backup.py            # 备份 + 验证 + 轮换
  python make_backup.py --dry-run  # 只备份到临时名并验证，不轮换
"""
import glob
import os
import sqlite3
import sys
import time

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"
BACKUP_DIR = r"D:\你的数据目录\livingmemory\backups"
TABLES = ("documents", "documents_fts", "memory_atoms", "graph_entries",
          "graph_nodes", "graph_edges")


def snapshot(src, dst):
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    with out:
        con.backup(out)
    out.close()
    con.close()


def stats(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = con.cursor()
    integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {}
    for t in TABLES:
        try:
            counts[t] = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        except sqlite3.Error:
            counts[t] = None
    con.close()
    return integrity, counts


def main():
    dry = "--dry-run" in sys.argv
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tmp = os.path.join(BACKUP_DIR, f".tmp_snapshot_{stamp}.db")
    final = os.path.join(BACKUP_DIR, f"livingmemory_complete_{stamp}.db")

    print("源库:", DB)
    src_integrity, src_counts = stats(DB)
    print("源库 integrity:", src_integrity)
    print("源库统计:", src_counts)
    if src_integrity != "ok":
        print("源库完整性异常，拒绝继续。")
        return 2

    print("\n生成快照 ->", tmp)
    snapshot(DB, tmp)
    b_integrity, b_counts = stats(tmp)
    print("备份 integrity:", b_integrity)
    print("备份统计:", b_counts)
    print("大小:", os.path.getsize(tmp), "bytes")

    ok = b_integrity == "ok" and b_counts == src_counts
    if not ok:
        print("\n验证失败：备份与源库不一致，保留源库不动，临时文件留存以便排查。")
        return 3

    os.replace(tmp, final)
    for suffix in ("-wal", "-shm"):
        side = tmp + suffix
        if os.path.exists(side):
            os.remove(side)
    print("\n验证通过，新备份:", final)

    if dry:
        print("dry-run：不轮换旧备份。")
        return 0

    old = [p for p in sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db")))
           if os.path.abspath(p) != os.path.abspath(final)]
    for p in old:
        # 只删完整备份快照，不碰其它文件
        if os.path.basename(p).startswith("livingmemory_complete_"):
            print("移除旧备份:", p)
            os.remove(p)
            for suffix in ("-wal", "-shm"):
                side = p + suffix
                if os.path.exists(side):
                    os.remove(side)
                    print("移除:", side)
    print("\n完成。当前本地备份:")
    for p in sorted(glob.glob(os.path.join(BACKUP_DIR, "*.db"))):
        print("  ", p, os.path.getsize(p), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
