"""Patched ChatOpenAI that preserves reasoning_content for Xiaomi MiMo models.

MiMo's API (https://token-plan-cn.xiaomimimo.com/v1) uses thinking mode that
returns ``reasoning_content`` in the assistant response.  In multi-turn
conversations the API requires ``reasoning_content`` to be passed back on ALL
previous assistant messages.

Standard ``langchain_openai.ChatOpenAI`` serialises only the standard fields
(``role``, ``content``, ``tool_calls``, …) and silently drops
``reasoning_content``, causing a 400 error:

    The reasoning_content in the thinking mode must be passed back to the API.

This module fixes the problem by overriding ``_get_request_payload`` to
re-inject ``reasoning_content`` from ``AIMessage.additional_kwargs`` into the
outgoing payload.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


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

        # Backstop empty reasoning_content for legacy assistant messages so MiMo
        # API does not 400 on threads that contain non-MiMo or pre-patch history.
        # Without this fallback, the very first call on a polluted thread fails
        # with: "The reasoning_content in the thinking mode must be passed back".
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
