import sqlite3
import sys
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")
from deerflow.config.paths import get_paths

db_path = get_paths().base_dir / "global_variables.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=== 所有包含 '仙生' 的 novel_toc 记录 ===")
cursor.execute("SELECT thread_id, key, value FROM global_variables WHERE key = 'novel_toc' AND value LIKE '%仙生%'")
for row in cursor.fetchall():
    tid = row['thread_id'] or 'NULL(项目级)'
    print(f"  thread_id={tid}")
    print(f"    value={row['value']!r}")
    print()

conn.close()
