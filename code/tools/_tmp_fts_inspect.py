import sqlite3
p = r"D:\你的数据目录\livingmemory\livingmemory.db"
c = sqlite3.connect(p)
for row in c.execute("select name, sql from sqlite_master where name in ('documents','documents_fts','documents_fts_config','documents_fts_data')"):
    print(row)
print("orphan ids sample:")
for row in c.execute("select f.rowid from documents_fts f left join documents d on d.rowid=f.rowid where d.rowid is null limit 20"):
    print(row)
