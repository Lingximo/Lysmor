import sqlite3
p = r"D:\你的数据目录\livingmemory\livingmemory.db"
c = sqlite3.connect(p)
c.execute("""DELETE FROM documents_fts WHERE rowid IN (
    SELECT f.rowid FROM documents_fts f
    LEFT JOIN documents d ON d.rowid=f.rowid
    WHERE d.rowid IS NULL
)""")
c.commit()
print("docs", c.execute("select count(*) from documents").fetchone()[0])
print("fts", c.execute("select count(*) from documents_fts").fetchone()[0])
print("integrity", c.execute("pragma integrity_check").fetchone()[0])
print("orphans", c.execute("""SELECT count(*) FROM documents_fts f
LEFT JOIN documents d ON d.rowid=f.rowid WHERE d.rowid IS NULL""").fetchone()[0])
