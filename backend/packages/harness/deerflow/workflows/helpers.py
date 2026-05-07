"""Helper functions for workflow nodes to call subagents."""

import json
import logging
import os
from datetime import datetime, timezone
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
        # Read host_path from config.yaml mounts configuration
        if novel_base and novel_base.startswith("/mnt/"):
            from deerflow.config.app_config import get_app_config
            config = get_app_config()
            mounts = config.sandbox.mounts if config and config.sandbox else []
            
            # Find matching mount for this virtual path
            for mount in mounts:
                container_path = mount.container_path.rstrip("/")
                if novel_base.startswith(container_path + "/") or novel_base == container_path:
                    # Extract relative path after container_path
                    relative = novel_base[len(container_path):].lstrip("/")
                    # Use configured host_path
                    host_path = Path(mount.host_path)
                    if not host_path.is_absolute():
                        from deerflow.config.paths import get_paths
                        host_path = (get_paths().base_dir.parent.parent / host_path).resolve()
                    novel_base = str(host_path / relative) if relative else str(host_path)
                    break

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

    logger.info(f"[CALL_SUBAGENT_DEBUG] parent_model: {parent_model}")
    if parent_model is None:
        raise ValueError("parent_model is required but was not provided. Make sure model_name is passed from the workflow state.")
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


def update_novel_card(
    card_path: str,
    chapter_num: int,
    chapter_content: str = "",
) -> dict:
    """直接程序化更新 card.json，无需 LLM 子 agent。

    更新字段：
    - current_chapter: 设为 chapter_num
    - word_count: 累加本章字数
    - last_updated: 当前时间戳
    - status: 设为 writing
    """
    try:
        card_path_obj = Path(card_path)
        if card_path_obj.exists():
            card_data = json.loads(card_path_obj.read_text(encoding="utf-8"))
        else:
            card_data = {}

        chapter_words = len(chapter_content.replace(" ", "").replace("\n", "")) if chapter_content else 0

        if chapter_num > 0:
            card_data["current_chapter"] = chapter_num
        card_data["word_count"] = (card_data.get("word_count", 0)) + chapter_words
        card_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        card_data["status"] = "writing"

        card_path_obj.parent.mkdir(parents=True, exist_ok=True)
        card_path_obj.write_text(json.dumps(card_data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(f"[update_novel_card] Updated {card_path}: chapter={chapter_num}, +{chapter_words} words")
        return {"success": True, "card_data": card_data}
    except Exception as e:
        logger.error(f"[update_novel_card] Failed to update {card_path}: {e}")
        return {"success": False, "error": str(e)}
