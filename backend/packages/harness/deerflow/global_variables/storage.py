"""Global variables storage provider with pluggable database backends."""

import logging
import threading
from pathlib import Path
from typing import Any

from deerflow.config.paths import get_paths
from deerflow.global_variables.db_base import GlobalVariablesDB
from deerflow.global_variables.db_sqlite import SQLiteGlobalVariablesDB, _build_system_variables

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    """Get current UTC time in ISO format with Z suffix."""
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z"


def get_system_variables() -> dict[str, Any]:
    """Get system variables (public API)."""
    return {"variables": _build_system_variables(), "is_system": True}


def _get_db_backend() -> GlobalVariablesDB:
    """Factory function to create appropriate DB backend based on config."""
    try:
        from deerflow.config.app_config import get_app_config
        from deerflow.config.global_variables_config import get_global_variables_config

        config = get_global_variables_config()
        db_type = getattr(config, "db_type", "sqlite")
        connection_string = getattr(config, "connection_string", None)

        if db_type == "postgres" and connection_string:
            try:
                from deerflow.global_variables.db_postgres import PostgresGlobalVariablesDB
                logger.info("Global variables: using PostgreSQL backend")
                return PostgresGlobalVariablesDB(connection_string)
            except ImportError:
                logger.warning(
                    "psycopg is required for PostgreSQL backend. "
                    "Install it with: uv add psycopg[binary] psycopg-pool"
                )
                raise

        # Default to SQLite
        logger.info("Global variables: using SQLite backend")
        return SQLiteGlobalVariablesDB()

    except Exception as e:
        logger.warning(f"Failed to load database config, falling back to SQLite: {e}")
        return SQLiteGlobalVariablesDB()


class GlobalVariablesStorage:
    """Global variables storage with pluggable database backend."""

    def __init__(self, db: GlobalVariablesDB | None = None) -> None:
        self._db = db or _get_db_backend()

    def load(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        """Load variables from database."""
        return self._db.load(scope, thread_id)

    def reload(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        """Reload variables from database (alias for load)."""
        return self._db.load(scope, thread_id)

    def save(self, data: dict[str, Any], scope: str, thread_id: str | None = None) -> bool:
        """Save variables to database."""
        return self._db.save(data, scope, thread_id)

    def delete(self, key: str, scope: str, thread_id: str | None = None) -> bool:
        """Delete a variable from database."""
        return self._db.delete(key, scope, thread_id)

    def load_novel_tocs(self) -> dict[str, str]:
        """Load novel_toc values for all threads."""
        return self._db.load_novel_tocs()

    def list_agent_favorites(self) -> list[str]:
        """Get all favorited agent names."""
        return self._db.list_agent_favorites()

    def add_agent_favorite(self, agent_name: str) -> bool:
        """Add an agent to favorites."""
        return self._db.add_agent_favorite(agent_name)

    def remove_agent_favorite(self, agent_name: str) -> bool:
        """Remove an agent from favorites."""
        return self._db.remove_agent_favorite(agent_name)

    def close(self) -> None:
        """Close database connection."""
        self._db.close()


# Singleton instance
_storage_instance: GlobalVariablesStorage | None = None
_storage_lock = threading.Lock()


def get_storage() -> GlobalVariablesStorage:
    """Get the global variables storage singleton."""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    with _storage_lock:
        if _storage_instance is not None:
            return _storage_instance
        _storage_instance = GlobalVariablesStorage()
    return _storage_instance


def reset_storage() -> None:
    """Reset the storage singleton."""
    global _storage_instance
    with _storage_lock:
        if _storage_instance is not None:
            _storage_instance.close()
        _storage_instance = None
