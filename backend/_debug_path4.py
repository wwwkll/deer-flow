import sys
from pathlib import Path

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend")
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")


from deerflow.config.app_config import get_app_config
from deerflow.config.paths import get_paths

base_dir = get_paths().base_dir
print(f"base_dir: {base_dir}")

# Get mount host_path from config
config = get_app_config()
mounts = config.sandbox.mounts if config and config.sandbox else []
for mount in mounts:
    host_path = Path(mount.host_path)
    if not host_path.is_absolute():
        project_root = base_dir.parent.parent
        host_path = (project_root / host_path).resolve()
    print(f"mount container_path: {mount.container_path}")
    print(f"mount host_path: {host_path}")
    print(f"exists: {host_path.exists()}")

    # Test path mapping
    virtual_path = "/mnt/shared-data/book/测试小说"
    container_path = mount.container_path.rstrip("/")
    if virtual_path.startswith(container_path):
        relative = virtual_path[len(container_path):].lstrip("/")
        actual = (host_path / relative).resolve()
        print(f"virtual_path: {virtual_path}")
        print(f"actual host_path: {actual}")
        print(f"exists: {actual.exists()}")
        if actual.exists():
            print(f"is_dir: {actual.is_dir()}")
            entries = list(actual.iterdir())[:5]
            print(f"entries: {[e.name for e in entries]}")
