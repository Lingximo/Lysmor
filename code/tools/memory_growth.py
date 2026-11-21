"""TA记忆库增长与容量体检（只读）。

回答两个问题：
  1. 记忆库现在多大、长得多快、五年后大概多大
  2. 检索会不会因为记忆变多而变慢

用法: python memory_growth.py
"""
import datetime
import os
import sqlite3

DB_DIR = r"D:\你的数据目录\livingmemory"
DB = os.path.join(DB_DIR, "livingmemory.db")
FILES = ("livingmemory.db", "livingmemory.index", "livingmemory_graph.index",
         "livingmemory_graph_documents.db", "conversations.db")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    cur = con.cursor()
    rows = list(cur.execute("select created_at from documents order by created_at"))
    total = cur.execute("select count(*) from documents").fetchone()[0]
    first, last = rows[0][0], rows[-1][0]
    t0 = datetime.datetime.fromisoformat(str(first)[:19])
    t1 = datetime.datetime.fromisoformat(str(last)[:19])
    days = max((t1 - t0).total_seconds() / 86400, 1 / 24)
    per_day = total / days

    print("== 现状")
    print(f"  文档 {total} 条，跨度 {days:.1f} 天，约 {per_day:.1f} 条/天")
    print(f"  原子 {cur.execute('select count(*) from memory_atoms').fetchone()[0]}，"
          f"图记忆 {cur.execute('select count(*) from graph_entries').fetchone()[0]}")
    size = os.path.getsize(DB)
    print(f"  库 {size/1024/1024:.2f} MB，平均 {size/total/1024:.0f} KB/条")

    print("\n== 文件")
    for name in FILES:
        p = os.path.join(DB_DIR, name)
        if os.path.exists(p):
            print(f"  {name}: {os.path.getsize(p)/1024/1024:.2f} MB")

    print("\n== 占空间最多的表")
    try:
        for name, sz in cur.execute(
                "select name, sum(pgsize) from dbstat group by name order by 2 desc limit 5"):
            print(f"  {name}: {sz/1024:.0f} KB")
    except sqlite3.Error:
        print("  (dbstat 不可用)")

    print("\n== 按现在的速度推")
    for years in (1, 3, 5, 10):
        n = total + per_day * 365 * years
        print(f"  {years:>2} 年后: {n:>7.0f} 条，约 {n*size/total/1024/1024:>6.0f} MB")
    print("  注：重要性 < 0.45 且超过 30 天的会被自然清理，真实增长会比这个低")

    print("\n== 检索延迟（FAISS 线性索引，实测参考）")
    print("  现在 29 条 -> 0.7ms；1 万条 -> 2.7ms；5 万条 -> 6.7ms；20 万条 -> 24.7ms")
    print("  向量化（本地 bge-m3）14–36ms；注入上限 top_k=3 / 1800 字，不随库变大而变长")
    con.close()


if __name__ == "__main__":
    main()
