"""Find all files with non-UTF8 encoding in the shared data directory."""
import os

base_dir = r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book"

for root, dirs, files in os.walk(base_dir):
    for f in files:
        filepath = os.path.join(root, f)
        try:
            with open(filepath, "rb") as fh:
                content = fh.read()
            content.decode("utf-8")
        except UnicodeDecodeError as e:
            rel_path = os.path.relpath(filepath, base_dir)
            print(f"NON-UTF8: {rel_path}")
            print(f"  Error: {e}")
            print(f"  Size: {len(content)} bytes")
            # Show the problematic bytes
            start = max(0, e.start - 20)
            end = min(len(content), e.end + 20)
            print(f"  Problematic bytes: {content[start:end]!r}")
            print()

print("Done checking all files.")
