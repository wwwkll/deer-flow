import sqlite3
import os

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\checkpoints.db"
print(f"DB size: {os.path.getsize(db_path) / 1024:.1f} KB")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"Tables: {tables}")

for table in tables:
    cur.execute(f"SELECT COUNT(*) FROM [{table}]")
    count = cur.fetchone()[0]
    print(f"  {table}: {count} rows")

for table in tables:
    cur.execute(f"PRAGMA table_info([{table}])")
    cols = [r[1] for r in cur.fetchall()]
    if "thread_id" in cols:
        cur.execute(f"SELECT DISTINCT thread_id FROM [{table}]")
        thread_ids = [r[0] for r in cur.fetchall()]
        print(f"\n  {table} thread_ids ({len(thread_ids)}):")
        for tid in thread_ids:
            cur.execute(f"SELECT COUNT(*) FROM [{table}] WHERE thread_id=?", (tid,))
            cnt = cur.fetchone()[0]
            print(f"    {tid}: {cnt} rows")

conn.close()
