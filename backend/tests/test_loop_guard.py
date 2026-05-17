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


def test_short_tool_call_args_not_monitored():
    """Short tool-call args (e.g. read_file path) stay below the 150-char
    accumulation threshold and are never fed to the detector."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    # Simulate several short read_file calls — each args is ~40 chars, well under 150
    short_args = [
        '{"path": "chapter-01.md"}',
        '{"path": "chapter-02.md"}',
        '{"path": "chapter-03.md"}',
        '{"path": "chapter-04.md"}',
        '{"path": "chapter-05.md"}',
    ]

    model = FakeToolCallStreamingModel(args_chunks=short_args)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))

    assert len(collected) == len(short_args)
    for chunk in collected:
        assert not (chunk.message.response_metadata or {}).get(LoopDetectedNotice.KEY)


def test_long_tool_call_args_loop_is_detected():
    """Long tool-call args (e.g. write_file with repetitive content) exceed
    the 150-char threshold and ARE monitored for loops."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    # Simulate write_file with a long looping content value (500+ chars total)
    args_text = '{"path": "out.md", "content": "' + "好的好的" * 80 + '"}'
    args_chunks = [args_text[i : i + 10] for i in range(0, len(args_text), 10)]

    model = FakeToolCallStreamingModel(args_chunks=args_chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))

    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "long tool_call args loop was not detected"
    original_streamed = collected[:-1]
    assert len(original_streamed) < len(args_chunks)


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


class FakeReasoningContentStreamingModel(BaseChatModel):
    """Streams chunks whose thinking content is in ``additional_kwargs.reasoning_content``.

    Mimics OpenAI-compatible thinking models (MiMo, DeepSeek, Ollama) that
    stream reasoning in a separate field rather than inside ``content``.
    """

    reasoning_chunks: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "fake-reasoning-streaming"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:  # type: ignore[override]
        raise NotImplementedError

    def _stream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for piece in self.reasoning_chunks:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content": piece},
                )
            )


def test_loop_in_reasoning_content_is_detected():
    """When the model loops inside ``reasoning_content`` (MiMo/DeepSeek style),
    the guard must detect it.  Reasoning uses a stricter threshold (≥80 repeats)
    so we need enough data to trigger it."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    reasoning_text = "好的好的" * 500
    chunks = [reasoning_text[i : i + 10] for i in range(0, len(reasoning_text), 10)]

    model = FakeReasoningContentStreamingModel(reasoning_chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "reasoning_content loop not detected"


def test_loop_in_anthropic_thinking_block_is_detected():
    """When the model loops inside an Anthropic-style thinking block
    (``{"type": "thinking", "thinking": "..."}``), the guard must detect it.
    Reasoning uses a stricter threshold (≥80 repeats) so we need enough data."""
    cfg = LoopDetectorConfig(min_content_length=50, check_interval_chars=10, max_ngram_repeats=4)

    thinking_text = "好的好的" * 500
    full_text = "Let me think. " + thinking_text
    blocks = [[{"type": "thinking", "thinking": full_text[i : i + 10]}] for i in range(0, len(full_text), 10)]

    model = FakeContentListStreamingModel(blocks=blocks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "Anthropic thinking-block loop not detected"


def test_reasoning_structured_list_not_false_positive():
    """Reasoning content with structured lists (e.g. 'book name, genre, platform')
    must NOT trigger Layer B clause-similarity detection.

    This is the exact bug scenario: mimo-v2.5-pro reasoning about what to ask
    the user produces natural list-like patterns that were falsely detected as
    loops before the reasoning/content split fix.
    """
    cfg = LoopDetectorConfig(
        min_content_length=50,
        check_interval_chars=10,
        max_ngram_repeats=4,
        max_clause_repeats=4,
    )

    # Simulate mimo-v2.5-pro reasoning with structured lists.
    # Carefully avoid n-gram repetition (Layer A) to isolate the Layer B test.
    reasoning_parts = [
        "The user wants to create a new novel that captures the essence and style of a popular classical novel. ",
        "They emphasize capturing the spirit, not copying surface-level elements. ",
        "Let me follow the workflow for creating a new novel. ",
        "First, I should ask for: book name, genre, one-sentence concept, platform. ",
        "The user has already provided a detailed creative brief, ",
        "but they have not specified the book name yet. ",
        "I should gather additional information before proceeding further. ",
        "Let me prepare a comprehensive list of questions for them. ",
    ]
    reasoning_text = "".join(reasoning_parts)
    chunks = [reasoning_text[i : i + 10] for i in range(0, len(reasoning_text), 10)]

    model = FakeReasoningContentStreamingModel(reasoning_chunks=chunks)
    wrap_model_with_loop_guard(model, cfg)

    collected = list(model._stream([]))
    # All chunks should pass through — no loop detection on structured reasoning
    assert len(collected) == len(chunks)
    for chunk in collected:
        assert not (chunk.message.response_metadata or {}).get(LoopDetectedNotice.KEY)


def test_content_clause_detection_still_works():
    """Content (non-reasoning) text must still trigger Layer B clause detection.

    Verifies that the content/reasoning split doesn't break normal content
    loop detection."""
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

    collected = list(model._stream([]))
    last_meta = collected[-1].message.response_metadata or {}
    assert last_meta.get(LoopDetectedNotice.KEY), "content clause detection broken"
