"""Shared path resolution for thread virtual paths (e.g. mnt/user-data/outputs/...)."""

import logging
from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def resolve_thread_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """Resolve a virtual path to the actual filesystem path under thread user-data.

    Args:
        thread_id: The thread ID.
        virtual_path: The virtual path as seen inside the sandbox
                      (e.g., /mnt/user-data/outputs/file.txt).

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If the path is invalid or outside allowed directories.
    """
    try:
        return get_paths().resolve_virtual_path(thread_id, virtual_path)
    except ValueError as e:
        status = 403 if "traversal" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


def resolve_mount_virtual_path(virtual_path: str) -> Path:
    """Resolve a custom mount virtual path (e.g. /mnt/shared-data/...) to host path.

    Uses the sandbox.mounts configuration to find the matching mount and
    resolve the virtual path to the actual host filesystem path.

    Args:
        virtual_path: The virtual path as seen inside the sandbox
                      (e.g., /mnt/shared-data/novels/book/小说A).

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If no matching mount is found or path traversal detected.
    """
    from deerflow.config.app_config import get_app_config

    config = get_app_config()
    mounts = config.sandbox.mounts if config.sandbox else []

    normalized = virtual_path.rstrip("/")

    best_match = None
    best_match_len = 0

    for mount in mounts:
        container_path = mount.container_path.rstrip("/")
        if normalized == container_path or normalized.startswith(container_path + "/"):
            if len(container_path) > best_match_len:
                best_match = mount
                best_match_len = len(container_path)

    if not best_match:
        raise HTTPException(
            status_code=403,
            detail=f"No mount configured for path: {virtual_path}",
        )

    host_path = Path(best_match.host_path)
    if not host_path.is_absolute():
        project_root = get_paths().base_dir.parent.parent
        host_path = (project_root / host_path).resolve()

    relative = normalized[best_match_len:].lstrip("/")
    if relative:
        actual = (host_path / relative).resolve()
    else:
        actual = host_path.resolve()

    try:
        actual.relative_to(host_path.resolve())
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Access denied: path traversal detected",
        )

    return actual


def resolve_any_virtual_path(thread_id: str, virtual_path: str) -> Path:
    """Resolve any virtual path to host filesystem path.

    Routes to the appropriate resolver based on the path prefix:
    - /mnt/user-data/... -> thread-scoped user data
    - Other mount paths (e.g. /mnt/shared-data/...) -> custom mount resolution

    Args:
        thread_id: The thread ID.
        virtual_path: The virtual path as seen inside the sandbox.

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException: If the path cannot be resolved.
    """
    if virtual_path.startswith("/mnt/user-data"):
        return resolve_thread_virtual_path(thread_id, virtual_path)
    return resolve_mount_virtual_path(virtual_path)
