"""只读查看TA最近写入的记忆条目。

用法: python peek_memory.py [条数]
"""
import os
import sqlite3
import sys

DB = r"D:\你的数据目录\livingmemory\livingmemory.db"


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(documents)")]
    print("documents 字段:", ", ".join(cols))
    order = "created_at" if "created_at" in cols else ("timestamp" if "timestamp" in cols else "rowid")
    rows = list(cur.execute(f"select * from documents order by {order} desc limit {limit}"))
    print(f"\n最近 {len(rows)} 条记忆（按 {order} 倒序）:\n")
    for r in rows:
        d = dict(r)
        imp = d.get("importance")
        src = d.get("source") or d.get("metadata") or ""
        ts = d.get(order)
        text = (d.get("content") or d.get("text") or d.get("summary") or "").replace("\n", " ")
        print(f"[id={d.get('id')}] t={ts} imp={imp} src={src}")
        print(f"    {text[:240]}")
    print("\n--- 按重要性排序（前 10，重要性存在 metadata JSON 里）---")
    ranked = []
    for r in cur.execute(f"select id, metadata, {order} as ts, text from documents"):
        d = dict(r)
        try:
            meta = json.loads(d.get("metadata") or "{}")
        except Exception:  # noqa: BLE001
            meta = {}
        ranked.append((meta.get("importance") or 0, d["id"], d["ts"], d.get("text") or ""))
    ranked.sort(reverse=True)
    for imp, did, ts, text in ranked[:10]:
        print(f"id={did} imp={imp} t={ts} :: {text.replace(chr(10), ' ')[:100]}")
    con.close()


if __name__ == "__main__":
    main()
