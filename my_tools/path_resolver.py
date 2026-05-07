# -*- coding: utf-8 -*-
"""Sandbox path resolver for custom tools.

Converts sandbox container paths to host paths so that custom tools
running on the host can correctly read/write files.

Supports two path types:
1. /mnt/shared-data/... -> from sandbox.mounts config (e.g. E:\\xiangmu\\deer-flow-data\\shared-data\\...)
2. /mnt/user-data/...   -> per-thread path (e.g. .deer-flow/threads/{thread_id}/user-data/...)
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_mount_cache: list[tuple[str, str]] | None = None
_current_thread_id: str | None = None


def set_current_thread_id(thread_id: str | None) -> None:
    """Set the current thread ID for /mnt/user-data/ path resolution.

    Should be called by the workflow before invoking custom tools.
    """
    global _current_thread_id
    _current_thread_id = thread_id


def get_current_thread_id() -> str | None:
    """Get the current thread ID."""
    return _current_thread_id


def _load_mounts() -> list[tuple[str, str]]:
    """Load and cache sandbox mount mappings as (container_path, host_path) pairs."""
    global _mount_cache
    if _mount_cache is not None:
        return _mount_cache

    try:
        from deerflow.config.app_config import get_app_config

        config = get_app_config()
        mounts = config.sandbox.mounts if config and config.sandbox else []

        pairs: list[tuple[str, str]] = []
        for mount in mounts:
            container = mount.container_path.rstrip("/")
            host = mount.host_path
            if not os.path.isabs(host):
                from deerflow.config.paths import get_paths
                host = str((Path(get_paths().base_dir).parent.parent / host).resolve())
            pairs.append((container, host))

        pairs.sort(key=lambda p: len(p[0]), reverse=True)
        _mount_cache = pairs
    except Exception:
        _mount_cache = []

    return _mount_cache


def _resolve_user_data_path(path: str) -> str | None:
    """Resolve /mnt/user-data/... path to host path.

    Uses the thread_id set via set_current_thread_id(). If not set,
    falls back to scanning .deer-flow/threads/ for the most recent thread.

    Mapping:
        /mnt/user-data/workspace/* -> {base_dir}/threads/{thread_id}/user-data/workspace/*
        /mnt/user-data/uploads/*   -> {base_dir}/threads/{thread_id}/user-data/uploads/*
        /mnt/user-data/outputs/*   -> {base_dir}/threads/{thread_id}/user-data/outputs/*
        /mnt/user-data/*           -> {base_dir}/threads/{thread_id}/user-data/*
    """
    normalized = path.replace("\\", "/")
    if not normalized.startswith("/mnt/user-data"):
        return None

    thread_id = _current_thread_id
    if not thread_id:
        thread_id = _discover_thread_id()
    if not thread_id:
        logger.warning("Cannot resolve /mnt/user-data path: no thread_id available")
        return None

    try:
        from deerflow.config.paths import get_paths
        host_base = get_paths().host_sandbox_user_data_dir(thread_id)
    except Exception:
        return None

    rest = normalized[len("/mnt/user-data"):].lstrip("/")
    if rest:
        return str(Path(host_base) / rest)
    return host_base


def _discover_thread_id() -> str | None:
    """Scan .deer-flow/threads/ to find the most recently modified thread."""
    try:
        from deerflow.config.paths import get_paths
        threads_dir = get_paths().base_dir / "threads"
        if not threads_dir.exists():
            return None

        candidates = []
        for entry in threads_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                user_data = entry / "user-data"
                if user_data.exists():
                    candidates.append((entry.stat().st_mtime, entry.name))

        if candidates:
            candidates.sort(reverse=True)
            logger.info("[path_resolver] 自动发现 thread_id=%s", candidates[0][1])
            return candidates[0][1]
    except Exception as e:
        logger.warning(f"Failed to discover thread_id: {e}")

    return None


def resolve_to_host_path(file_path: str) -> str:
    """Resolve a sandbox container path to the corresponding host path.

    Supports two path types:
    1. /mnt/shared-data/... -> resolved via sandbox.mounts config
    2. /mnt/user-data/...   -> resolved via thread_id discovery

    If the path doesn't match any known prefix, returns it unchanged.

    Examples:
        >>> resolve_to_host_path("/mnt/shared-data/book/测试小说/card.json")
        "E:\\xiangmu\\deer-flow-data\\shared-data\\book\\测试小说\\card.json"

        >>> resolve_to_host_path("/mnt/user-data/workspace/file.txt")
        "e:\\xiangmu\\deer-flow\\backend\\.deer-flow\\threads\\{thread_id}\\user-data\\workspace\\file.txt"
    """
    normalized = file_path.replace("\\", "/")

    # 1. Check /mnt/user-data/ first (more specific prefix)
    if normalized.startswith("/mnt/user-data"):
        result = _resolve_user_data_path(normalized)
        if result:
            logger.info("[path_resolver] resolve_to_host_path | %s -> %s (user-data)", file_path, result)
            return result

    # 2. Check sandbox mounts (handles /mnt/shared-data/ and any other custom mounts)
    mounts = _load_mounts()
    for container_path, host_path in mounts:
        if normalized == container_path or normalized.startswith(container_path + "/"):
            relative = normalized[len(container_path):].lstrip("/")
            if relative:
                resolved = str(Path(host_path) / relative)
                logger.info("[path_resolver] resolve_to_host_path | %s -> %s (mount)", file_path, resolved)
                return resolved
            logger.info("[path_resolver] resolve_to_host_path | %s -> %s (mount)", file_path, host_path)
            return host_path

    logger.debug("[path_resolver] resolve_to_host_path | %s -> %s (未匹配，原样返回)", file_path, file_path)
    return file_path
