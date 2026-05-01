import sqlite3

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\global_variables.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

thread_id = "2e043892-5491-42fc-b99f-b03ffaf26f92"
cur.execute("SELECT * FROM global_variables WHERE thread_id = ?", (thread_id,))
rows = cur.fetchall()
if rows:
    print(f"Found {len(rows)} rows for thread {thread_id}:")
    for r in rows:
        print(dict(r))
else:
    print(f"No rows found for thread_id: {thread_id}")
    cur.execute("SELECT DISTINCT thread_id FROM global_variables LIMIT 20")
    tids = cur.fetchall()
    print("Available thread_ids:")
    for t in tids:
        print(f"  {t[0]}")

conn.close()
