"""Loop-guard chat-model wrapper.

Wraps any LangChain :class:`BaseChatModel` instance so that its streamed
output is monitored by :class:`~deerflow.models.loop_detector.StreamLoopDetector`.
When the detector flags an infinite loop, the stream is terminated
gracefully — the partial output already streamed is preserved, a final
chunk with ``finish_reason="loop_detected"`` is emitted, and the generator
returns instead of letting the underlying model keep producing repetitive
content (which can run until ``max_tokens`` is exhausted).

Design notes
============
* **Dynamic subclassing** (``instance.__class__`` reassignment).  We do not
  want to subclass every concrete chat-model class (``ChatOpenAI``,
  ``VllmChatModel``, ``ChatAnthropic`` etc.) statically.  Creating a
  dynamic subclass at runtime lets ``isinstance`` and pydantic validation
  keep working: the subclass *is* the original class, plus the override
  methods of :class:`LoopGuardMixin`.

* **Per-call detector instances**.  Loop detection state must NOT leak
  between calls — that would cause a long conversation to trigger a false
  positive simply because the model used the same boilerplate twice.
  We instantiate a fresh ``StreamLoopDetector`` inside each ``_stream`` /
  ``_astream`` invocation.

* **Tool calls bypass detection**.  Tool-call deltas don't carry textual
  loops; their loop detection is already handled by
  ``LoopDetectionMiddleware`` (the existing tool-call hash check).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from deerflow.models.loop_detector import (
    LoopDetectionResult,
    LoopDetectorConfig,
    StreamLoopDetector,
)
from deerflow.runtime.cancel_registry import clear_cancel, get_cancel_event, is_cancelled

logger = logging.getLogger(__name__)


def _get_thread_id() -> str | None:
    try:
        from langgraph.config import get_config
        config = get_config()
        return config.get("configurable", {}).get("thread_id")
    except Exception:
        return None


async def _cancel_aware_anext(
    parent_gen: AsyncIterator,
    cancel_tid: str | None,
) -> Any | None:
    """Await the next chunk from *parent_gen*, but return ``None`` early
    if the run is cancelled while waiting.

    Detects cancellation via three mechanisms:

    1. **cancel_registry** — set by Gateway's ``RunManager.cancel()`` or
       by subagent executor when the parent signals stop.
    2. **asyncio.Task.cancel()** — used by the LangGraph server when the
       user clicks Stop.  The current task's cancelled flag is checked
       every poll cycle.
    3. **asyncio.CancelledError** — propagated when the task is actually
       cancelled mid-await.

    We use a polling approach (check every 0.5 s) instead of
    ``loop.run_in_executor(None, event.wait)`` because the latter leaks
    a thread-pool thread for every chunk: cancelling the ``Future`` does
    **not** interrupt a blocking ``threading.Event.wait()`` call.
    """
    if cancel_tid is None:
        try:
            return await parent_gen.__anext__()
        except StopAsyncIteration:
            return _STOP_ITERATION_SENTINEL

    cancel_event = get_cancel_event(cancel_tid)
    if cancel_event.is_set():
        return None

    current_task = asyncio.current_task()
    anext_task = asyncio.ensure_future(parent_gen.__anext__())
    try:
        while not cancel_event.is_set():
            if current_task is not None and current_task.cancelled():
                anext_task.cancel()
                try:
                    await anext_task
                except (asyncio.CancelledError, StopAsyncIteration):
                    pass
                return None
            done, _ = await asyncio.wait(
                {anext_task},
                timeout=0.5,
            )
            if done:
                break
        else:
            anext_task.cancel()
            try:
                await anext_task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            return None

        try:
            return anext_task.result()
        except StopAsyncIteration:
            return _STOP_ITERATION_SENTINEL
    except asyncio.CancelledError:
        anext_task.cancel()
        try:
            await anext_task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        raise


_STOP_ITERATION_SENTINEL = object()


# Sentinel attribute used so we never wrap the same instance twice.
_GUARD_MARKER_ATTR = "_deerflow_loop_guard_applied"

# Marker stored on the wrapped instance so the mixin can read its config.
_GUARD_CONFIG_ATTR = "_deerflow_loop_guard_config"

# Per-base-class cache of dynamic ``…WithLoopGuard`` subclasses so we do not
# leak a fresh class object each time ``wrap_model_with_loop_guard`` runs.
_GUARDED_CLASS_CACHE: dict[type, type] = {}


class LoopDetectedNotice:
    """Marker carried on the final chunk's ``response_metadata`` when a loop
    was detected.  Consumers (gateway, audit log) can react accordingly.
    """

    KEY = "deerflow_loop_detected"


def _extract_content_text(chunk: ChatGenerationChunk) -> str:
    """Extract visible reply text from ``message.content``.

    Two sources are considered:

    1. ``message.content`` (string) — plain assistant reply.
    2. ``message.content`` (list of content blocks) — multimodal models.
       Only ``{"type":"text","text":"..."}`` blocks are extracted;
       ``{"type":"thinking","thinking":"..."}`` blocks are **excluded** (they
       are reasoning content, handled by :func:`_extract_reasoning_text`).

    ``additional_kwargs["reasoning_content"]`` is also **excluded** — reasoning
    streams naturally contain structured lists and confirmation steps that
    trigger false positives in Layer B's clause-similarity detection.
    """
    message = getattr(chunk, "message", None)
    if message is None:
        return ""

    parts: list[str] = []

    content = getattr(message, "content", None)
    if isinstance(content, str):
        if content:
            parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Skip thinking/reasoning blocks — they go to _extract_reasoning_text
                block_type = block.get("type", "")
                if block_type == "thinking":
                    continue
                text = block.get("text") or block.get("content") or ""
                if isinstance(text, str) and text:
                    parts.append(text)

    return "".join(parts)


def _extract_reasoning_text(chunk: ChatGenerationChunk) -> str:
    """Extract reasoning / thinking text from a chunk.

    Two sources are considered:

    1. ``additional_kwargs["reasoning_content"]`` — OpenAI-compatible thinking
       models (DeepSeek, MiMo, Ollama) that stream reasoning in a separate
       field.
    2. ``message.content`` list entries with ``{"type":"thinking","thinking":"..."}``
       — Anthropic native thinking blocks.
    """
    message = getattr(chunk, "message", None)
    if message is None:
        return ""

    parts: list[str] = []

    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking")
                if isinstance(text, str) and text:
                    parts.append(text)

    additional_kwargs = getattr(message, "additional_kwargs", None) or {}
    reasoning_content = additional_kwargs.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content:
        parts.append(reasoning_content)

    return "".join(parts)


def _extract_tool_args(chunk: ChatGenerationChunk) -> str:
    """Extract raw argument deltas from ``tool_call_chunks``.

    Returns the concatenated ``args`` strings from all tool-call chunks
    in this chunk (empty string if none).
    """
    message = getattr(chunk, "message", None)
    if message is None:
        return ""

    parts: list[str] = []
    tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
    for tc in tool_call_chunks:
        if isinstance(tc, dict):
            args = tc.get("args")
        else:
            args = getattr(tc, "args", None)
        if isinstance(args, str) and args:
            parts.append(args)

    return "".join(parts)


# Minimum accumulated tool-call-args length before we start feeding them into
# the loop detector.  Short args (e.g. ``read_file(path="xxx.md")`` ≈ 30-50 chars)
# never cross this threshold, so they are silently ignored — preventing false
# positives on normal multi-tool workflows.  Long args (e.g.
# ``write_file(content="好的好的..." * 100)``) exceed it quickly and get
# monitored for repetition loops.
_TOOL_ARGS_ACCUMULATE_THRESHOLD = 150


def _emit_loop_detected_event(result: LoopDetectionResult) -> None:
    """Emit a custom stream event so the frontend can show a toast."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(
            {
                "type": "loop_detected",
                "layer": result.layer,
                "reason": result.reason,
                "repeat_count": result.repeat_count,
            }
        )
    except Exception:
        logger.debug("Failed to emit loop_detected event", exc_info=True)


def _build_loop_break_chunk(result: LoopDetectionResult) -> ChatGenerationChunk:
    """Build a final chunk that announces the loop break.

    The chunk carries:
    * a short visible suffix appended to ``content`` so the user sees why
      the model stopped;
    * ``response_metadata.finish_reason = "loop_detected"`` for tooling /
      logs that watch finish reasons;
    * ``response_metadata[LoopDetectedNotice.KEY]`` with detection details.
    """
    _emit_loop_detected_event(result)
    suffix = f"\n\n[deerflow] 检测到模型输出循环（{result.layer}），已自动终止：{result.reason}"
    message = AIMessageChunk(
        content=suffix,
        response_metadata={
            "finish_reason": "loop_detected",
            LoopDetectedNotice.KEY: {
                "layer": result.layer,
                "reason": result.reason,
                "repeat_count": result.repeat_count,
            },
        },
    )
    return ChatGenerationChunk(
        message=message,
        generation_info={"finish_reason": "loop_detected"},
    )


class LoopGuardMixin:
    """Mixin that overrides ``_stream`` / ``_astream`` with loop detection.

    Applied via dynamic subclassing in :func:`wrap_model_with_loop_guard`;
    not intended to be instantiated directly.

    Three detectors run in parallel:

    * **content_detector** (Layer A + B + C) — monitors the visible reply
      text and accumulated tool-call args.
    * **reasoning_detector** (Layer A + C) — monitors thinking / reasoning
      content.  Layer B is disabled because reasoning naturally contains
      structured lists and confirmation steps that trigger false positives.
      Layer C is enabled because large-block repetition in reasoning is
      just as pathological as in normal content.
    """

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        _cancel_tid = _get_thread_id()
        if not cfg.enabled:
            for chunk in super()._stream(messages, stop, run_manager, **kwargs):  # type: ignore[misc]
                if is_cancelled(_cancel_tid):
                    logger.info("LoopGuard: LLM sync stream cancelled for thread %s", _cancel_tid)
                    return
                yield chunk
            return

        content_detector = StreamLoopDetector(cfg)
        reasoning_cfg = LoopDetectorConfig(
            enabled=cfg.enabled,
            max_tail_chars=cfg.max_tail_chars,
            check_interval_chars=cfg.check_interval_chars,
            min_content_length=cfg.min_content_length,
            ngram_sizes=cfg.ngram_sizes,
            max_ngram_repeats=cfg.max_ngram_repeats,
            layer_a_only=True,
            paragraph_min_length=cfg.paragraph_min_length,
            paragraph_window=cfg.paragraph_window,
            max_paragraph_repeats=cfg.max_paragraph_repeats,
            paragraph_similarity_threshold=cfg.paragraph_similarity_threshold,
            paragraph_fuzzy_check=cfg.paragraph_fuzzy_check,
            paragraph_tail_chars=cfg.paragraph_tail_chars,
        )
        reasoning_detector = StreamLoopDetector(reasoning_cfg)
        tool_args_buf = ""
        _cancel_tid = _get_thread_id()
        for chunk in super()._stream(messages, stop, run_manager, **kwargs):  # type: ignore[misc]
            if is_cancelled(_cancel_tid):
                logger.info("LoopGuard: LLM sync stream cancelled for thread %s", _cancel_tid)
                return
            text = _extract_content_text(chunk)
            reasoning = _extract_reasoning_text(chunk)
            tool_args = _extract_tool_args(chunk)
            if tool_args:
                tool_args_buf += tool_args
                if len(tool_args_buf) >= _TOOL_ARGS_ACCUMULATE_THRESHOLD:
                    text += tool_args_buf
                    tool_args_buf = ""
            if text:
                result = content_detector.feed(text)
                if result.detected:
                    tail_preview = "".join(content_detector._tail)
                    logger.warning(
                        "LoopGuard: terminating sync stream — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                        result.reason,
                        content_detector.total_chars,
                        len(tail_preview),
                        tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                    )
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            if reasoning:
                result = reasoning_detector.feed(reasoning)
                if result.detected:
                    tail_preview = "".join(reasoning_detector._tail)
                    logger.warning(
                        "LoopGuard: terminating sync stream (reasoning) — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                        result.reason,
                        reasoning_detector.total_chars,
                        len(tail_preview),
                        tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                    )
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            yield chunk

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        _cancel_tid = _get_thread_id()
        if _cancel_tid is not None and is_cancelled(_cancel_tid):
            clear_cancel(_cancel_tid)
        parent_gen = super()._astream(messages, stop, run_manager, **kwargs)  # type: ignore[misc]
        try:
            if not cfg.enabled:
                while True:
                    chunk = await _cancel_aware_anext(parent_gen, _cancel_tid)
                    if chunk is None:
                        logger.info("LoopGuard: LLM async stream cancelled for thread %s", _cancel_tid)
                        return
                    if chunk is _STOP_ITERATION_SENTINEL:
                        return
                    yield chunk
                return

            content_detector = StreamLoopDetector(cfg)
            reasoning_cfg = LoopDetectorConfig(
                enabled=cfg.enabled,
                max_tail_chars=cfg.max_tail_chars,
                check_interval_chars=cfg.check_interval_chars,
                min_content_length=cfg.min_content_length,
                ngram_sizes=cfg.ngram_sizes,
                max_ngram_repeats=cfg.max_ngram_repeats,
                layer_a_only=True,
                paragraph_min_length=cfg.paragraph_min_length,
                paragraph_window=cfg.paragraph_window,
                max_paragraph_repeats=cfg.max_paragraph_repeats,
                paragraph_similarity_threshold=cfg.paragraph_similarity_threshold,
                paragraph_fuzzy_check=cfg.paragraph_fuzzy_check,
                paragraph_tail_chars=cfg.paragraph_tail_chars,
            )
            reasoning_detector = StreamLoopDetector(reasoning_cfg)
            tool_args_buf = ""
            while True:
                chunk = await _cancel_aware_anext(parent_gen, _cancel_tid)
                if chunk is None:
                    logger.info("LoopGuard: LLM async stream cancelled for thread %s", _cancel_tid)
                    return
                if chunk is _STOP_ITERATION_SENTINEL:
                    return
                text = _extract_content_text(chunk)
                reasoning = _extract_reasoning_text(chunk)
                tool_args = _extract_tool_args(chunk)
                if tool_args:
                    tool_args_buf += tool_args
                    if len(tool_args_buf) >= _TOOL_ARGS_ACCUMULATE_THRESHOLD:
                        text += tool_args_buf
                        tool_args_buf = ""
                if text:
                    result = content_detector.feed(text)
                    if result.detected:
                        tail_preview = "".join(content_detector._tail)
                        logger.warning(
                            "LoopGuard: terminating async stream — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                            result.reason,
                            content_detector.total_chars,
                            len(tail_preview),
                            tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                        )
                        yield chunk
                        yield _build_loop_break_chunk(result)
                        return
                if reasoning:
                    result = reasoning_detector.feed(reasoning)
                    if result.detected:
                        tail_preview = "".join(reasoning_detector._tail)
                        logger.warning(
                            "LoopGuard: terminating async stream (reasoning) — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                            result.reason,
                            reasoning_detector.total_chars,
                            len(tail_preview),
                            tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                        )
                        yield chunk
                        yield _build_loop_break_chunk(result)
                        return
                yield chunk
        finally:
            await parent_gen.aclose()


def wrap_model_with_loop_guard(model: BaseChatModel, config: LoopDetectorConfig | None = None) -> BaseChatModel:
    """Attach the loop-detection overrides to *model*.

    Args:
        model: The chat model instance to wrap.  Must be a
            :class:`BaseChatModel` (i.e. expose ``_stream`` / ``_astream``).
        config: Detector tuning.  Defaults to :class:`LoopDetectorConfig`'s
            defaults, which are conservative.

    Returns:
        The same *model* instance (mutated).  Idempotent — calling twice on
        the same instance updates the detector config without nesting the
        overrides.

    Implementation: we try the **dynamic-subclass** approach first because it
    keeps ``isinstance`` checks intact and lets debugging tools see the
    real class hierarchy.  Some hosts (pydantic v2 with frozen schemas,
    ``__slots__``-based models) reject ``__class__`` reassignment, in which
    case we fall back to **per-instance monkey-patching** of ``_stream`` and
    ``_astream``.  Both paths produce functionally identical behaviour.
    """
    cfg = config or LoopDetectorConfig()

    # Always (re)attach config — supports hot-config-reload paths that may
    # tweak thresholds without rebuilding the model.  Use ``object.__setattr__``
    # because BaseChatModel does not declare an ``extra='allow'`` model config.
    object.__setattr__(model, _GUARD_CONFIG_ATTR, cfg)

    if getattr(model, _GUARD_MARKER_ATTR, False):
        return model

    base_cls = type(model)
    wrap_strategy = "subclass"
    try:
        guarded_cls = _GUARDED_CLASS_CACHE.get(base_cls)
        if guarded_cls is None:
            guarded_cls = type(
                f"{base_cls.__name__}WithLoopGuard",
                (LoopGuardMixin, base_cls),
                {"__module__": __name__},
            )
            _GUARDED_CLASS_CACHE[base_cls] = guarded_cls
        model.__class__ = guarded_cls  # type: ignore[assignment]
    except (TypeError, ValueError):
        # ``__slots__`` / pydantic-frozen models reject class reassignment.
        # Fall back to per-instance method patching.
        _apply_instance_patches(model)
        wrap_strategy = "instance-patch"

    object.__setattr__(model, _GUARD_MARKER_ATTR, True)
    logger.debug(
        "LoopGuard enabled on %s via %s (max_ngram_repeats=%d, max_clause_repeats=%d, max_paragraph_repeats=%d)",
        base_cls.__name__,
        wrap_strategy,
        cfg.max_ngram_repeats,
        cfg.max_clause_repeats,
        cfg.max_paragraph_repeats,
    )
    return model


def _apply_instance_patches(model: BaseChatModel) -> None:
    """Fallback path: patch ``_stream`` / ``_astream`` on the instance directly.

    Used when ``model.__class__`` cannot be reassigned (e.g. the host class
    uses ``__slots__``).  We capture the originals via closures so the
    overrides can still call into them.
    """
    import types

    orig_stream = model._stream
    orig_astream = model._astream

    def _patched_stream(self, messages, stop=None, run_manager=None, **kwargs):
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        _cancel_tid = _get_thread_id()
        if not cfg.enabled:
            for chunk in orig_stream(messages, stop, run_manager, **kwargs):
                if is_cancelled(_cancel_tid):
                    logger.info("LoopGuard: LLM sync stream cancelled for thread %s", _cancel_tid)
                    return
                yield chunk
            return
        content_detector = StreamLoopDetector(cfg)
        reasoning_cfg = LoopDetectorConfig(
            enabled=cfg.enabled,
            max_tail_chars=cfg.max_tail_chars,
            check_interval_chars=cfg.check_interval_chars,
            min_content_length=cfg.min_content_length,
            ngram_sizes=cfg.ngram_sizes,
            max_ngram_repeats=cfg.max_ngram_repeats,
            layer_a_only=True,
            paragraph_min_length=cfg.paragraph_min_length,
            paragraph_window=cfg.paragraph_window,
            max_paragraph_repeats=cfg.max_paragraph_repeats,
            paragraph_similarity_threshold=cfg.paragraph_similarity_threshold,
            paragraph_fuzzy_check=cfg.paragraph_fuzzy_check,
            paragraph_tail_chars=cfg.paragraph_tail_chars,
        )
        reasoning_detector = StreamLoopDetector(reasoning_cfg)
        tool_args_buf = ""
        _cancel_tid = _get_thread_id()
        for chunk in orig_stream(messages, stop, run_manager, **kwargs):
            if is_cancelled(_cancel_tid):
                logger.info("LoopGuard: LLM sync stream cancelled for thread %s", _cancel_tid)
                return
            text = _extract_content_text(chunk)
            reasoning = _extract_reasoning_text(chunk)
            tool_args = _extract_tool_args(chunk)
            if tool_args:
                tool_args_buf += tool_args
                if len(tool_args_buf) >= _TOOL_ARGS_ACCUMULATE_THRESHOLD:
                    text += tool_args_buf
                    tool_args_buf = ""
            if text:
                result = content_detector.feed(text)
                if result.detected:
                    tail_preview = "".join(content_detector._tail)
                    logger.warning(
                        "LoopGuard: terminating sync stream — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                        result.reason,
                        content_detector.total_chars,
                        len(tail_preview),
                        tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                    )
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            if reasoning:
                result = reasoning_detector.feed(reasoning)
                if result.detected:
                    tail_preview = "".join(reasoning_detector._tail)
                    logger.warning(
                        "LoopGuard: terminating sync stream (reasoning) — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                        result.reason,
                        reasoning_detector.total_chars,
                        len(tail_preview),
                        tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                    )
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            yield chunk

    async def _patched_astream(self, messages, stop=None, run_manager=None, **kwargs):
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        _cancel_tid = _get_thread_id()
        if _cancel_tid is not None and is_cancelled(_cancel_tid):
            clear_cancel(_cancel_tid)
        parent_gen = orig_astream(messages, stop, run_manager, **kwargs)
        try:
            if not cfg.enabled:
                while True:
                    chunk = await _cancel_aware_anext(parent_gen, _cancel_tid)
                    if chunk is None:
                        logger.info("LoopGuard: LLM async stream cancelled for thread %s", _cancel_tid)
                        return
                    if chunk is _STOP_ITERATION_SENTINEL:
                        return
                    yield chunk
                return
            content_detector = StreamLoopDetector(cfg)
            reasoning_cfg = LoopDetectorConfig(
                enabled=cfg.enabled,
                max_tail_chars=cfg.max_tail_chars,
                check_interval_chars=cfg.check_interval_chars,
                min_content_length=cfg.min_content_length,
                ngram_sizes=cfg.ngram_sizes,
                max_ngram_repeats=cfg.max_ngram_repeats,
                layer_a_only=True,
                paragraph_min_length=cfg.paragraph_min_length,
                paragraph_window=cfg.paragraph_window,
                max_paragraph_repeats=cfg.max_paragraph_repeats,
                paragraph_similarity_threshold=cfg.paragraph_similarity_threshold,
                paragraph_fuzzy_check=cfg.paragraph_fuzzy_check,
                paragraph_tail_chars=cfg.paragraph_tail_chars,
            )
            reasoning_detector = StreamLoopDetector(reasoning_cfg)
            tool_args_buf = ""
            while True:
                chunk = await _cancel_aware_anext(parent_gen, _cancel_tid)
                if chunk is None:
                    logger.info("LoopGuard: LLM async stream cancelled for thread %s", _cancel_tid)
                    return
                if chunk is _STOP_ITERATION_SENTINEL:
                    return
                text = _extract_content_text(chunk)
                reasoning = _extract_reasoning_text(chunk)
                tool_args = _extract_tool_args(chunk)
                if tool_args:
                    tool_args_buf += tool_args
                    if len(tool_args_buf) >= _TOOL_ARGS_ACCUMULATE_THRESHOLD:
                        text += tool_args_buf
                        tool_args_buf = ""
                if text:
                    result = content_detector.feed(text)
                    if result.detected:
                        tail_preview = "".join(content_detector._tail)
                        logger.warning(
                            "LoopGuard: terminating async stream — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                            result.reason,
                            content_detector.total_chars,
                            len(tail_preview),
                            tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                        )
                        yield chunk
                        yield _build_loop_break_chunk(result)
                        return
                if reasoning:
                    result = reasoning_detector.feed(reasoning)
                    if result.detected:
                        tail_preview = "".join(reasoning_detector._tail)
                        logger.warning(
                            "LoopGuard: terminating async stream (reasoning) — %s (total chars=%d)\nTail content (last %d chars):\n%s",
                            result.reason,
                            reasoning_detector.total_chars,
                            len(tail_preview),
                            tail_preview[-2000:] if len(tail_preview) > 2000 else tail_preview,
                        )
                        yield chunk
                        yield _build_loop_break_chunk(result)
                        return
                yield chunk
        finally:
            await parent_gen.aclose()

    object.__setattr__(model, "_stream", types.MethodType(_patched_stream, model))
    object.__setattr__(model, "_astream", types.MethodType(_patched_astream, model))


__all__ = [
    "LoopDetectedNotice",
    "LoopGuardMixin",
    "wrap_model_with_loop_guard",
]
