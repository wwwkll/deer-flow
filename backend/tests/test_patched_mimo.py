"""Tests for deerflow.models.patched_mimo.PatchedMiMoChatOpenAI.

Covers:
- reasoning_content restoration in _get_request_payload (single and multi-turn)
- Positional fallback when message counts differ
- No-op when no reasoning_content present
- reasoning_content capture from non-streaming responses (_create_chat_result)
- reasoning_content capture from streaming deltas (_convert_chunk_to_generation_chunk)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def _make_model(**kwargs):
    from deerflow.models.patched_mimo import PatchedMiMoChatOpenAI

    return PatchedMiMoChatOpenAI(
        model="mimo-v2.5",
        api_key="test-key",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        **kwargs,
    )


def _make_payload_message(role: str, content: str | None = None, tool_calls: list | None = None) -> dict:
    msg: dict = {"role": role, "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


# ---------------------------------------------------------------------------
# reasoning_content preservation in _get_request_payload
# ---------------------------------------------------------------------------


def test_reasoning_content_injected_into_assistant_message():
    model = _make_model()

    human = HumanMessage(content="What is 2+2?")
    ai = AIMessage(
        content="4",
        additional_kwargs={"reasoning_content": "Let me think: 2+2=4"},
    )

    base_payload = {
        "messages": [
            _make_payload_message("user", "What is 2+2?"),
            _make_payload_message("assistant", "4"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "Let me think: 2+2=4"


def test_missing_reasoning_content_falls_back_to_empty_string():
    model = _make_model()

    human = HumanMessage(content="hello")
    ai = AIMessage(content="hi", additional_kwargs={})

    base_payload = {
        "messages": [
            _make_payload_message("user", "hello"),
            _make_payload_message("assistant", "hi"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == ""


def test_reasoning_content_multi_turn():
    model = _make_model()

    human1 = HumanMessage(content="Step 1?")
    ai1 = AIMessage(content="A1", additional_kwargs={"reasoning_content": "Thought1"})
    human2 = HumanMessage(content="Step 2?")
    ai2 = AIMessage(content="A2", additional_kwargs={"reasoning_content": "Thought2"})

    base_payload = {
        "messages": [
            _make_payload_message("user", "Step 1?"),
            _make_payload_message("assistant", "A1"),
            _make_payload_message("user", "Step 2?"),
            _make_payload_message("assistant", "A2"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human1, ai1, human2, ai2])
            payload = model._get_request_payload([human1, ai1, human2, ai2])

    assistant_msgs = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant_msgs[0]["reasoning_content"] == "Thought1"
    assert assistant_msgs[1]["reasoning_content"] == "Thought2"


def test_positional_fallback_when_count_differs():
    model = _make_model()

    human = HumanMessage(content="hi")
    ai = AIMessage(content="hello", additional_kwargs={"reasoning_content": "My reasoning"})

    extra_system = _make_payload_message("system", "You are helpful.")
    base_payload = {
        "messages": [
            extra_system,
            _make_payload_message("user", "hi"),
            _make_payload_message("assistant", "hello"),
        ]
    }

    with patch.object(type(model).__bases__[0], "_get_request_payload", return_value=base_payload):
        with patch.object(model, "_convert_input") as mock_convert:
            mock_convert.return_value = MagicMock(to_messages=lambda: [human, ai])
            payload = model._get_request_payload([human, ai])

    assistant_msg = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant_msg["reasoning_content"] == "My reasoning"


# ---------------------------------------------------------------------------
# reasoning_content capture from non-streaming responses
# ---------------------------------------------------------------------------


def test_create_chat_result_captures_reasoning_content():
    model = _make_model()

    mock_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "The answer is 42.",
                    "reasoning_content": "I calculated deeply and found 42.",
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "model": "mimo-v2.5",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }

    from langchain_core.outputs import ChatGeneration, ChatResult

    original_result = ChatResult(
        generations=[ChatGeneration(message=AIMessage(content="The answer is 42."))],
        llm_output={},
    )

    with patch.object(type(model).__bases__[0], "_create_chat_result", return_value=original_result):
        result = model._create_chat_result(mock_response)

    ai_msg = result.generations[0].message
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.additional_kwargs.get("reasoning_content") == "I calculated deeply and found 42."


def test_create_chat_result_no_reasoning_is_noop():
    model = _make_model()

    mock_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello!",
                },
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "model": "mimo-v2.5",
        "usage": {},
    }

    from langchain_core.outputs import ChatGeneration, ChatResult

    original_result = ChatResult(
        generations=[ChatGeneration(message=AIMessage(content="Hello!"))],
        llm_output={},
    )

    with patch.object(type(model).__bases__[0], "_create_chat_result", return_value=original_result):
        result = model._create_chat_result(mock_response)

    ai_msg = result.generations[0].message
    assert "reasoning_content" not in ai_msg.additional_kwargs


# ---------------------------------------------------------------------------
# reasoning_content capture from streaming deltas
# ---------------------------------------------------------------------------


def test_convert_chunk_captures_reasoning_content_from_delta():
    model = _make_model()

    chunk = {
        "choices": [
            {
                "delta": {
                    "role": "assistant",
                    "content": "Hello",
                    "reasoning_content": "Thinking about greeting...",
                },
                "index": 0,
            }
        ],
        "model": "mimo-v2.5",
    }

    result = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert result is not None
    msg = result.message
    assert isinstance(msg, AIMessageChunk)
    assert msg.additional_kwargs.get("reasoning_content") == "Thinking about greeting..."


def test_convert_chunk_no_reasoning_is_noop():
    model = _make_model()

    chunk = {
        "choices": [
            {
                "delta": {
                    "role": "assistant",
                    "content": "Hi there",
                },
                "index": 0,
            }
        ],
        "model": "mimo-v2.5",
    }

    result = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert result is not None
    msg = result.message
    assert isinstance(msg, AIMessageChunk)
    assert "reasoning_content" not in msg.additional_kwargs
