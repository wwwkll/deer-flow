"""Generic Patched ChatOpenAI that preserves reasoning_content for all OpenAI-compatible models.

Many OpenAI-compatible APIs (Ollama, LM Studio, vLLM, DeepSeek, Qwen, etc.) return
thinking/reasoning content in non-standard fields that ``langchain_openai.ChatOpenAI``
silently drops:

- ``reasoning_content`` — used by DeepSeek, MiMo, Ollama thinking models
- ``reasoning`` — used by vLLM, some Qwen deployments

This causes two problems:

1. **Frontend cannot display thinking**: The reasoning text never reaches
   ``AIMessage.additional_kwargs["reasoning_content"]``, so
   ``extractReasoningContentFromMessage()`` returns ``None``.
2. **Multi-turn conversation breaks**: Some APIs (MiMo, vLLM) require the
   reasoning content to be echoed back on subsequent turns.

This module fixes both problems by capturing reasoning from responses and
re-injecting it into request payloads, following the same pattern as
:mod:`deerflow.models.patched_mimo` and :mod:`deerflow.models.vllm_provider`.

Usage in ``config.yaml``::

    - name: qwen-3.6-local
      display_name: Qwen 3.6 (Local)
      use: deerflow.models.patched_generic_openai:GenericPatchedChatOpenAI
      model: qwen3:32b
      api_key: ollama
      base_url: http://localhost:11434/v1
      supports_thinking: true
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_delta_to_message_chunk, _create_usage_metadata

logger = logging.getLogger(__name__)


def _extract_reasoning_from_response_message(message_dict: dict) -> tuple[str | None, str | None]:
    """Extract reasoning content from a response message dict.

    Returns:
        Tuple of (reasoning_content, reasoning) — whichever is present.
    """
    reasoning_content = message_dict.get("reasoning_content")
    reasoning = message_dict.get("reasoning")
    return reasoning_content, reasoning


def _extract_reasoning_from_delta(delta: dict) -> tuple[str | None, Any | None]:
    """Extract reasoning content from a streaming delta dict.

    Returns:
        Tuple of (reasoning_content_text, raw_reasoning).
        reasoning_content is always a string or None.
        reasoning preserves the original type (str, list, dict, or None).
    """
    reasoning_content = delta.get("reasoning_content")
    reasoning = delta.get("reasoning")

    if reasoning is not None and not isinstance(reasoning, str):
        reasoning_text = _reasoning_to_text(reasoning)
    else:
        reasoning_text = reasoning

    return reasoning_content, reasoning_text


def _reasoning_to_text(reasoning: Any) -> str:
    """Best-effort extraction of readable reasoning text from various formats."""
    if isinstance(reasoning, str):
        return reasoning
    if isinstance(reasoning, list):
        parts = [_reasoning_to_text(item) for item in reasoning]
        return "".join(part for part in parts if part)
    if isinstance(reasoning, dict):
        for key in ("text", "content", "reasoning_content"):
            value = reasoning.get(key)
            if isinstance(value, str):
                return value
            if value is not None:
                text = _reasoning_to_text(value)
                if text:
                    return text
        try:
            import json
            return json.dumps(reasoning, ensure_ascii=False)
        except TypeError:
            return str(reasoning)
    try:
        import json
        return json.dumps(reasoning, ensure_ascii=False)
    except TypeError:
        return str(reasoning)


def _restore_reasoning_to_payload(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Re-inject reasoning onto an outgoing assistant message payload.

    Checks both ``reasoning_content`` and ``reasoning`` in additional_kwargs
    and restores whichever is available.
    """
    reasoning_content = orig_msg.additional_kwargs.get("reasoning_content")
    reasoning = orig_msg.additional_kwargs.get("reasoning")

    if reasoning_content is not None:
        payload_msg["reasoning_content"] = reasoning_content
    elif reasoning is not None:
        payload_msg["reasoning"] = reasoning


class GenericPatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with universal reasoning_content preservation.

    Captures ``reasoning_content`` and ``reasoning`` from both non-streaming
    and streaming responses, stores them in ``AIMessage.additional_kwargs``,
    and re-injects them into multi-turn request payloads.

    Compatible with any OpenAI-compatible API that returns thinking content,
    including:
    - Ollama (Qwen, DeepSeek-R1, etc.)
    - LM Studio
    - Local vLLM deployments
    - Any gateway that proxies thinking models
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_reasoning_to_payload(payload_msg, orig_msg)
        else:
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [(i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"]
            for (idx, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                _restore_reasoning_to_payload(payload_msg, ai_msg)

        return payload

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        for index, generation in enumerate(result.generations):
            if index >= len(choices):
                break
            if not isinstance(generation, ChatGeneration):
                continue
            message = generation.message
            if not isinstance(message, AIMessage):
                continue

            choice_message = choices[index].get("message", {})
            reasoning_content, reasoning = _extract_reasoning_from_response_message(choice_message)

            logger.debug(
                "GenericPatchedChatOpenAI._create_chat_result: choice_message keys=%s, "
                "has_reasoning_content=%s, has_reasoning=%s, content_preview=%s",
                list(choice_message.keys()),
                reasoning_content is not None,
                reasoning is not None,
                (choice_message.get("content") or "")[:100],
            )

            if reasoning_content or reasoning:
                additional_kwargs = dict(message.additional_kwargs)
                if reasoning_content:
                    additional_kwargs["reasoning_content"] = reasoning_content
                if reasoning:
                    additional_kwargs["reasoning"] = reasoning
                    if not reasoning_content:
                        reasoning_text = _reasoning_to_text(reasoning)
                        if reasoning_text:
                            additional_kwargs["reasoning_content"] = reasoning_text
                generation.message = message.model_copy(update={"additional_kwargs": additional_kwargs})

        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        if chunk.get("type") == "content.delta":
            return None

        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        usage_metadata = _create_usage_metadata(token_usage, chunk.get("service_tier")) if token_usage else None

        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(
                message=default_chunk_class(content="", usage_metadata=usage_metadata),
                generation_info=base_generation_info,
            )
            if self.output_version == "v1":
                generation_chunk.message.content = []
                generation_chunk.message.response_metadata["output_version"] = "v1"
            return generation_chunk

        choice = choices[0]
        delta = choice.get("delta")
        if delta is None:
            return None

        message_chunk = _convert_delta_to_message_chunk(delta, default_chunk_class)
        generation_info = {**base_generation_info} if base_generation_info else {}

        if finish_reason := choice.get("finish_reason"):
            generation_info["finish_reason"] = finish_reason
            if model_name := chunk.get("model"):
                generation_info["model_name"] = model_name
            if system_fingerprint := chunk.get("system_fingerprint"):
                generation_info["system_fingerprint"] = system_fingerprint
            if service_tier := chunk.get("service_tier"):
                generation_info["service_tier"] = service_tier

        logprobs = choice.get("logprobs")
        if logprobs:
            generation_info["logprobs"] = logprobs

        if isinstance(message_chunk, AIMessageChunk):
            if usage_metadata:
                message_chunk.usage_metadata = usage_metadata

            reasoning_content, reasoning_text = _extract_reasoning_from_delta(delta)
            if reasoning_content or reasoning_text:
                additional_kwargs = dict(message_chunk.additional_kwargs)
                if reasoning_content:
                    additional_kwargs["reasoning_content"] = reasoning_content
                elif reasoning_text:
                    additional_kwargs["reasoning_content"] = reasoning_text
                if delta.get("reasoning") is not None:
                    additional_kwargs["reasoning"] = delta["reasoning"]
                message_chunk = message_chunk.model_copy(update={"additional_kwargs": additional_kwargs})
                logger.debug(
                    "GenericPatchedChatOpenAI._convert_chunk: captured reasoning, "
                    "rc_len=%s, rt_len=%s",
                    len(reasoning_content) if reasoning_content else 0,
                    len(reasoning_text) if reasoning_text else 0,
                )
            else:
                content_in_delta = delta.get("content", "")
                if isinstance(content_in_delta, str) and "<tool_call>" in content_in_delta:
                    logger.debug(
                        "GenericPatchedChatOpenAI._convert_chunk: found <arg_key> tag in content delta, "
                        "content_preview=%s",
                        content_in_delta[:100],
                    )

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(message=message_chunk, generation_info=generation_info or None)
