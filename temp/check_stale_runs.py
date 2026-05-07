import sqlite3
import json

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\checkpoints.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT thread_id, checkpoint_id, metadata FROM checkpoints ORDER BY rowid DESC LIMIT 10")
rows = cur.fetchall()
print("=== Latest 10 checkpoints ===")
for tid, cid, meta_json in rows:
    meta = json.loads(meta_json) if meta_json else {}
    source = meta.get("source", "?")
    step = meta.get("step", "?")
    print(f"  thread={tid[:12]}... checkpoint={cid[:12]}... source={source} step={step}")

print("\n=== Checking for stale/incomplete runs ===")
cur.execute("""
    SELECT thread_id, checkpoint_id, metadata
    FROM checkpoints
    WHERE metadata LIKE '%"source": "loop"%'
    ORDER BY rowid DESC
    LIMIT 5
""")
rows = cur.fetchall()
for tid, cid, meta_json in rows:
    meta = json.loads(meta_json) if meta_json else {}
    print(f"  thread={tid[:12]}... checkpoint={cid[:12]}... source={meta.get('source')} step={meta.get('step')}")

conn.close()
