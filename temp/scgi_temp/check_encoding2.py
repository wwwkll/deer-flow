import sys
import json
from pathlib import Path

print(f"Python filesystem encoding: {sys.getfilesystemencoding()}")
print(f"Default encoding: {sys.getdefaultencoding()}")

# 模拟后端的 browse_directory 逻辑
dirs_to_check = [
    r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\01-规划\chapters",
    r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\02-正文",
    r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\00-世界观",
    r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\03-状态",
]

for dir_path in dirs_to_check:
    p = Path(dir_path)
    if not p.exists():
        print(f"\nSKIP (not exists): {dir_path}")
        continue
    
    print(f"\n--- Testing: {dir_path} ---")
    entries = []
    for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entry = {"name": item.name, "path": f"/mnt/test/{item.name}", "isDirectory": True}
        elif item.is_file():
            entry = {"name": item.name, "path": f"/mnt/test/{item.name}", "isDirectory": False}
        entries.append(entry)
    
    # 模拟 Pydantic/JSON 序列化
    try:
        result = json.dumps(entries, ensure_ascii=False)
        result_bytes = result.encode("utf-8")
        print(f"  Entries: {len(entries)}, JSON bytes: {len(result_bytes)}")
        print(f"  OK")
    except Exception as e:
        print(f"  FAIL: {e}")
        for entry in entries:
            try:
                json.dumps(entry, ensure_ascii=False).encode("utf-8")
            except Exception as e2:
                print(f"    BAD ENTRY: {entry} - {e2}")
