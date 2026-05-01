"""Helper functions for workflow nodes to call subagents."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def get_workdir(thread_id: str | None = None) -> str:
    try:
        from deerflow.global_variables.prompt_injector import get_merged_variables

        merged = get_merged_variables(thread_id=thread_id)
        workdir_data = merged.get("workdir")
        if isinstance(workdir_data, dict):
            return workdir_data.get("value", os.getcwd())
        if workdir_data:
            return str(workdir_data)
    except Exception as e:
        logger.warning(f"Failed to get workdir from global variables: {e}")
    return os.getcwd()


def get_novel_base(thread_id: str | None = None) -> str | None:
    try:
        from deerflow.global_variables.prompt_injector import get_merged_variables

        merged = get_merged_variables(thread_id=thread_id)
        novel_toc = merged.get("novel_toc")
        if isinstance(novel_toc, dict):
            return novel_toc.get("value")
        if novel_toc:
            return str(novel_toc)
    except Exception as e:
        logger.warning(f"Failed to get novel_toc from global variables: {e}")
    return None


def normalize_chapter_group(chapter_group: str) -> str:
    chapter_group = chapter_group.strip()
    if not chapter_group.startswith("第"):
        chapter_group = f"第{chapter_group}"
    if not chapter_group.endswith("章"):
        chapter_group = f"{chapter_group}章"
    return chapter_group


def read_file_safe(file_path: str) -> str | None:
    try:
        p = Path(file_path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return None


async def call_subagent(
    subagent_name: str,
    task: str,
    parent_model: str | None = None,
    thread_id: str | None = None,
) -> str:
    from deerflow.subagents import SubagentExecutor, get_subagent_config
    from deerflow.tools import get_available_tools

    config = get_subagent_config(subagent_name)
    if config is None:
        raise ValueError(f"Unknown subagent: {subagent_name}")

    config.skills = []

    tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

    executor = SubagentExecutor(
        config=config,
        tools=tools,
        parent_model=parent_model,
        thread_id=thread_id,
    )

    result = await executor._aexecute(task)
    from deerflow.subagents.executor import SubagentStatus

    if result.status == SubagentStatus.COMPLETED:
        return result.result or ""
    else:
        raise RuntimeError(f"Subagent {subagent_name} failed: {result.error}")
