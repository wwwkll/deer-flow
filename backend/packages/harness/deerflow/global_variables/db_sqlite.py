"""SQLite backend for global variables storage."""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.config.paths import get_paths
from deerflow.global_variables.db_base import GlobalVariablesDB

logger = logging.getLogger(__name__)


def _build_system_variables() -> dict[str, Any]:
    """Build system variables dict with dynamic workdir from config."""
    from deerflow.config.app_config import get_app_config

    try:
        config = get_app_config()
        mounts = config.sandbox.mounts if config and config.sandbox else []
        if mounts:
            workdir = mounts[0].container_path
        else:
            workdir = "/mnt/shared-data"
    except Exception as e:
        logger.warning(f"Failed to read sandbox mounts for workdir: {e}")
        workdir = "/mnt/shared-data"

    return {
        "workdir": {
            "value": workdir,
            "description": "Shared workspace directory",
            "is_system": True,
            "llm_editable": False,
            "updated_at": "system",
            "updated_by": "system",
        },
        "novel_dir_structure": {
            "value": (
                "工作目录/book/[小说名称]/\n"
                "├── card.json                    # 小说名片（JSON 格式，记录进度等元数据）\n"
                "├── 00-世界观/\n"
                "│   ├── 故事圣经.md           # 故事圣经（世界观、力量体系、核心冲突）\n"
                "│   ├── 角色矩阵.md      # 角色矩阵（角色档案、关系网）\n"
                "│   ├── 支线板.md         # 支线板（多条故事线跟踪）\n"
                "│   └── 情感弧线.md        # 情感弧线（角色情感发展）\n"
                "├── 01-规划/\n"
                "│   ├── 卷纲.md        # 卷纲（分卷概览 + 章节分组规划）\n"
                "│   ├── 本书规则.json          # 本书规则（JSON 格式，硬规则+风格指南）\n"
                "│   ├── 创作计划.md             # 创作计划\n"
                "│   └── chapters/                # 章节细纲（每 5 章一组）\n"
                "│       ├── 第01-05章-细纲.md\n"
                "│       ├── 第06-10章-细纲.md\n"
                "│       └── ...\n"
                "├── 02-正文/                     # 正文按章节组组织\n"
                "│   └── 第N-M章/                 # 每组一个文件夹（如：第01-05章/）\n"
                "│       ├── _task/               # 临时任务目录（写作时创建，完成后清理）\n"
                "│       │   ├── 世界观参考.md\n"
                "│       │   ├── 人物参考.md\n"
                "│       │   ├── 道具参考.md\n"
                "│       │   ├── 故事线参考.md\n"
                "│       │   ├── 用户要求.md\n"
                "│       │   └── 写作任务汇总.md\n"
                "│       ├── 第N章.md             # 各章节正文\n"
                "│       ├── 第N+1章.md\n"
                "│       └── ...\n"
                "├── 03-状态/\n"
                "│   ├── 当前状态卡.md         # 当前状态卡（主角位置、目标、敌人等）\n"
                "│   ├── 待办事项.md         # 伏笔池（未解决伏笔跟踪）\n"
                "│   └── 章节摘要汇总.md     # 章节摘要汇总\n"
                "├── 04-审稿/\n"
                "│   ├── 第01章-审计报告.md\n"
                "│   ├── 第01章-修改记录.md\n"
                "│   └── ...\n"
                "├── 05-参考/\n"
                "│   ├── 样式指纹.md         # 风格指纹（从样章提取）\n"
                "│   └── 市场分析.md          # 市场分析（如适用）\n"
                "└── 06-归档/\n"
                "    ├── 合并后的卷摘要.md # 压缩后的卷摘要\n"
                "    └── 历史版本/                 # 重要修改前备份"
            ),
            "description": "Novel project directory structure template",
            "is_system": True,
            "llm_editable": False,
            "updated_at": "system",
            "updated_by": "system",
        },
    }


def utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


class SQLiteGlobalVariablesDB(GlobalVariablesDB):
    """SQLite implementation of global variables storage."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._db_path = db_path or (get_paths().base_dir / "global_variables.db")

    @contextmanager
    def _get_connection(self):
        """Get thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            with self._init_lock:
                if not hasattr(self._local, "conn") or self._local.conn is None:
                    self._db_path.parent.mkdir(parents=True, exist_ok=True)
                    self._local.conn = sqlite3.connect(
                        f"file:{self._db_path.as_posix()}?mode=rwc&journal_mode=WAL&busy_timeout=30000",
                        uri=True,
                        check_same_thread=False,
                    )
                    self._local.conn.row_factory = sqlite3.Row
                    self._local.conn.execute("PRAGMA journal_mode=WAL")
                    self._local.conn.execute("PRAGMA busy_timeout=30000")
                    self._init_database(self._local.conn)
        try:
            yield self._local.conn
        except Exception:
            self._local.conn.rollback()
            raise

    def _init_database(self, conn: sqlite3.Connection) -> None:
        """Initialize database schema."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS global_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                description TEXT DEFAULT '',
                is_system BOOLEAN DEFAULT FALSE,
                llm_editable BOOLEAN DEFAULT TRUE,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                UNIQUE(thread_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_thread_id ON global_variables(thread_id);
            CREATE INDEX IF NOT EXISTS idx_key ON global_variables(key);
            CREATE INDEX IF NOT EXISTS idx_thread_key ON global_variables(thread_id, key);

            CREATE TABLE IF NOT EXISTS agent_favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(agent_name)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_favorites_name ON agent_favorites(agent_name);
        """)
        conn.commit()
        self._sync_system_variables_to_db(conn)

    def _sync_system_variables_to_db(self, conn: sqlite3.Connection) -> None:
        """Sync system variables to database on startup."""
        now = utc_now_iso_z()
        cursor = conn.cursor()
        system_vars = _build_system_variables()
        for key, var_data in system_vars.items():
            cursor.execute(
                """
                UPDATE global_variables
                SET value = ?, description = ?, updated_at = ?, updated_by = ?
                WHERE thread_id IS NULL AND key = ?
            """,
                (var_data["value"], var_data["description"], now, "system", key),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO global_variables
                    (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (None, key, var_data["value"], var_data["description"], True, var_data["llm_editable"], now, "system"),
                )
        conn.commit()

    def init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            pass  # Schema is initialized on first connection

    def load(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        """Load variables from database."""
        if scope == "thread" and not thread_id:
            return {"variables": _build_system_variables(), "is_system": True, "is_custom": False}

        with self._get_connection() as conn:
            cursor = conn.cursor()
            if scope == "project":
                cursor.execute("""
                    SELECT key, value, description, is_system, llm_editable, updated_at, updated_by
                    FROM global_variables
                    WHERE thread_id IS NULL
                    ORDER BY key
                """)
            else:
                cursor.execute(
                    """
                    SELECT key, value, description, is_system, llm_editable, updated_at, updated_by
                    FROM global_variables
                    WHERE thread_id = ?
                    ORDER BY key
                """,
                    (thread_id,),
                )

            variables = {}
            for row in cursor.fetchall():
                variables[row["key"]] = {
                    "value": row["value"],
                    "description": row["description"] or "",
                    "is_system": bool(row["is_system"]),
                    "llm_editable": bool(row["llm_editable"]),
                    "updated_at": row["updated_at"],
                    "updated_by": row["updated_by"],
                }

            if scope == "project":
                cursor.execute("""
                    SELECT MAX(updated_at) as last_updated
                    FROM global_variables
                    WHERE thread_id IS NULL
                """)
            else:
                cursor.execute(
                    """
                    SELECT MAX(updated_at) as last_updated
                    FROM global_variables
                    WHERE thread_id = ?
                """,
                    (thread_id,),
                )

            row = cursor.fetchone()
            last_updated = row["last_updated"] if row and row["last_updated"] else ""

            all_variables = {**_build_system_variables(), **variables}
            user_variable_count = sum(1 for v in variables.values() if not (isinstance(v, dict) and v.get("is_system")))

            return {
                "variables": all_variables,
                "lastUpdated": last_updated,
                "is_custom": user_variable_count > 0,
            }

    def save(self, data: dict[str, Any], scope: str, thread_id: str | None = None) -> bool:
        """Save variables to database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                all_vars = data.get("variables", {})
                now = utc_now_iso_z()

                for key, var_data in all_vars.items():
                    if isinstance(var_data, dict) and var_data.get("is_system"):
                        continue

                    value = var_data.get("value", "") if isinstance(var_data, dict) else str(var_data)
                    description = var_data.get("description", "") if isinstance(var_data, dict) else ""
                    llm_editable = var_data.get("llm_editable", True) if isinstance(var_data, dict) else True

                    if scope == "project":
                        cursor.execute(
                            """
                            UPDATE global_variables
                            SET value = ?, description = ?, llm_editable = ?, updated_at = ?, updated_by = ?
                            WHERE thread_id IS NULL AND key = ?
                        """,
                            (value, description, llm_editable, now, "api", key),
                        )

                        if cursor.rowcount == 0:
                            cursor.execute(
                                """
                                INSERT INTO global_variables
                                (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                                (None, key, value, description, False, llm_editable, now, "api"),
                            )
                    else:
                        cursor.execute(
                            """
                            UPDATE global_variables
                            SET value = ?, description = ?, llm_editable = ?, updated_at = ?, updated_by = ?
                            WHERE thread_id = ? AND key = ?
                        """,
                            (value, description, llm_editable, now, "api", thread_id, key),
                        )

                        if cursor.rowcount == 0:
                            cursor.execute(
                                """
                                INSERT INTO global_variables
                                (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                                (thread_id, key, value, description, False, llm_editable, now, "api"),
                            )

                conn.commit()
                logger.info("Global variables saved to SQLite database")
                return True
        except Exception as e:
            logger.error("Failed to save global variables: %s", e)
            return False

    def load_novel_tocs(self) -> dict[str, str]:
        """Load novel_toc values for all threads."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT thread_id, value
                FROM global_variables
                WHERE key = 'novel_toc' AND thread_id IS NOT NULL AND value != ''
            """)
            return {row["thread_id"]: row["value"] for row in cursor.fetchall()}

    def list_agent_favorites(self) -> list[str]:
        """Get all favorited agent names."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT agent_name FROM agent_favorites ORDER BY created_at DESC
            """)
            return [row["agent_name"] for row in cursor.fetchall()]

    def add_agent_favorite(self, agent_name: str) -> bool:
        """Add an agent to favorites."""
        try:
            now = utc_now_iso_z()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE agent_favorites SET created_at = ? WHERE agent_name = ?
                """,
                    (now, agent_name),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        INSERT INTO agent_favorites (agent_name, created_at) VALUES (?, ?)
                    """,
                        (agent_name, now),
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error("Failed to add agent favorite: %s", e)
            return False

    def remove_agent_favorite(self, agent_name: str) -> bool:
        """Remove an agent from favorites."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM agent_favorites WHERE agent_name = ?
                """,
                    (agent_name,),
                )
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error("Failed to remove agent favorite: %s", e)
            return False

    def delete(self, key: str, scope: str, thread_id: str | None = None) -> bool:
        """Delete a variable from database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if scope == "project":
                    cursor.execute(
                        """
                        DELETE FROM global_variables
                        WHERE thread_id IS NULL AND key = ?
                    """,
                        (key,),
                    )
                else:
                    cursor.execute(
                        """
                        DELETE FROM global_variables
                        WHERE thread_id = ? AND key = ?
                    """,
                        (thread_id, key),
                    )

                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error("Failed to delete variable: %s", e)
            return False

    def close(self) -> None:
        """Close database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
