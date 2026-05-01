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
            novel_base = novel_toc.get("value")
        elif novel_toc:
            novel_base = str(novel_toc)
        else:
            return None

        # Convert container virtual path to host path
        # /mnt/shared-data/... -> backend/.deer-flow/shared-data/...
        if novel_base and novel_base.startswith("/mnt/shared-data/"):
            from deerflow.config.paths import get_paths
            relative = novel_base[len("/mnt/shared-data/"):].lstrip("/")
            novel_base = str(get_paths().base_dir / "shared-data" / relative)

        return novel_base
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
    from deerflow.config import get_app_config

    config = get_subagent_config(subagent_name)
    if config is None:
        raise ValueError(f"Unknown subagent: {subagent_name}")

    config.skills = []

    # Use default model if parent_model not specified
    logger.info(f"[CALL_SUBAGENT_DEBUG] parent_model before fallback: {parent_model}")
    if parent_model is None:
        app_config = get_app_config()
        if app_config.models:
            parent_model = app_config.models[0].name
            logger.info(f"[CALL_SUBAGENT_DEBUG] Using fallback model: {parent_model}")

    logger.info(f"[CALL_SUBAGENT_DEBUG] Final parent_model: {parent_model}")
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
