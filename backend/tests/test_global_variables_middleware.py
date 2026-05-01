"""Unit tests for GlobalVariablesMiddleware.

Tests cover:
- _apply_global_variables: replaces {{variable_name}} in system_message
- wrap_model_call (sync): calls handler with modified request
- awrap_model_call (async): calls handler with modified request
- Edge cases: disabled config, no system_message, no variables
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.agents.middlewares.global_variables_middleware import (
    GlobalVariablesMiddleware,
    _apply_global_variables,
)
from deerflow.config.global_variables_config import GlobalVariablesConfig


def _make_request(system_message=None, thread_id=None):
    mock_model = MagicMock()
    request = MagicMock()
    request.model = mock_model
    request.messages = [HumanMessage(content="hello")]
    request.system_message = system_message
    request.runtime = MagicMock()
    request.runtime.context = {"thread_id": thread_id} if thread_id else {}
    request.tool_choice = None
    request.tools = []
    request.response_format = None
    request.state = {"messages": []}
    request.model_settings = {}

    def _override(**kwargs):
        new_req = MagicMock()
        new_req.model = request.model
        new_req.messages = request.messages
        new_req.system_message = kwargs.get("system_message", request.system_message)
        new_req.runtime = request.runtime
        new_req.tool_choice = request.tool_choice
        new_req.tools = request.tools
        new_req.response_format = request.response_format
        new_req.state = request.state
        new_req.model_settings = request.model_settings
        return new_req

    request.override = _override
    return request


def _mock_handler(request):
    return {"messages": request.messages}


def _mock_ahandler(request):
    async def _inner(req):
        return {"messages": req.messages}

    return _inner(request)


class TestApplyGlobalVariables:
    def test_replaces_novel_toc_in_system_message(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "小说根目录：/mnt/novel/toc.md\n项目路径：/mnt/shared-data"
                request = _make_request(
                    system_message=SystemMessage(content="小说根目录：{{novel_toc}}\n项目路径：{{workdir}}"),
                    thread_id="test-thread-1",
                )
                result = _apply_global_variables(request)
                assert result.system_message.content == "小说根目录：/mnt/novel/toc.md\n项目路径：/mnt/shared-data"

    def test_replaces_only_known_variables(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "Hello world, {{unknown}}"
                request = _make_request(
                    system_message=SystemMessage(content="Hello world, {{unknown}}"),
                    thread_id="t1",
                )
                result = _apply_global_variables(request)
                assert result.system_message.content == "Hello world, {{unknown}}"

    def test_no_change_when_same_content(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                original = "No variables here"
                mock_replace.return_value = original
                request = _make_request(
                    system_message=SystemMessage(content=original),
                    thread_id="t1",
                )
                result = _apply_global_variables(request)
                assert result is request

    def test_disabled_config_returns_unchanged(self):
        config = GlobalVariablesConfig(enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            request = _make_request(
                system_message=SystemMessage(content="{{novel_toc}}"),
                thread_id="t1",
            )
            result = _apply_global_variables(request)
            assert result is request
            assert result.system_message.content == "{{novel_toc}}"

    def test_no_system_message_returns_unchanged(self):
        config = GlobalVariablesConfig(enabled=True)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            request = _make_request(system_message=None, thread_id="t1")
            result = _apply_global_variables(request)
            assert result is request

    def test_no_thread_id_still_replaces_system_vars(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "project: /mnt/shared-data"
                request = _make_request(
                    system_message=SystemMessage(content="project: {{workdir}}"),
                    thread_id=None,
                )
                result = _apply_global_variables(request)
                mock_replace.assert_called_once_with("project: {{workdir}}", thread_id=None)
                assert result.system_message.content == "project: /mnt/shared-data"

    def test_preserves_system_message_id(self):
        config = GlobalVariablesConfig(enabled=True)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "replaced"
                request = _make_request(
                    system_message=SystemMessage(content="{{novel_toc}}", id="my-id"),
                    thread_id="t1",
                )
                result = _apply_global_variables(request)
                assert result.system_message.id == "my-id"

    def test_injection_enabled_appends_global_variables_block(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=True)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "Hello"
                with patch("deerflow.agents.middlewares.global_variables_middleware.build_prompt_section") as mock_build:
                    mock_build.return_value = "<global_variables>\nmode = writing\n</global_variables>"
                    request = _make_request(
                        system_message=SystemMessage(content="Hello"),
                        thread_id="t1",
                    )
                    result = _apply_global_variables(request)
                    assert "<global_variables>" in result.system_message.content

    def test_injection_not_duplicated_when_already_present(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=True)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                original = "Hello\n\n<global_variables>existing</global_variables>"
                mock_replace.return_value = original
                with patch("deerflow.agents.middlewares.global_variables_middleware.build_prompt_section") as mock_build:
                    mock_build.return_value = "<global_variables>new</global_variables>"
                    request = _make_request(
                        system_message=SystemMessage(content=original),
                        thread_id="t1",
                    )
                    result = _apply_global_variables(request)
                    assert result.system_message.content == original


class TestWrapModelCall:
    def test_sync_calls_handler_with_modified_request(self):
        mw = GlobalVariablesMiddleware()
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "replaced content"
                request = _make_request(
                    system_message=SystemMessage(content="{{novel_toc}}"),
                    thread_id="t1",
                )
                captured = {}

                def handler(req):
                    captured["system_message"] = req.system_message
                    return {"messages": []}

                result = mw.wrap_model_call(request, handler)
                assert captured["system_message"].content == "replaced content"
                assert result == {"messages": []}

    def test_sync_disabled_passes_through(self):
        mw = GlobalVariablesMiddleware()
        config = GlobalVariablesConfig(enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            request = _make_request(
                system_message=SystemMessage(content="{{novel_toc}}"),
                thread_id="t1",
            )
            captured = {}

            def handler(req):
                captured["system_message"] = req.system_message
                return {"messages": []}

            result = mw.wrap_model_call(request, handler)
            assert captured["system_message"].content == "{{novel_toc}}"
            assert result == {"messages": []}


class TestAwrapModelCall:
    @pytest.mark.asyncio
    async def test_async_calls_handler_with_modified_request(self):
        mw = GlobalVariablesMiddleware()
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "async replaced"
                request = _make_request(
                    system_message=SystemMessage(content="{{novel_toc}}"),
                    thread_id="t1",
                )
                captured = {}

                async def handler(req):
                    captured["system_message"] = req.system_message
                    return {"messages": []}

                result = await mw.awrap_model_call(request, handler)
                assert captured["system_message"].content == "async replaced"
                assert result == {"messages": []}

    @pytest.mark.asyncio
    async def test_async_disabled_passes_through(self):
        mw = GlobalVariablesMiddleware()
        config = GlobalVariablesConfig(enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            request = _make_request(
                system_message=SystemMessage(content="{{novel_toc}}"),
                thread_id="t1",
            )
            captured = {}

            async def handler(req):
                captured["system_message"] = req.system_message
                return {"messages": []}

            result = await mw.awrap_model_call(request, handler)
            assert captured["system_message"].content == "{{novel_toc}}"
            assert result == {"messages": []}

    @pytest.mark.asyncio
    async def test_async_replaces_workdir_and_novel_toc(self):
        mw = GlobalVariablesMiddleware()
        config = GlobalVariablesConfig(enabled=True, injection_enabled=False)
        with patch("deerflow.agents.middlewares.global_variables_middleware.get_global_variables_config", return_value=config):
            with patch("deerflow.agents.middlewares.global_variables_middleware.replace_template_variables") as mock_replace:
                mock_replace.return_value = "项目路径：/mnt/shared-data\n小说根目录：/mnt/novel/toc.md"
                request = _make_request(
                    system_message=SystemMessage(content="项目路径：{{workdir}}\n小说根目录：{{novel_toc}}"),
                    thread_id="new-thread-123",
                )
                captured = {}

                async def handler(req):
                    captured["req"] = req
                    return {"messages": []}

                result = await mw.awrap_model_call(request, handler)
                assert "/mnt/shared-data" in captured["req"].system_message.content
                assert "/mnt/novel/toc.md" in captured["req"].system_message.content
                assert "{{workdir}}" not in captured["req"].system_message.content
                assert "{{novel_toc}}" not in captured["req"].system_message.content
