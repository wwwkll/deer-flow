import sqlite3
import sys
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")
from deerflow.config.paths import get_paths

db_path = get_paths().base_dir / "global_variables.db"
print(f"DB path: {db_path}")

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT thread_id, key, value, description FROM global_variables WHERE key = 'novel_toc'")
for row in cursor.fetchall():
    print(f"thread_id={row['thread_id']!r}")
    print(f"  key={row['key']!r}")
    print(f"  value={row['value']!r}")
    print(f"  len={len(row['value'])}")
    print(f"  desc={row['description']!r}")
    print()
conn.close()
