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

logger = logging.getLogger(__name__)


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


def _extract_text(chunk: ChatGenerationChunk) -> str:
    """Pull all newly-emitted text out of a streamed chunk.

    Three sources must be considered — small models can loop in any of them:

    1. ``message.content`` (string)
         — the common case, plain assistant reply.
    2. ``message.content`` (list of content blocks)
         — Anthropic with thinking, Vertex Gemini, multimodal models.
    3. ``message.tool_call_chunks`` / ``additional_kwargs.tool_calls``
         — the model is **writing a tool call** whose ``arguments`` field is
         being streamed.  Real production case: a small model calls
         ``write_file(content="...")`` and loops inside the ``content``
         JSON value.  The chars never appear in ``message.content`` so we
         must mine them out of the tool-call delta here.

    All extracted text is concatenated.  We do **not** maintain separate
    detectors per source because in practice a model is either in "text"
    mode or "tool call" mode for any given stream — the merged stream
    preserves the loop signal correctly.
    """
    message = getattr(chunk, "message", None)
    if message is None:
        return ""

    parts: list[str] = []

    # --- Source 1 & 2: assistant content ---
    content = getattr(message, "content", None)
    if isinstance(content, str):
        if content:
            parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Common shapes: {"type":"text","text":"..."},
                # {"type":"input_text","text":"..."}, {"content":"..."}
                text = block.get("text") or block.get("content") or ""
                if isinstance(text, str) and text:
                    parts.append(text)

    # --- Source 3: tool-call argument deltas ---
    # LangChain exposes per-chunk increments via ``tool_call_chunks`` on
    # AIMessageChunk.  Each entry is a dict-like with an ``args`` (str)
    # field containing the JSON arguments delta for that call.
    tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
    for tc in tool_call_chunks:
        if isinstance(tc, dict):
            args = tc.get("args")
        else:
            args = getattr(tc, "args", None)
        if isinstance(args, str) and args:
            parts.append(args)

    return "".join(parts)


def _build_loop_break_chunk(result: LoopDetectionResult) -> ChatGenerationChunk:
    """Build a final chunk that announces the loop break.

    The chunk carries:
    * a short visible suffix appended to ``content`` so the user sees why
      the model stopped;
    * ``response_metadata.finish_reason = "loop_detected"`` for tooling /
      logs that watch finish reasons;
    * ``response_metadata[LoopDetectedNotice.KEY]`` with detection details.
    """
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
    """

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        if not cfg.enabled:
            yield from super()._stream(messages, stop, run_manager, **kwargs)  # type: ignore[misc]
            return

        detector = StreamLoopDetector(cfg)
        for chunk in super()._stream(messages, stop, run_manager, **kwargs):  # type: ignore[misc]
            text = _extract_text(chunk)
            if text:
                result = detector.feed(text)
                if result.detected:
                    logger.warning(
                        "LoopGuard: terminating sync stream — %s (total chars=%d)",
                        result.reason,
                        detector.total_chars,
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
        if not cfg.enabled:
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):  # type: ignore[misc]
                yield chunk
            return

        detector = StreamLoopDetector(cfg)
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):  # type: ignore[misc]
            text = _extract_text(chunk)
            if text:
                result = detector.feed(text)
                if result.detected:
                    logger.warning(
                        "LoopGuard: terminating async stream — %s (total chars=%d)",
                        result.reason,
                        detector.total_chars,
                    )
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            yield chunk


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

    if not cfg.enabled:
        # Mark anyway so downstream code can detect "guard considered" even
        # if currently disabled — avoids unnecessary class reassignment.
        object.__setattr__(model, _GUARD_MARKER_ATTR, True)
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
        "LoopGuard enabled on %s via %s (max_ngram_repeats=%d, max_clause_repeats=%d)",
        base_cls.__name__,
        wrap_strategy,
        cfg.max_ngram_repeats,
        cfg.max_clause_repeats,
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
        if not cfg.enabled:
            yield from orig_stream(messages, stop, run_manager, **kwargs)
            return
        detector = StreamLoopDetector(cfg)
        for chunk in orig_stream(messages, stop, run_manager, **kwargs):
            text = _extract_text(chunk)
            if text:
                result = detector.feed(text)
                if result.detected:
                    logger.warning("LoopGuard: terminating sync stream — %s", result.reason)
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            yield chunk

    async def _patched_astream(self, messages, stop=None, run_manager=None, **kwargs):
        cfg: LoopDetectorConfig = getattr(self, _GUARD_CONFIG_ATTR, LoopDetectorConfig())
        if not cfg.enabled:
            async for chunk in orig_astream(messages, stop, run_manager, **kwargs):
                yield chunk
            return
        detector = StreamLoopDetector(cfg)
        async for chunk in orig_astream(messages, stop, run_manager, **kwargs):
            text = _extract_text(chunk)
            if text:
                result = detector.feed(text)
                if result.detected:
                    logger.warning("LoopGuard: terminating async stream — %s", result.reason)
                    yield chunk
                    yield _build_loop_break_chunk(result)
                    return
            yield chunk

    object.__setattr__(model, "_stream", types.MethodType(_patched_stream, model))
    object.__setattr__(model, "_astream", types.MethodType(_patched_astream, model))


__all__ = [
    "LoopDetectedNotice",
    "LoopGuardMixin",
    "wrap_model_with_loop_guard",
]
