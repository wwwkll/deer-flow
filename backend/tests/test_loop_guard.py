"""Integration tests for ``deerflow.models.loop_guard``.

We build a tiny fake :class:`BaseChatModel` whose ``_astream`` /``_stream``
yield a configurable sequence of chunks, then verify that wrapping it with
:func:`wrap_model_with_loop_guard` causes the stream to terminate early
when the chunks form a loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from deerflow.models.loop_detector import LoopDetectorConfig
from deerflow.models.loop_guard import LoopDetectedNotice, wrap_model_with_loop_guard


# ---------------------------------------------------------------------------
# Fake chat model
# ---------------------------------------------------------------------------


class FakeStreamingChatModel(BaseChatModel):
    """Streams a preset list of text chunks and never calls a real provider.

    Pydantic v2-friendly: subclass of :class:`BaseChatModel`, declares
    ``chunks`` as a regular field.
    """

    chunks: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-streaming"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        raise NotImplementedError("fake model only supports streaming")

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for piece in self.chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for piece in self.chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looping_chunks(prefix: str, phrase: str, count: int) -> list[str]:
    """Produce a chunk list = prefix + phrase repeated ``count`` times.

    Chunks are intentionally short (~10 chars) to mimic SSE delta granularity.
    """
    body = prefix + phrase * count
    return [body[i : i + 10] for i in range(0, len(body), 10)]


def _collect_text(chunks: list[ChatGenerationChunk]) -> str:
    return "".join(c.message.content for c in chunks)


# ---------------------------------------------------------------------------
# Tests — sync path
# ---------------------------------------------------------------------------


def test_sync_stream_aborts_on_short_phrase_loop():
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)
    model = FakeStreamingChatModel(chunks=_looping_chunks("我开始回答你的问题：", "好的好的", 80))
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))  # noqa: SLF001 — internal API by design
    text = _collect_text(collected)

    # The final chunk should carry the loop-detected notice.
    last = collected[-1]
    metadata = last.message.response_metadata or {}
    assert metadata.get(LoopDetectedNotice.KEY), f"final chunk missing loop notice: {metadata}"
    # The aborted stream is shorter than the full repeating chunk list.
    full_text = "".join(model.chunks)
    assert len(text) < len(full_text), "loop guard did not truncate the stream"


def test_sync_stream_passes_through_when_no_loop():
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10)
    chunks = [
        "今天我们来讨论一下机器学习的几个核心概念。",
        "首先是监督学习，它依赖大量带标签的数据。",
        "其次是无监督学习，主要任务是发现数据本身的结构。",
        "最后是强化学习，关注智能体在环境中的决策。",
    ]
    model = FakeStreamingChatModel(chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    text = _collect_text(collected)
    assert text == "".join(chunks)
    # No notice on the last chunk.
    last_meta = collected[-1].message.response_metadata or {}
    assert LoopDetectedNotice.KEY not in last_meta


# ---------------------------------------------------------------------------
# Tests — async path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_stream_aborts_on_templated_loop():
    cfg = LoopDetectorConfig(
        min_content_length=80,
        check_interval_chars=10,
        max_ngram_repeats=20,  # weaken Layer A so we exercise Layer B
        max_clause_repeats=4,
    )
    prefix = "让我帮你算一算未来几天的安排。"
    body = (
        "今天是周一，"
        "明天是周二，"
        "三天后是周三，"
        "四天后是周四，"
        "五天后是周五，"
        "六天后是周六，"
        "七天后是周日，"
        "八天后又是周一，"
    )
    text = prefix + body * 3
    chunks = [text[i : i + 8] for i in range(0, len(text), 8)]

    model = FakeStreamingChatModel(chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = []
    async for chunk in model._astream([]):
        collected.append(chunk)

    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "async stream did not raise loop notice"

    # The stream must have aborted before exhausting all original chunks.
    # ``collected[-1]`` is the loop-detected notice chunk appended by the
    # guard; everything before it came from the underlying model.
    # We measure truncation in *chunk count* rather than total text length:
    # the appended notice itself is ~80 chars of human-readable Chinese, so
    # comparing total character counts can falsely "grow" the stream even
    # though it was actually aborted early.
    original_streamed = collected[:-1]
    assert len(original_streamed) < len(chunks), (
        f"stream was not truncated: yielded {len(original_streamed)} original "
        f"chunks out of {len(chunks)} total"
    )


@pytest.mark.asyncio
async def test_async_stream_disabled_passes_through():
    cfg = LoopDetectorConfig(enabled=False)
    chunks = _looping_chunks("", "好的", 200)
    model = FakeStreamingChatModel(chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = []
    async for chunk in model._astream([]):
        collected.append(chunk)
    assert _collect_text(collected) == "".join(chunks)


# ---------------------------------------------------------------------------
# Tests — wrapper idempotency
# ---------------------------------------------------------------------------


def test_wrap_is_idempotent():
    cfg = LoopDetectorConfig()
    model = FakeStreamingChatModel(chunks=["a"])
    first = wrap_model_with_loop_guard(model, cfg)
    cls_after_first = type(first)
    second = wrap_model_with_loop_guard(model, cfg)
    assert type(second) is cls_after_first, "wrap should not nest the mixin"


def test_wrap_updates_config_on_subsequent_calls():
    """Second wrap should refresh thresholds without altering the class."""
    model = FakeStreamingChatModel(chunks=["a"])
    wrap_model_with_loop_guard(model, LoopDetectorConfig(max_ngram_repeats=10))
    wrap_model_with_loop_guard(model, LoopDetectorConfig(max_ngram_repeats=3))

    # Access internal config attr via getattr to verify update happened.
    cfg = getattr(model, "_deerflow_loop_guard_config")
    assert cfg.max_ngram_repeats == 3


# ---------------------------------------------------------------------------
# Tests — alternate chunk shapes (content-list, tool-call args, emoji)
# ---------------------------------------------------------------------------


from langchain_core.messages.tool import tool_call_chunk  # noqa: E402


class FakeToolCallStreamingModel(BaseChatModel):
    """Streams chunks whose payload lives in ``tool_call_chunks.args``.

    Mimics what LangChain produces when an LLM is generating a tool call —
    no ``content`` text, just JSON deltas under ``tool_call_chunks``.
    """

    args_chunks: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-toolcall-streaming"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        raise NotImplementedError

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for piece in self.args_chunks:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[tool_call_chunk(name="write_file", args=piece, id="call_1", index=0)],
                )
            )

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for piece in self.args_chunks:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[tool_call_chunk(name="write_file", args=piece, id="call_1", index=0)],
                )
            )


def test_loop_in_tool_call_args_is_detected():
    """Real production case: small model calls ``write_file(content=...)``
    and gets stuck repeating the same phrase inside the JSON ``content``
    value.  The repetitive chars only live in tool_call_chunks.args, never
    in message.content — yet the guard must still abort the stream."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    # Simulate the streamed JSON args of write_file with a repetitive content value
    args_text = '{"path": "out.md", "content": "' + "好的好的" * 80 + '"}'
    args_chunks = [args_text[i : i + 10] for i in range(0, len(args_text), 10)]

    model = FakeToolCallStreamingModel(args_chunks=args_chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))

    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "loop in tool_call args was not detected"
    # Verify the stream was truncated (didn't yield all original chunks)
    original_streamed = collected[:-1]
    assert len(original_streamed) < len(args_chunks)


@pytest.mark.asyncio
async def test_loop_in_tool_call_args_async():
    """Async variant of the tool-call args loop detection."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    args_text = '{"path": "log.txt", "content": "' + "I am sorry " * 60 + '"}'
    args_chunks = [args_text[i : i + 12] for i in range(0, len(args_text), 12)]

    model = FakeToolCallStreamingModel(args_chunks=args_chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = []
    async for chunk in model._astream([]):
        collected.append(chunk)

    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "async tool_call args loop not detected"


def test_loop_in_emoji_only_stream_is_detected():
    """Pure-emoji loops must be caught — emoji are single Unicode codepoints
    in Python and the n-gram algorithm is codepoint-based, so this should
    work without any special-case logic."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    # Each emoji is 1 codepoint; 100 emoji = 100 codepoints
    prefix = "Sure, here we go: "
    body = "👍" * 200
    chunks = [(prefix + body)[i : i + 10] for i in range(0, len(prefix + body), 10)]

    model = FakeStreamingChatModel(chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "pure emoji loop not detected"


def test_loop_in_mixed_emoji_phrase_is_detected():
    """Mixed text + emoji loop (very common with small RP / chat models)."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    prefix = "好的，我来帮你："
    phrase = "好的👍"  # 3 codepoints
    body = phrase * 100
    chunks = [(prefix + body)[i : i + 10] for i in range(0, len(prefix + body), 10)]

    model = FakeStreamingChatModel(chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "mixed emoji loop not detected"


class FakeContentListStreamingModel(BaseChatModel):
    """Streams chunks whose ``message.content`` is a list of blocks.

    Mimics Anthropic-with-thinking or Vertex Gemini multimodal output.
    """

    blocks: list[list[dict]] = []

    @property
    def _llm_type(self) -> str:
        return "fake-content-list-streaming"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        raise NotImplementedError

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for block_list in self.blocks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=block_list))

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for block_list in self.blocks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=block_list))


def test_loop_in_content_block_list_is_detected():
    """When content is a list of text blocks (Anthropic/Gemini style),
    the guard must still aggregate the text inside each block."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    # Simulate streamed content blocks, each containing a small text fragment
    intro = "Working on it: "
    body = "好的好的" * 80
    full_text = intro + body
    blocks = [[{"type": "text", "text": full_text[i : i + 10]}] for i in range(0, len(full_text), 10)]

    model = FakeContentListStreamingModel(blocks=blocks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "content-block-list loop not detected"
