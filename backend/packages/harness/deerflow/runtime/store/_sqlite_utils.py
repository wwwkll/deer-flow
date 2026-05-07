"""Shared SQLite connection utilities for store and checkpointer providers."""

from __future__ import annotations

import pathlib
import urllib.parse

from deerflow.config.paths import resolve_path

BUSY_TIMEOUT_MS = 30000


def resolve_sqlite_conn_str(raw: str) -> str:
    """Return a SQLite connection string ready for use with store/checkpointer backends.

    SQLite special strings (``":memory:"`` and ``file:`` URIs) are returned
    unchanged.  Plain filesystem paths — relative or absolute — are resolved
    to an absolute string via :func:`resolve_path`.

    For filesystem paths, returns the absolute path.  WAL mode and busy_timeout
    must be set separately via PRAGMA after connection (especially on Windows,
    where ``file:`` URIs are not reliably supported by aiosqlite).
    """
    if raw == ":memory:":
        return raw
    if raw.startswith("file:"):
        return raw

    # Return plain filesystem path — aiosqlite on Windows cannot open
    # ``file:`` URIs, so callers must execute PRAGMAs after connecting.
    return str(resolve_path(raw))


def _extract_path_from_conn_str(conn_str: str) -> str:
    """Extract filesystem path from a SQLite connection string."""
    if conn_str.startswith("file:"):
        uri_path, _, _ = conn_str.partition("?")
        return urllib.parse.unquote(uri_path[5:])
    return conn_str


def ensure_sqlite_parent_dir(conn_str: str) -> None:
    """Create parent directory for a SQLite filesystem path.

    No-op for in-memory databases (``":memory:"``) and ``file:`` URIs.
    """
    if conn_str == ":memory:":
        return
    path = _extract_path_from_conn_str(conn_str)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
