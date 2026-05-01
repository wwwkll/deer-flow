import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend")
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")


from deerflow.config.paths import get_paths

base_dir = get_paths().base_dir
print(f"base_dir: {base_dir}")

project_root = base_dir.parent.parent
print(f"project_root: {project_root}")

host_path = (project_root / "backend/.deer-flow/shared-data").resolve()
print(f"mount host_path: {host_path}")
print(f"exists: {host_path.exists()}")

virtual_path = "/mnt/shared-data/novels/book/测试小说"
container_path = "/mnt/shared-data"
relative = virtual_path[len(container_path) :].lstrip("/")
print(f"relative: {relative}")

actual = (host_path / relative).resolve()
print(f"actual: {actual}")
print(f"exists: {actual.exists()}")
if actual.exists():
    print(f"is_dir: {actual.is_dir()}")
    entries = list(actual.iterdir())[:5]
    print(f"entries: {[e.name for e in entries]}")
