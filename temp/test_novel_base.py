import sqlite3
import sys
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

from deerflow.config.paths import get_paths

db_path = get_paths().base_dir / "global_variables.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT thread_id, key, value FROM global_variables WHERE key = 'novel_toc' AND value LIKE '%副本%'")
rows = cursor.fetchall()
if rows:
    test_thread_id = rows[0]['thread_id']
    test_value = rows[0]['value']
    print(f"测试用 thread_id: {test_thread_id}")
    print(f"数据库中的值: {test_value}")
else:
    print("没有找到包含'副本'的记录")
    conn.close()
    sys.exit(1)
conn.close()

from deerflow.workflows.helpers import get_novel_base, get_workdir

print("\n=== 测试 get_novel_base() ===")

result1 = get_novel_base(thread_id=test_thread_id)
print(f"get_novel_base(thread_id={test_thread_id!r})")
print(f"  结果: {result1}")
print(f"  正确: {result1 == test_value}")

result2 = get_novel_base(thread_id=None)
print(f"\nget_novel_base(thread_id=None)")
print(f"  结果: {result2}")

result3 = get_novel_base(thread_id="nonexistent-id")
print(f"\nget_novel_base(thread_id='nonexistent-id')")
print(f"  结果: {result3}")

print("\n=== 测试 get_workdir() ===")
result4 = get_workdir(thread_id=test_thread_id)
print(f"get_workdir(thread_id={test_thread_id!r})")
print(f"  结果: {result4}")

print("\n=== 测试路径拼接 ===")
if result1:
    print(f"novel_base: {result1}")
    print(f"  02-正文: {result1}/02-正文")
    print(f"  card.json: {result1}/card.json")
    print(f"  03-状态: {result1}/03-状态")
