"""Database abstraction layer for global variables."""

from abc import ABC, abstractmethod
from typing import Any


class GlobalVariablesDB(ABC):
    """Abstract base class for global variables database backends."""

    @abstractmethod
    def init_schema(self) -> None:
        """Initialize database schema (tables, indexes)."""

    @abstractmethod
    def load(self, scope: str, thread_id: str | None = None) -> dict[str, Any]:
        """Load variables."""

    @abstractmethod
    def save(self, data: dict[str, Any], scope: str, thread_id: str | None = None) -> bool:
        """Save variables."""

    @abstractmethod
    def delete(self, key: str, scope: str, thread_id: str | None = None) -> bool:
        """Delete a variable."""

    @abstractmethod
    def load_novel_tocs(self) -> dict[str, str]:
        """Load novel_toc values for all threads."""

    @abstractmethod
    def list_agent_favorites(self) -> list[str]:
        """Get all favorited agent names."""

    @abstractmethod
    def add_agent_favorite(self, agent_name: str) -> bool:
        """Add an agent to favorites."""

    @abstractmethod
    def remove_agent_favorite(self, agent_name: str) -> bool:
        """Remove an agent from favorites."""

    @abstractmethod
    def delete_by_key_across_threads(self, key: str) -> int:
        """Delete a variable by key across all threads. Returns number of deleted rows."""

    @abstractmethod
    def close(self) -> None:
        """Close database connection."""
