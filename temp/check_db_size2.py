import sqlite3
import json
import os

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\checkpoints.db"
print(f"DB file size: {os.path.getsize(db_path) / 1024 / 1024:.2f} MB")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""
    SELECT thread_id, COUNT(*) as cnt,
           SUM(LENGTH(COALESCE(checkpoint, ''))) as ckpt_bytes,
           SUM(LENGTH(COALESCE(metadata, ''))) as meta_bytes
    FROM checkpoints
    GROUP BY thread_id
    ORDER BY ckpt_bytes DESC
    LIMIT 10
""")
print("\n=== Top 10 threads by checkpoint data size ===")
for tid, cnt, ckpt_bytes, meta_bytes in cur.fetchall():
    print(f"  {tid[:16]}... {cnt} checkpoints, checkpoint_data={ckpt_bytes / 1024:.1f} KB, metadata={meta_bytes / 1024:.1f} KB")

cur.execute("SELECT SUM(LENGTH(COALESCE(checkpoint, ''))) FROM checkpoints")
total_ckpt = cur.fetchone()[0]
cur.execute("SELECT SUM(LENGTH(COALESCE(metadata, ''))) FROM checkpoints")
total_meta = cur.fetchone()[0]
cur.execute("SELECT SUM(LENGTH(COALESCE(value, ''))) FROM writes")
total_writes = cur.fetchone()[0]

print(f"\n=== Total data breakdown ===")
print(f"  checkpoints.checkpoint column: {total_ckpt / 1024 / 1024:.2f} MB")
print(f"  checkpoints.metadata column:   {total_meta / 1024 / 1024:.2f} MB")
print(f"  writes.value column:           {total_writes / 1024 / 1024:.2f} MB")
print(f"  DB file on disk:               {os.path.getsize(db_path) / 1024 / 1024:.2f} MB")

cur.execute("SELECT COUNT(DISTINCT thread_id) FROM checkpoints")
thread_count = cur.fetchone()[0]
print(f"\n=== Summary ===")
print(f"  Total threads: {thread_count}")
print(f"  Total checkpoints: 13256")
print(f"  Total writes: 20104")
print(f"  Avg checkpoints per thread: {13256 / thread_count:.0f}")

conn.close()
