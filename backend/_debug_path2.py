import os
import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend")
sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages\harness")

os.environ.pop("DEERFLOW_DATA_DIR", None)

from pathlib import Path

from deerflow.config.paths import get_paths

# Check base_dir
paths = get_paths()
print(f"base_dir: {paths.base_dir}")
print(f"base_dir.parent: {paths.base_dir.parent}")
print(f"base_dir.parent.parent: {paths.base_dir.parent.parent}")

# Now load config
from deerflow.config.app_config import load_app_config_from_yaml, set_app_config

config = load_app_config_from_yaml("c:/xiangmu/deer-flow/config.yaml")
set_app_config(config)

print("\nConfig loaded, sandbox mounts:")
for m in config.sandbox.mounts:
    print(f"  {m.container_path} -> {m.host_path}")

# Try to resolve the mount path
host_path_str = config.sandbox.mounts[0].host_path
host_path = Path(host_path_str)
if not host_path.is_absolute():
    project_root = paths.base_dir.parent.parent
    resolved = (project_root / host_path).resolve()
    print(f'\nRelative host_path "{host_path_str}" resolves to: {resolved}')
    print(f"  exists: {resolved.exists()}")
    if resolved.exists():
        target = resolved / "novels" / "book" / "测试小说"
        print(f"  target: {target}")
        print(f"  target exists: {target.exists()}")
        if target.exists():
            print(f"  contents: {list(target.iterdir())}")
