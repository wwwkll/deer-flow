"""Backward-compatible alias for :mod:`deerflow.models.patched_generic_openai`.

The ``PatchedMiMoChatOpenAI`` class has been merged into
``GenericPatchedChatOpenAI`` which is a strict superset — it handles
``reasoning_content`` *and* ``reasoning`` from any OpenAI-compatible API
(MiMo, DeepSeek, Ollama, vLLM, Qwen, etc.).

Existing ``config.yaml`` entries using
``deerflow.models.patched_mimo:PatchedMiMoChatOpenAI`` continue to work
without any changes.
"""

from .patched_generic_openai import GenericPatchedChatOpenAI as PatchedMiMoChatOpenAI

__all__ = ["PatchedMiMoChatOpenAI"]
