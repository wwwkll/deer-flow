import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "packages" / "harness"))

from deerflow.config.app_config import get_app_config

def _get_workdir_from_config():
    try:
        config = get_app_config()
        mounts = config.sandbox.mounts if config and config.sandbox else []
        if mounts:
            return mounts[0].container_path
    except Exception:
        pass
    return "/mnt/shared-data"

db_path = r"c:\xiangmu\deer-flow\backend\.deer-flow\global_variables.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

thread_id = "2e043892-5491-42fc-b99f-b03ffaf26f92"

cur.execute(
    """
    SELECT key, value, description, is_system, llm_editable, updated_at, updated_by
    FROM global_variables
    WHERE thread_id = ?
    ORDER BY key
""",
    (thread_id,),
)

variables = {}
for row in cur.fetchall():
    variables[row["key"]] = {
        "value": row["value"],
        "description": row["description"] or "",
        "is_system": bool(row["is_system"]),
        "llm_editable": bool(row["llm_editable"]),
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }

print("Variables for thread:", thread_id)
for k, v in variables.items():
    print(f"  {k}: {v['value']}")

SYSTEM_VARIABLES = {
    "workdir": {
        "value": _get_workdir_from_config(),
        "description": "Shared workspace directory",
        "is_system": True,
        "llm_editable": False,
        "updated_at": "system",
        "updated_by": "system",
    },
}

all_variables = {**SYSTEM_VARIABLES, **variables}
print("\nAll variables (with system):")
for k, v in all_variables.items():
    print(f"  {k}: {v['value']}")

novel_toc_found = "novel_toc" in all_variables
print(f"\nnovel_toc found: {novel_toc_found}")
if novel_toc_found:
    print(f"novel_toc value: {all_variables['novel_toc']['value']}")

conn.close()
