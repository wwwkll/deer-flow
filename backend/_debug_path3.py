import os
import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend")
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

os.environ.pop("DEERFLOW_DATA_DIR", None)

from deerflow.config.paths import get_paths

print(f"base_dir: {get_paths().base_dir}")

from deerflow.config.app_config import load_app_config_from_yaml, set_app_config

config = load_app_config_from_yaml("c:/xiangmu/deer-flow/config.yaml")
set_app_config(config)

print("mounts:")
for m in config.sandbox.mounts:
    host_path = os.path.join(str(get_paths().base_dir.parent.parent), m.host_path)
    print(f"  container: {m.container_path} -> host: {host_path}")
    print(f"  exists: {os.path.exists(host_path)}")

virtual_path = "/mnt/shared-data/novels/book/测试小说"
print(f"\nResolving: {virtual_path}")

from pathlib import Path

for mount in config.sandbox.mounts:
    container_path = mount.container_path.rstrip("/")
    if virtual_path.startswith(container_path + "/") or virtual_path == container_path:
        host_path = Path(mount.host_path)
        if not host_path.is_absolute():
            project_root = get_paths().base_dir.parent.parent
            host_path = (project_root / host_path).resolve()

        relative = virtual_path[len(container_path) :].lstrip("/")
        if relative:
            actual = (host_path / relative).resolve()
        else:
            actual = host_path.resolve()

        print(f"Resolved: {actual}")
        print(f"Exists: {actual.exists()}")
        if actual.exists():
            print(f"Is dir: {actual.is_dir()}")
            if actual.is_dir():
                entries = list(actual.iterdir())[:5]
                print(f"First 5 entries: {[e.name for e in entries]}")
