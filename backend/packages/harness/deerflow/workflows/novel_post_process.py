"""Novel post-process workflow - Extracted from writing workflow."""

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.config.subagents_config import get_subagents_app_config
from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState
from my_tools.path_resolver import set_current_thread_id

logger = logging.getLogger(__name__)


def _is_parallel_enabled() -> bool:
    """Check if workflow parallel execution is enabled from config."""
    try:
        config = get_subagents_app_config()
        return config.workflow_parallel_enabled
    except Exception:
        return True


def _resolve_chapter_content(novel_base: str, chapter_num: int, chapter_group: str | None = None, chapter_content: str | None = None) -> str | None:
    """Resolve chapter content path. Priority: explicit path > auto-detect by group > glob search."""
    if chapter_content:
        return chapter_content

    if chapter_group:
        group_normalized = normalize_chapter_group(chapter_group)
        auto_path = f"{novel_base}/02-正文/{group_normalized}/第{chapter_num}章.md"
        if Path(auto_path).exists():
            return auto_path

    body_dir = Path(f"{novel_base}/02-正文")
    if body_dir.exists():
        pattern = f"**/第{chapter_num}章.md"
        matches = list(body_dir.rglob(pattern))
        if matches:
            return str(matches[0])

    return None


def _inject(label: str, path: str, required: bool = True) -> str:
    content = read_file_safe(path)
    if content:
        return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
    if required:
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"
    return f"## {label}\n路径：{path}\n[文件不存在，跳过]\n"


def _inject_data(label: str, path: str, data: str | None) -> str:
    if data:
        return f"## {label}（已注入，不要再用read_file读取）\n\n{data}\n"
    return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"


INJECTION_NOTE = '以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。\n标注"未成功注入"的，请用read_file按路径自行读取。\n\n'


async def _process_single_chapter_summary(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Generate chapter summary for a single chapter."""
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"

    content_path = _resolve_chapter_content(novel_base, chapter_num, chapter_group, chapter_content)
    content_data = read_file_safe(content_path) if content_path else None
    summary_data = read_file_safe(summary_path)

    chapter_section = _inject_data("章节正文", content_path or "自动查找失败", content_data)
    summary_sections = chapter_section
    summary_sections += _inject_data("已有章节摘要汇总", summary_path, summary_data)

    summary_task = f"""你的任务是生成第{chapter_num}章摘要。

{INJECTION_NOTE}{summary_sections}

生成摘要后，追加写入：{summary_path}
"""

    try:
        summary_result = await call_subagent("chapter-summarizer", summary_task, parent_model=model_name)
        return {"chapter_num": chapter_num, "chapter_summary": summary_result}
    except Exception as e:
        logger.error(f"Chapter summarizer failed for chapter {chapter_num}: {e}")
        return {"chapter_num": chapter_num, "errors": [f"Chapter summarizer failed: {e}"]}


async def _process_single_chapter_state(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Update state card for a single chapter."""
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    matrix_path = f"{novel_base}/00-世界观/角色矩阵.md"
    subplot_path = f"{novel_base}/00-世界观/支线板.md"
    emotional_path = f"{novel_base}/00-世界观/情感弧线.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md" if chapter_group else ""

    content_path = _resolve_chapter_content(novel_base, chapter_num, chapter_group, chapter_content)
    content_data = read_file_safe(content_path) if content_path else None
    state_data = read_file_safe(state_path)
    hook_data = read_file_safe(hook_path)
    summary_data = read_file_safe(summary_path)
    matrix_data = read_file_safe(matrix_path)
    subplot_data = read_file_safe(subplot_path)
    emotional_data = read_file_safe(emotional_path)
    outline_data = read_file_safe(outline_path)

    chapter_section = _inject_data("章节正文", content_path or "自动查找失败", content_data)
    state_sections = chapter_section
    state_sections += _inject_data("当前状态卡", state_path, state_data)
    state_sections += _inject_data("伏笔池", hook_path, hook_data)
    state_sections += _inject_data("章节摘要汇总", summary_path, summary_data)
    state_sections += _inject_data("角色矩阵", matrix_path, matrix_data)
    state_sections += _inject_data("支线板", subplot_path, subplot_data)
    state_sections += _inject_data("情感弧线", emotional_path, emotional_data)
    state_sections += _inject_data("章节细纲", outline_path, outline_data)

    state_task = f"""你的任务是更新当前状态卡。

{INJECTION_NOTE}{state_sections}

更新状态文件：{state_path}
"""

    try:
        await call_subagent("state-settler", state_task, parent_model=model_name)
        return {"chapter_num": chapter_num, "state_updated": True}
    except Exception as e:
        logger.error(f"State settler failed for chapter {chapter_num}: {e}")
        return {"chapter_num": chapter_num, "errors": [f"State settler failed: {e}"]}


async def _process_single_chapter_hooks(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Update hooks pool for a single chapter."""
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md" if chapter_group else ""

    content_path = _resolve_chapter_content(novel_base, chapter_num, chapter_group, chapter_content)
    content_data = read_file_safe(content_path) if content_path else None
    hook_data = read_file_safe(hook_path)
    outline_data = read_file_safe(outline_path)

    chapter_section = _inject_data("章节正文", content_path or "自动查找失败", content_data)
    hook_sections = chapter_section
    hook_sections += _inject_data("伏笔池", hook_path, hook_data)
    hook_sections += _inject_data("章节细纲", outline_path, outline_data)

    hook_task = f"""你的任务是更新伏笔池。

章节号：{chapter_num}
更新伏笔池文件：{hook_path}

{INJECTION_NOTE}{hook_sections}
"""

    try:
        await call_subagent("hook-manager", hook_task, parent_model=model_name)
        return {"chapter_num": chapter_num, "hooks_updated": True}
    except Exception as e:
        logger.error(f"Hook manager failed for chapter {chapter_num}: {e}")
        return {"chapter_num": chapter_num, "errors": [f"Hook manager failed: {e}"]}


async def _process_single_chapter_card(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Update novel card for a single chapter."""
    card_path = f"{novel_base}/card.json"

    content_path = _resolve_chapter_content(novel_base, chapter_num, chapter_group, chapter_content)
    content_data = read_file_safe(content_path) if content_path else None
    card_data = read_file_safe(card_path)

    card_sections = _inject_data("小说名片", card_path, card_data)
    card_sections += _inject_data("章节正文", content_path or "自动查找失败", content_data)

    card_task = f"""你的任务是更新小说名片。

章节号：{chapter_num}
更新名片文件：{card_path}

{INJECTION_NOTE}{card_sections}
"""

    try:
        await call_subagent("card-manager", card_task, parent_model=model_name)
        return {"chapter_num": chapter_num, "card_updated": True}
    except Exception as e:
        logger.error(f"Card manager failed for chapter {chapter_num}: {e}")
        return {"chapter_num": chapter_num, "errors": [f"Card manager failed: {e}"]}


async def _process_single_chapter_sequential(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Process all post-processing steps sequentially for a single chapter."""
    logger.info(f"Post-process workflow: processing chapter {chapter_num} (sequential)")

    results = {"chapter_num": chapter_num}

    summary_result = await _process_single_chapter_summary(novel_base, chapter_num, chapter_group, chapter_content, model_name)
    results.update(summary_result)

    state_result = await _process_single_chapter_state(novel_base, chapter_num, chapter_group, chapter_content, model_name)
    results.update(state_result)

    hooks_result = await _process_single_chapter_hooks(novel_base, chapter_num, chapter_group, chapter_content, model_name)
    results.update(hooks_result)

    card_result = await _process_single_chapter_card(novel_base, chapter_num, chapter_group, chapter_content, model_name)
    results.update(card_result)

    return results


async def _process_single_chapter_parallel(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Process all post-processing steps in parallel for a single chapter."""
    import asyncio

    logger.info(f"Post-process workflow: processing chapter {chapter_num} (parallel)")

    results = await asyncio.gather(
        _process_single_chapter_summary(novel_base, chapter_num, chapter_group, chapter_content, model_name),
        _process_single_chapter_state(novel_base, chapter_num, chapter_group, chapter_content, model_name),
        _process_single_chapter_hooks(novel_base, chapter_num, chapter_group, chapter_content, model_name),
        _process_single_chapter_card(novel_base, chapter_num, chapter_group, chapter_content, model_name),
        return_exceptions=True,
    )

    merged = {"chapter_num": chapter_num}
    errors = []
    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r))
        elif isinstance(r, dict):
            merged.update(r)
            if "errors" in r and r["errors"]:
                errors.extend(r["errors"] if isinstance(r["errors"], list) else [r["errors"]])

    if errors:
        merged["errors"] = errors

    return merged


async def post_process(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_nums = state.get("chapter_nums", [])
    chapter_group = state.get("chapter_group", "")
    chapter_content = state.get("chapter_content", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    chapters_to_process: list[tuple[int, str | None]] = []

    if chapter_nums:
        for num in chapter_nums:
            chapters_to_process.append((num, chapter_content))
    elif chapter_num:
        chapters_to_process.append((chapter_num, chapter_content))
    else:
        raise ValueError("缺少必需参数: chapter_num 或 chapter_nums")

    all_results = []
    errors = []

    parallel = _is_parallel_enabled()

    for num, content in chapters_to_process:
        try:
            if parallel:
                result = await _process_single_chapter_parallel(
                    novel_base=novel_base,
                    chapter_num=num,
                    chapter_group=chapter_group,
                    chapter_content=content,
                    model_name=model_name,
                )
            else:
                result = await _process_single_chapter_sequential(
                    novel_base=novel_base,
                    chapter_num=num,
                    chapter_group=chapter_group,
                    chapter_content=content,
                    model_name=model_name,
                )
            all_results.append(result)
        except Exception as e:
            logger.error(f"Post-process failed for chapter {num}: {e}")
            errors.append(f"Chapter {num}: {e}")

    return {
        "post_process_results": all_results,
        "errors": errors if errors else None,
    }


async def sync_outline(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_nums = state.get("chapter_nums", [])
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    chapters_to_sync: list[int] = []
    if chapter_nums:
        chapters_to_sync = chapter_nums
    elif chapter_num:
        chapters_to_sync = [chapter_num]
    else:
        raise ValueError("缺少必需参数: chapter_num 或 chapter_nums")

    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    volume_path = f"{novel_base}/01-规划/卷纲.md"

    outline_data = read_file_safe(outline_path)
    volume_data = read_file_safe(volume_path)

    sections = _inject_data("细纲", outline_path, outline_data)
    sections += _inject_data("卷纲", volume_path, volume_data)

    all_synced = []
    errors = []

    for num in chapters_to_sync:
        logger.info(f"Post-process workflow: syncing outline for chapter {num}")

        content_path = _resolve_chapter_content(novel_base, num, chapter_group)
        content_data = read_file_safe(content_path) if content_path else None
        chapter_section = _inject_data("章节正文", content_path or "自动查找失败", content_data)

        task = f"""你的任务是同步细纲（sync模式）。

章节号：{num}
小说根目录：{novel_base}

{INJECTION_NOTE}{sections}{chapter_section}

请根据正文内容，更新当前章节的完成状态。
"""

        try:
            await call_subagent("outline-planner", task, parent_model=model_name)
            all_synced.append(num)
        except Exception as e:
            logger.error(f"Sync outline failed for chapter {num}: {e}")
            errors.append(f"Chapter {num}: {e}")

    return {
        "outline_synced": len(all_synced) > 0,
        "synced_chapters": all_synced,
        "errors": errors if errors else None,
    }


def create_post_process_workflow() -> StateGraph:
    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("post_process", post_process)
    workflow.add_node("sync_outline", sync_outline)

    workflow.set_entry_point("post_process")
    workflow.add_edge("post_process", "sync_outline")
    workflow.add_edge("sync_outline", END)

    return workflow.compile()


register_workflow("post_process", create_post_process_workflow)
