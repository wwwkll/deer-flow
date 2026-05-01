import sqlite3

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\global_variables.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM global_variables WHERE thread_id = ?", ("2e043892-5491-42fc-b99f-b03ffaf26f92",))
rows = cur.fetchall()
print(f"Found {len(rows)} rows for thread 2e043892-5491-42fc-b99f-b03ffaf26f92:")
for r in rows:
    print(dict(r))
conn.close()
