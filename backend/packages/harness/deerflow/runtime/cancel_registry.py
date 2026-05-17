"""Global cancellation registry for runs.

Provides a cross-layer mechanism to signal run cancellation from the
Gateway/API layer down to the LLM streaming layer.  This bridges the
gap between the RunManager's ``abort_event`` (checked at
``agent.astream()`` iteration boundaries) and the LLM's
``_astream()``/``_stream()`` methods (checked at each chunk boundary).

Two signaling backends are supported:

* **In-process** (default): A thread-safe ``set`` of cancelled thread IDs.
  Used when the Gateway and the agent run in the same process.

* **File-based**: A flag file under ``temp/cancel/<thread_id>``.
  Used when the agent runs in a separate process (e.g. the LangGraph
  dev server).  File checks are cached for up to 0.5 s to avoid
  excessive I/O.

Additionally, a **threading.Event** per thread allows the LLM streaming
layer to use ``asyncio.wait()`` to interrupt an in-progress ``await``
on the next LLM chunk — closing the underlying HTTP connection to the
model server (LM Studio, vLLM, etc.) immediately rather than waiting
for the next chunk to arrive.

We use ``threading.Event`` instead of ``asyncio.Event`` because the
LangGraph server runs agents in a ``ThreadPoolExecutor`` where each
thread has its own event loop.  An ``asyncio.Event`` created in one
loop cannot be awaited from another, which causes ``RuntimeError:
is bound to a different event loop``.  ``threading.Event`` is
loop-agnostic and can be safely shared across threads and event loops.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cancelled_threads: set[str] = set()

_cancel_events_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}

_CANCEL_DIR = Path(os.environ.get("DEERFLOW_TEMP_DIR", "temp")) / "cancel"

_file_check_cache: dict[str, tuple[float, bool]] = {}
_FILE_CACHE_TTL = 0.5


def request_cancel(thread_id: str) -> None:
    """Mark a thread's run as cancelled.

    Sets the in-process flag, the file-based flag, **and** the
    per-thread ``threading.Event`` so that any coroutine using
    :func:`get_cancel_event` with ``asyncio.wait()`` will wake up
    immediately.
    """
    with _lock:
        _cancelled_threads.add(thread_id)
    _write_cancel_file(thread_id)
    event = _get_or_create_cancel_event(thread_id)
    event.set()
    logger.info("Cancel registry: thread %s marked as cancelled", thread_id)


def is_cancelled(thread_id: str | None) -> bool:
    """Check if a thread's run has been cancelled.

    Checks the in-process set first (O(1), no I/O).  Falls back to
    the file-based flag with a time-based cache to limit disk access.
    """
    if thread_id is None:
        return False
    with _lock:
        if thread_id in _cancelled_threads:
            return True
    return _check_cancel_file(thread_id)


def get_cancel_event(thread_id: str) -> threading.Event:
    """Return the ``threading.Event`` for *thread_id*.

    The event is set by :func:`request_cancel` and cleared by
    :func:`clear_cancel`.  Use it with ``loop.run_in_executor`` to
    interrupt an in-progress ``await`` on the next LLM chunk::

        cancel_event = get_cancel_event(thread_id)
        anext_task = asyncio.ensure_future(gen.__anext__())
        cancel_task = asyncio.ensure_future(
            loop.run_in_executor(None, cancel_event.wait)
        )
        done, pending = await asyncio.wait(
            {anext_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    """
    return _get_or_create_cancel_event(thread_id)


def clear_cancel(thread_id: str) -> None:
    """Clear the cancellation flag for a thread.

    Called after a run completes (success, error, or cancellation) so
    that the registry does not grow unboundedly.
    """
    with _lock:
        _cancelled_threads.discard(thread_id)
    _remove_cancel_file(thread_id)
    with _cancel_events_lock:
        event = _cancel_events.pop(thread_id, None)
    if event is not None:
        event.clear()


def _get_or_create_cancel_event(thread_id: str) -> threading.Event:
    with _cancel_events_lock:
        if thread_id not in _cancel_events:
            _cancel_events[thread_id] = threading.Event()
        return _cancel_events[thread_id]


def _write_cancel_file(thread_id: str) -> None:
    try:
        _CANCEL_DIR.mkdir(parents=True, exist_ok=True)
        (_CANCEL_DIR / thread_id).write_text("1")
    except Exception:
        logger.debug("Failed to write cancel file for thread %s", thread_id, exc_info=True)


def _check_cancel_file(thread_id: str) -> bool:
    now = time.monotonic()
    cached = _file_check_cache.get(thread_id)
    if cached is not None and (now - cached[0]) < _FILE_CACHE_TTL:
        return cached[1]
    exists = (_CANCEL_DIR / thread_id).is_file()
    _file_check_cache[thread_id] = (now, exists)
    return exists


def _remove_cancel_file(thread_id: str) -> None:
    try:
        path = _CANCEL_DIR / thread_id
        if path.is_file():
            path.unlink()
    except Exception:
        logger.debug("Failed to remove cancel file for thread %s", thread_id, exc_info=True)
    _file_check_cache.pop(thread_id, None)
