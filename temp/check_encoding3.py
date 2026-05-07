"""Script to simulate the actual backend browse_directory response and check for encoding issues."""
import sys
import json
from pathlib import Path
from pydantic import BaseModel

class DirectoryEntry(BaseModel):
    name: str
    path: str
    isDirectory: bool

class BrowseResponse(BaseModel):
    currentPath: str
    parentPath: str
    entries: list[DirectoryEntry]

def test_directory(dir_path, virtual_path):
    p = Path(dir_path)
    if not p.exists():
        print(f"SKIP (not exists): {dir_path}")
        return
    
    print(f"\n--- Testing: {virtual_path} ---")
    entries = []
    for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append(DirectoryEntry(
                name=item.name,
                path=f"{virtual_path}/{item.name}",
                isDirectory=True,
            ))
        elif item.is_file():
            if item.suffix.lower() in {".md", ".txt", ".json", ".log"}:
                entries.append(DirectoryEntry(
                    name=item.name,
                    path=f"{virtual_path}/{item.name}",
                    isDirectory=False,
                ))
    
    response = BrowseResponse(
        currentPath=virtual_path,
        parentPath=str(Path(virtual_path).parent),
        entries=entries,
    )
    
    # Test Pydantic serialization
    try:
        data = response.model_dump()
        json_str = json.dumps(data, ensure_ascii=False)
        json_bytes = json_str.encode("utf-8")
        print(f"  Entries: {len(entries)}, JSON bytes: {len(json_bytes)}")
        print(f"  Pydantic + JSON: OK")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        for i, entry in enumerate(entries):
            try:
                json.dumps(entry.model_dump(), ensure_ascii=False).encode("utf-8")
            except Exception as e2:
                print(f"    BAD ENTRY #{i}: {entry.name} - {e2}")

# Test all directories
test_cases = [
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝", "/mnt/shared-data/book/女帅回归：从赐死到女帝"),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\01-规划", "/mnt/shared-data/book/女帅回归：从赐死到女帝/01-规划"),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\01-规划\chapters", "/mnt/shared-data/book/女帅回归：从赐死到女帝/01-规划/chapters"),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\02-正文\第01-05章", "/mnt/shared-data/book/女帅回归：从赐死到女帝/02-正文/第01-05章"),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\02-正文\第01-05章\_task", "/mnt/shared-data/book/女帅回归：从赐死到女帝/02-正文/第01-05章/_task"),
]

for actual, virtual in test_cases:
    test_directory(actual, virtual)
