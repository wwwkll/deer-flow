import sqlite3
import json
import os

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\checkpoints.db"
print(f"DB file size: {os.path.getsize(db_path) / 1024 / 1024:.2f} MB")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"\nTables: {tables}")

for table in tables:
    cur.execute(f"PRAGMA table_info([{table}])")
    cols = [r[1] for r in cur.fetchall()]
    cur.execute(f"SELECT COUNT(*) FROM [{table}]")
    count = cur.fetchone()[0]
    print(f"\n=== {table} ({count} rows) ===")
    print(f"  Columns: {cols}")

    if count > 0 and table == "checkpoints":
        cur.execute(f"SELECT thread_id, checkpoint_id, parent_checkpoint_id, metadata FROM [{table}] ORDER BY rowid DESC LIMIT 3")
        rows = cur.fetchall()
        for row in rows:
            tid, cid, parent_cid, meta_json = row
            meta = json.loads(meta_json) if meta_json else {}
            print(f"  thread_id={tid[:16]}... checkpoint_id={cid[:16]}... parent={parent_cid[:16] if parent_cid else 'None'}... source={meta.get('source')} step={meta.get('step')}")

    if count > 0 and table == "writes":
        cur.execute(f"SELECT thread_id, checkpoint_id, task_id, idx, channel, type, value FROM [{table}] LIMIT 3")
        rows = cur.fetchall()
        for row in rows:
            tid, cid, task_id, idx, channel, type_, value = row
            value_preview = value[:100] if value else "None"
            print(f"  thread_id={tid[:16]}... channel={channel} type={type_} value_preview={value_preview}...")

cur.execute("""
    SELECT thread_id, COUNT(*) as cnt,
           SUM(LENGTH(COALESCE(blob, x''))) as blob_bytes
    FROM checkpoints
    GROUP BY thread_id
    ORDER BY blob_bytes DESC
    LIMIT 10
""")
print("\n=== Top 10 threads by blob size ===")
for row in cur.fetchall():
    tid, cnt, blob_bytes = row
    print(f"  {tid[:16]}... {cnt} checkpoints, {blob_bytes / 1024:.1f} KB blob data")

cur.execute("SELECT SUM(LENGTH(COALESCE(blob, x''))) FROM checkpoints")
total_blob = cur.fetchone()[0]
print(f"\nTotal checkpoint blob data: {total_blob / 1024 / 1024:.2f} MB")

cur.execute("SELECT SUM(LENGTH(COALESCE(blob, x''))) FROM writes")
total_writes_blob = cur.fetchone()[0]
print(f"Total writes blob data: {total_writes_blob / 1024 / 1024:.2f} MB")

conn.close()
