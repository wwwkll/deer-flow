"""Patched ChatOpenAI that preserves reasoning_content for Xiaomi MiMo models.

MiMo's API (https://token-plan-cn.xiaomimimo.com/v1) uses thinking mode that
returns ``reasoning_content`` in the assistant response.  In multi-turn
conversations the API requires ``reasoning_content`` to be passed back on ALL
previous assistant messages.

Standard ``langchain_openai.ChatOpenAI`` serialises only the standard fields
(``role``, ``content``, ``tool_calls``, …) and silently drops
``reasoning_content``, causing a 400 error:

    The reasoning_content in the thinking mode must be passed back to the API.

This module fixes the problem by:
1. Capturing ``reasoning_content`` from non-streaming responses (``_create_chat_result``)
2. Capturing ``reasoning_content`` from streaming deltas (``_convert_chunk_to_generation_chunk``)
3. Re-injecting it into outgoing request payloads (``_get_request_payload``)
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_delta_to_message_chunk, _create_usage_metadata


class PatchedMiMoChatOpenAI(ChatOpenAI):
    """ChatOpenAI with reasoning_content preservation for MiMo thinking models.

    Usage in ``config.yaml``::

        - name: mimo-v2.5
          display_name: mimo-v2.5
          use: deerflow.models.patched_mimo:PatchedMiMoChatOpenAI
          model: mimo-v2.5
          api_key: $MIMO_API_KEY
          base_url: https://token-plan-cn.xiaomimimo.com/v1
          max_tokens: 80000
          temperature: 1
          supports_thinking: false
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
                    reasoning_content = orig_msg.additional_kwargs.get("reasoning_content")
                    payload_msg["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
        else:
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [(i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"]
            for (idx, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                reasoning_content = ai_msg.additional_kwargs.get("reasoning_content")
                payload_messages[idx]["reasoning_content"] = reasoning_content if reasoning_content is not None else ""

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
            reasoning_content = choice_message.get("reasoning_content")
            if reasoning_content:
                additional_kwargs = dict(message.additional_kwargs)
                additional_kwargs["reasoning_content"] = reasoning_content
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
            reasoning_content = delta.get("reasoning_content")
            if reasoning_content:
                additional_kwargs = dict(message_chunk.additional_kwargs)
                additional_kwargs["reasoning_content"] = reasoning_content
                message_chunk = message_chunk.model_copy(update={"additional_kwargs": additional_kwargs})

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(message=message_chunk, generation_info=generation_info or None)
