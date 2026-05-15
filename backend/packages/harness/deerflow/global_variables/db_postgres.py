"""PostgreSQL backend for global variables storage."""

import logging
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

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
                "│   ├── 故事圣经.md              # 故事圣经（世界观、力量体系、核心冲突）\n"
                "│   ├── 角色矩阵.md              # 角色矩阵（角色档案、关系网）\n"
                "│   ├── 支线板.md                # 支线板（多条故事线跟踪）\n"
                "│   ├── 情感弧线.md              # 情感弧线（角色情感发展）\n"
                "│   └── 细纲摘要.md              # 细纲摘要（每章一句话剧情概述）\n"
                "├── 01-规划/\n"
                "│   ├── 卷纲.md                  # 卷纲（分卷概览 + 章节分组规划）\n"
                "│   ├── 本书规则.json            # 本书规则（JSON 格式，硬规则+风格指南）\n"
                "│   ├── 创作计划.md              # 创作计划\n"
                "│   └── chapters/                # 章节细纲（每 5 章一组）\n"
                "│       ├── 第1-5章-细纲.md\n"
                "│       ├── 第6-10章-细纲.md\n"
                "│       └── ...\n"
                "├── 02-正文/                     # 正文按章节组组织\n"
                "│   └── 第N-M章/                 # 每组一个文件夹（如：第1-5章/）\n"
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
                "│   ├── 当前状态卡.md            # 当前状态卡（主角位置、目标、敌人等）\n"
                "│   ├── 待办事项.md              # 伏笔池（未解决伏笔跟踪）\n"
                "│   └── 章节摘要汇总.md          # 章节摘要汇总\n"
                "├── 04-审稿/\n"
                "│   ├── 第1章-审计报告.md       # 正文审计报告\n"
                "│   ├── 第1章-修改记录.md       # 正文修改记录\n"
                "│   ├── 第1-5章-审核报告.md    # 细纲审核报告\n"
                "│   ├── 第1-5章-修改记录.md    # 细纲修改记录\n"
                "│   └── ...\n"
                "├── 05-参考/\n"
                "│   ├── 样式指纹.md              # 风格指纹（从样章提取）\n"
                "│   └── 市场分析.md              # 市场分析（如适用）\n"
                "└── 06-归档/\n"
                "    ├── 合并后的卷摘要.md        # 压缩后的卷摘要\n"
                "    └── 历史版本/                # 重要修改前备份"
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


class PostgresGlobalVariablesDB(GlobalVariablesDB):
    """PostgreSQL implementation of global variables storage."""

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self._pool = ConnectionPool(connection_string, min_size=1, max_size=10)
        self.init_schema()

    def init_schema(self) -> None:
        """Initialize PostgreSQL schema."""
        with self._pool.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS global_variables (
                    id SERIAL PRIMARY KEY,
                    thread_id TEXT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    is_system BOOLEAN DEFAULT FALSE,
                    llm_editable BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMPTZ NOT NULL,
                    updated_by TEXT NOT NULL,
                    UNIQUE(thread_id, key)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_id ON global_variables(thread_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_key ON global_variables(key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_key ON global_variables(thread_id, key)")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_favorites (
                    id SERIAL PRIMARY KEY,
                    agent_name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            conn.commit()
        self._sync_system_variables_to_db()

    def _sync_system_variables_to_db(self) -> None:
        """Sync system variables to database on startup."""
        now = utc_now_iso_z()
        system_vars = _build_system_variables()
        
        with self._pool.connection() as conn:
            for key, var_data in system_vars.items():
                conn.execute(
                    """
                    INSERT INTO global_variables 
                    (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, key) 
                    DO UPDATE SET 
                        value = EXCLUDED.value,
                        description = EXCLUDED.description,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                """,
                    (None, key, var_data["value"], var_data["description"], True, var_data["llm_editable"], now, "system"),
                )
            conn.commit()

    def load(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        """Load variables from PostgreSQL database."""
        if scope == "thread" and not thread_id:
            return {"variables": _build_system_variables(), "is_system": True, "is_custom": False}

        with self._pool.connection() as conn:
            if scope == "project":
                rows = conn.execute("""
                    SELECT key, value, description, is_system, llm_editable, updated_at, updated_by
                    FROM global_variables
                    WHERE thread_id IS NULL
                    ORDER BY key
                """).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT key, value, description, is_system, llm_editable, updated_at, updated_by
                    FROM global_variables
                    WHERE thread_id = %s
                    ORDER BY key
                """,
                    (thread_id,),
                ).fetchall()

            variables = {}
            for row in rows:
                updated_at = row[5]
                if isinstance(updated_at, datetime):
                    updated_at = updated_at.isoformat()
                variables[row[0]] = {
                    "value": row[1],
                    "description": row[2] or "",
                    "is_system": bool(row[3]),
                    "llm_editable": bool(row[4]),
                    "updated_at": updated_at or "",
                    "updated_by": row[6],
                }

            if scope == "project":
                last_updated_row = conn.execute("""
                    SELECT MAX(updated_at) as last_updated
                    FROM global_variables
                    WHERE thread_id IS NULL
                """).fetchone()
            else:
                last_updated_row = conn.execute(
                    """
                    SELECT MAX(updated_at) as last_updated
                    FROM global_variables
                    WHERE thread_id = %s
                """,
                    (thread_id,),
                ).fetchone()

            last_updated = last_updated_row[0] if last_updated_row and last_updated_row[0] else ""
            if isinstance(last_updated, datetime):
                last_updated = last_updated.isoformat()

            all_variables = {**_build_system_variables(), **variables}
            user_variable_count = sum(1 for v in variables.values() if not (isinstance(v, dict) and v.get("is_system")))

            return {
                "variables": all_variables,
                "lastUpdated": last_updated,
                "is_custom": user_variable_count > 0,
            }

    def save(self, data: dict[str, Any], scope: str, thread_id: str | None = None) -> bool:
        """Save variables to PostgreSQL database using UPSERT."""
        try:
            with self._pool.connection() as conn:
                all_vars = data.get("variables", {})
                now = utc_now_iso_z()

                for key, var_data in all_vars.items():
                    if isinstance(var_data, dict) and var_data.get("is_system"):
                        continue

                    value = var_data.get("value", "") if isinstance(var_data, dict) else str(var_data)
                    description = var_data.get("description", "") if isinstance(var_data, dict) else ""
                    llm_editable = var_data.get("llm_editable", True) if isinstance(var_data, dict) else True

                    if scope == "project":
                        conn.execute(
                            """
                            INSERT INTO global_variables 
                            (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (thread_id, key) 
                            DO UPDATE SET 
                                value = EXCLUDED.value,
                                description = EXCLUDED.description,
                                llm_editable = EXCLUDED.llm_editable,
                                updated_at = EXCLUDED.updated_at,
                                updated_by = EXCLUDED.updated_by
                        """,
                            (None, key, value, description, False, llm_editable, now, "api"),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO global_variables 
                            (thread_id, key, value, description, is_system, llm_editable, updated_at, updated_by)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (thread_id, key) 
                            DO UPDATE SET 
                                value = EXCLUDED.value,
                                description = EXCLUDED.description,
                                llm_editable = EXCLUDED.llm_editable,
                                updated_at = EXCLUDED.updated_at,
                                updated_by = EXCLUDED.updated_by
                        """,
                            (thread_id, key, value, description, False, llm_editable, now, "api"),
                        )

                conn.commit()
                logger.info("Global variables saved to PostgreSQL database")
                return True
        except Exception as e:
            logger.error("Failed to save global variables: %s", e)
            return False

    def load_novel_tocs(self) -> dict[str, str]:
        """Load novel_toc values for all threads."""
        with self._pool.connection() as conn:
            rows = conn.execute("""
                SELECT thread_id, value
                FROM global_variables
                WHERE key = 'novel_toc' AND thread_id IS NOT NULL AND value != ''
            """).fetchall()
            return {row[0]: row[1] for row in rows}

    def list_agent_favorites(self) -> list[str]:
        """Get all favorited agent names."""
        with self._pool.connection() as conn:
            rows = conn.execute("""
                SELECT agent_name FROM agent_favorites ORDER BY created_at DESC
            """).fetchall()
            return [row[0] for row in rows]

    def add_agent_favorite(self, agent_name: str) -> bool:
        """Add an agent to favorites."""
        try:
            now = utc_now_iso_z()
            with self._pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_favorites (agent_name, created_at)
                    VALUES (%s, %s)
                    ON CONFLICT (agent_name) DO UPDATE SET created_at = EXCLUDED.created_at
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
            with self._pool.connection() as conn:
                result = conn.execute(
                    """
                    DELETE FROM agent_favorites WHERE agent_name = %s
                """,
                    (agent_name,),
                )
                deleted = result.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error("Failed to remove agent favorite: %s", e)
            return False

    def delete(self, key: str, scope: str, thread_id: str | None = None) -> bool:
        """Delete a variable from database."""
        try:
            with self._pool.connection() as conn:
                if scope == "project":
                    result = conn.execute(
                        """
                        DELETE FROM global_variables
                        WHERE thread_id IS NULL AND key = %s
                    """,
                        (key,),
                    )
                else:
                    result = conn.execute(
                        """
                        DELETE FROM global_variables
                        WHERE thread_id = %s AND key = %s
                    """,
                        (thread_id, key),
                    )

                deleted = result.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error("Failed to delete variable: %s", e)
            return False

    def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            self._pool.close()
