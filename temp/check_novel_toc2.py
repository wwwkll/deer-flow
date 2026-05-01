import sqlite3
import sys
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")
from deerflow.config.paths import get_paths

db_path = get_paths().base_dir / "global_variables.db"
print(f"DB path: {db_path}")

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT thread_id, key, value FROM global_variables WHERE key = 'novel_toc'")
rows = cursor.fetchall()

print(f"总记录数: {len(rows)}\n")

project_level = [r for r in rows if r['thread_id'] is None]
thread_level = [r for r in rows if r['thread_id'] is not None]

print(f"=== 项目级 (thread_id IS NULL): {len(project_level)} 条 ===")
for r in project_level:
    print(f"  value={r['value']!r}")

print(f"\n=== 对话级 (thread_id 有值): {len(thread_level)} 条 ===")
for r in thread_level:
    print(f"  thread_id={r['thread_id']!r}, value={r['value']!r}")

conn.close()
