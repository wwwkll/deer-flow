"""Novel tags API for scanning book directories from configured mount paths."""

import logging
import sys
import time
from pathlib import Path

from fastapi import APIRouter

from deerflow.config.paths import get_paths

# Fix Windows console encoding for Chinese characters
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            # Python < 3.7 doesn't have reconfigure
            pass

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/novel-tags", tags=["novel-tags"])

# Simple cache with 5-minute TTL
_novel_tags_cache = {
    "tags": [],
    "last_updated": 0,
    "ttl": 300,  # 5 minutes
}


def _find_book_directories(base_path: Path, max_depth: int = 3) -> list[Path]:
    """
    Find all directories named 'book' or 'books' under base_path up to max_depth levels.

    Args:
        base_path: The starting directory to search from
        max_depth: Maximum depth to search (default: 3)

    Returns:
        List of paths to directories named 'book' or 'books'
    """
    book_dirs = []

    def search(current_path: Path, current_depth: int):
        if current_depth > max_depth:
            return

        try:
            if not current_path.is_dir():
                return

            for item in current_path.iterdir():
                if item.is_dir():
                    if item.name.lower() in ("book", "books"):
                        book_dirs.append(item)
                    else:
                        search(item, current_depth + 1)
        except (PermissionError, OSError):
            # Skip directories we can't access
            pass

    search(base_path, 0)
    return book_dirs


def _scan_novel_tocs() -> list[str]:
    """
    Scan configured mount paths for book directories and collect novel TOC paths.

    Returns:
        Sorted list of unique novel directory paths
    """
    try:
        # Get app config to read sandbox mounts
        try:
            from deerflow.config.app_config import get_app_config

            config = get_app_config()
            mounts = config.sandbox.mounts if config and config.sandbox else []
            logger.warning(f"[DEBUG] Loaded {len(mounts)} mounts from config")
            for i, mount in enumerate(mounts):
                logger.warning(f"[DEBUG] Mount {i}: host_path={mount.host_path}, container_path={mount.container_path}")
        except Exception as e:
            logger.warning(f"[DEBUG] Could not load app config: {e}")
            mounts = []

        # If no mounts configured, return empty list
        if not mounts:
            logger.warning("[DEBUG] No sandbox mounts configured, returning empty tags list")
            return []

        tocs = set()

        for mount in mounts:
            # Get the host path and resolve it
            host_path = Path(mount.host_path)
            logger.warning(f"[DEBUG] Original host_path: {host_path}")

            # If not absolute, resolve relative to project root
            if not host_path.is_absolute():
                project_root = get_paths().base_dir.parent.parent
                host_path = (project_root / host_path).resolve()
                logger.warning(f"[DEBUG] Resolved host_path: {host_path}")

            if not host_path.exists():
                logger.warning(f"[DEBUG] Mount path does not exist: {host_path}")
                continue

            logger.warning(f"[DEBUG] Scanning mount path: {host_path}")

            # Find all book/books directories under this mount
            book_dirs = _find_book_directories(host_path, max_depth=3)
            logger.warning(f"[DEBUG] Found {len(book_dirs)} book directories: {book_dirs}")

            # Collect paths of direct children of book directories
            for book_dir in book_dirs:
                try:
                    logger.warning(f"[DEBUG] Scanning book_dir: {book_dir}")
                    for item in book_dir.iterdir():
                        if item.is_dir():
                            # Use container_path + relative path for sandbox paths
                            relative = item.relative_to(host_path)
                            # Ensure proper encoding for Chinese characters in path
                            relative_str = str(relative).replace("\\", "/")
                            container_path = mount.container_path.rstrip("/") + "/" + relative_str
                            tocs.add(container_path)
                            logger.warning(f"[DEBUG] Added TOC: {container_path}")
                except (PermissionError, OSError) as e:
                    logger.warning(f"[DEBUG] Error scanning book_dir {book_dir}: {e}")

        result = sorted(list(tocs))
        logger.warning(f"[DEBUG] Returning {len(result)} tocs: {result}")
        return result

    except Exception as e:
        logger.error(f"[DEBUG] Failed to scan novel tocs: {e}")
        import traceback

        logger.error(f"[DEBUG] Traceback: {traceback.format_exc()}")
        return []


@router.get("")
@router.get("/")
async def get_novel_tags():
    """
    Get all available novel TOC paths.

    Scans configured sandbox mount paths for book/books directories and returns
    all novel directory paths (container paths) as TOC enum values.
    """
    current_time = time.time()

    # Check cache validity
    if _novel_tags_cache["tags"] and current_time - _novel_tags_cache["last_updated"] < _novel_tags_cache["ttl"]:
        return {"tags": _novel_tags_cache["tags"]}

    # Scan and update cache
    tocs = _scan_novel_tocs()
    _novel_tags_cache["tags"] = tocs
    _novel_tags_cache["last_updated"] = current_time

    return {"tags": tocs}
