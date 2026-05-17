"""Category management endpoints for novel-based thread grouping."""

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.deps import get_checkpointer, get_store
from app.gateway.path_utils import resolve_mount_virtual_path
from app.gateway.routers.threads import THREADS_NS, _delete_thread_data
from deerflow.global_variables.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryClearResponse(BaseModel):
    success: bool
    message: str
    deleted_count: int


class CategoryDeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_threads: int
    novel_path: str | None = None


def _get_threads_by_category(category_name: str) -> list[str]:
    novel_tocs = get_storage().load_novel_tocs()
    thread_ids = []
    for thread_id, toc_path in novel_tocs.items():
        segments = toc_path.split("/")
        if segments and segments[-1] == category_name:
            thread_ids.append(thread_id)
    return thread_ids


def _get_novel_path_by_category(category_name: str) -> str | None:
    novel_tocs = get_storage().load_novel_tocs()
    for toc_path in novel_tocs.values():
        segments = toc_path.split("/")
        if segments and segments[-1] == category_name:
            return toc_path
    return None


async def _delete_thread_full(thread_id: str, request: Request) -> bool:
    try:
        _delete_thread_data(thread_id)

        store = get_store(request)
        if store is not None:
            try:
                await store.adelete(THREADS_NS, thread_id)
            except Exception:
                logger.debug("Could not delete store record for thread %s (not critical)", thread_id)

        checkpointer = getattr(request.app.state, "checkpointer", None)
        if checkpointer is not None:
            try:
                if hasattr(checkpointer, "adelete_thread"):
                    await checkpointer.adelete_thread(thread_id)
            except Exception:
                logger.debug("Could not delete checkpoints for thread %s (not critical)", thread_id)

        try:
            get_storage().delete_all_by_thread(thread_id)
        except Exception:
            logger.debug("Could not delete global variables for thread %s (not critical)", thread_id)

        return True
    except Exception as e:
        logger.error("Failed to delete thread %s: %s", thread_id, e)
        return False


@router.post("/{category_name}/clear", response_model=CategoryClearResponse)
async def clear_category_threads(category_name: str, request: Request) -> CategoryClearResponse:
    if category_name == "__undefined__":
        raise HTTPException(status_code=400, detail="Cannot clear undefined category")

    thread_ids = _get_threads_by_category(category_name)
    if not thread_ids:
        return CategoryClearResponse(
            success=True,
            message=f"No threads found in category '{category_name}'",
            deleted_count=0,
        )

    deleted_count = 0
    for thread_id in thread_ids:
        ok = await _delete_thread_full(thread_id, request)
        if ok:
            deleted_count += 1

    return CategoryClearResponse(
        success=True,
        message=f"Cleared {deleted_count} threads from category '{category_name}'",
        deleted_count=deleted_count,
    )


@router.delete("/{category_name}", response_model=CategoryDeleteResponse)
async def delete_category(category_name: str, request: Request) -> CategoryDeleteResponse:
    if category_name == "__undefined__":
        raise HTTPException(status_code=400, detail="Cannot delete undefined category")

    novel_path = _get_novel_path_by_category(category_name)

    thread_ids = _get_threads_by_category(category_name)
    deleted_threads = 0
    for thread_id in thread_ids:
        ok = await _delete_thread_full(thread_id, request)
        if ok:
            deleted_threads += 1

    deleted_path = None
    if novel_path:
        try:
            host_path = resolve_mount_virtual_path(novel_path)
            if host_path.exists():
                shutil.rmtree(str(host_path))
                deleted_path = novel_path
                logger.info("Deleted novel directory: %s (host: %s)", novel_path, host_path)
            else:
                logger.warning("Novel directory does not exist: %s (host: %s)", novel_path, host_path)
        except HTTPException:
            logger.warning("Cannot resolve novel path for deletion: %s", novel_path)
        except Exception as e:
            logger.error("Failed to delete novel directory %s: %s", novel_path, e)

    return CategoryDeleteResponse(
        success=True,
        message=f"Deleted category '{category_name}' with {deleted_threads} threads",
        deleted_threads=deleted_threads,
        novel_path=deleted_path,
    )
