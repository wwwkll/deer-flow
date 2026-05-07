import sys
print(f"Python filesystem encoding: {sys.getfilesystemencoding()}")
from pathlib import Path

p = Path(r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\01-规划\chapters")
for item in p.iterdir():
    try:
        name_utf8 = item.name.encode("utf-8")
        name_utf8.decode("utf-8")
        print(f"OK: {item.name} ({len(name_utf8)} bytes)")
    except UnicodeDecodeError as e:
        print(f"FAIL: {item.name} - {e}")
    except UnicodeEncodeError as e:
        print(f"FAIL ENCODE: {item.name} - {e}")
