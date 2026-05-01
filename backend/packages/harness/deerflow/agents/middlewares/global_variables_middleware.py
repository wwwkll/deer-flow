"""Middleware for injecting global variables into the system prompt.

Uses wrap_model_call hook to access ModelRequest.system_message directly,
since SystemMessage is NOT included in state["messages"] during before_model
(see langchain-agents factory.py model_node / _execute_model_sync).
"""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware

from deerflow.config.global_variables_config import get_global_variables_config
from deerflow.global_variables.prompt_injector import build_prompt_section, replace_template_variables

logger = logging.getLogger(__name__)


class GlobalVariablesMiddlewareState(AgentState):
    pass


def _apply_global_variables(request):
    config = get_global_variables_config()
    if not config.enabled:
        return request

    system_msg = request.system_message
    if not system_msg:
        return request

    content = system_msg.content if hasattr(system_msg, "content") else None
    if not isinstance(content, str) or not content:
        return request

    runtime = request.runtime
    thread_id = runtime.context.get("thread_id") if runtime and runtime.context else None
    original = content

    updated = replace_template_variables(original, thread_id=thread_id)

    if config.injection_enabled:
        gv_section = build_prompt_section(thread_id=thread_id)
        if gv_section and "<global_variables>" not in updated:
            updated = updated + "\n\n" + gv_section

    if updated != original:
        from langchain_core.messages import SystemMessage

        new_msg = SystemMessage(content=updated, id=system_msg.id, name=system_msg.name)
        request = request.override(system_message=new_msg)
        logger.debug("[GV] replaced %d chars in system prompt (thread=%s)", len(updated), thread_id)

    return request


class GlobalVariablesMiddleware(AgentMiddleware[GlobalVariablesMiddlewareState]):
    """Middleware that injects global variables into the system prompt at runtime.

    Uses wrap_model_call/awrap_model_call (not before_model) because system_message
    lives in ModelRequest.system_message, not in state["messages"].
    """

    state_schema = GlobalVariablesMiddlewareState

    @override
    def wrap_model_call(self, request, handler):
        request = _apply_global_variables(request)
        return handler(request)

    @override
    async def awrap_model_call(self, request, handler):
        request = _apply_global_variables(request)
        return await handler(request)
