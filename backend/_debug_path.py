import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend")
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

from deerflow.config.app_config import load_app_config_from_yaml, set_app_config
from deerflow.config.paths import get_paths

config = load_app_config_from_yaml("c:/xiangmu/deer-flow/config.yaml")
set_app_config(config)

print(f"base_dir: {get_paths().base_dir}")
print(f"sandbox mounts: {config.sandbox.mounts}")

from pathlib import Path

for mount in config.sandbox.mounts:
    host_path = Path(mount.host_path)
    if not host_path.is_absolute():
        project_root = get_paths().base_dir.parent.parent
        host_path = (project_root / host_path).resolve()
    print(f"  {mount.container_path} -> {host_path} (exists: {host_path.exists()})")

virtual_path = "/mnt/shared-data/novels/book/测试小说"
print(f"\nResolving: {virtual_path}")

try:
    from app.gateway.path_utils import resolve_mount_virtual_path

    result = resolve_mount_virtual_path(virtual_path)
    print(f"Resolved to: {result} (exists: {result.exists()})")
except Exception as e:
    print(f"Error: {e}")
