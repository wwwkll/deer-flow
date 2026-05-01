"""Novel post-process workflow - Extracted from writing workflow."""

import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

logger = logging.getLogger(__name__)


def _resolve_chapter_content(novel_base: str, chapter_num: int, chapter_group: str | None = None, chapter_content: str | None = None) -> str | None:
    """Resolve chapter content path. Priority: explicit path > auto-detect by group > glob search."""
    # 1. Explicit path provided
    if chapter_content:
        return chapter_content

    # 2. Auto-detect by chapter_group
    if chapter_group:
        group_normalized = normalize_chapter_group(chapter_group)
        auto_path = f"{novel_base}/02-正文/{group_normalized}/第{chapter_num}章.md"
        if Path(auto_path).exists():
            return auto_path

    # 3. Glob search in all chapter groups
    body_dir = Path(f"{novel_base}/02-正文")
    if body_dir.exists():
        pattern = f"**/第{chapter_num}章.md"
        matches = list(body_dir.rglob(pattern))
        if matches:
            return str(matches[0])

    return None


async def _process_single_chapter(
    novel_base: str,
    chapter_num: int,
    chapter_group: str | None,
    chapter_content: str | None,
    thread_id: str | None,
    model_name: str | None,
) -> dict[str, Any]:
    """Process post-processing for a single chapter."""
    logger.info(f"Post-process workflow: processing chapter {chapter_num}")

    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    card_path = f"{novel_base}/card.json"

    content_path = _resolve_chapter_content(novel_base, chapter_num, chapter_group, chapter_content)
    content_data = read_file_safe(content_path) if content_path else None

    if content_data:
        chapter_section = f"## 章节正文（已注入，不要再用read_file读取）\n\n{content_data}\n"
    else:
        chapter_section = f"## 章节正文\n路径：{content_path or '自动查找失败'}\n[未成功注入，请用read_file自行读取]\n"

    injection_note = '以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。\n标注"未成功注入"的，请用read_file按路径自行读取。\n\n'

    results = {"chapter_num": chapter_num, "content_path": content_path}

    try:
        summary_task = f"""你的任务是生成第{chapter_num}章摘要。

{injection_note}{chapter_section}

生成摘要后，追加写入：{summary_path}
"""
        summary_result = await call_subagent("chapter-summarizer", summary_task, parent_model=model_name)
        results["chapter_summary"] = summary_result
    except Exception as e:
        logger.error(f"Chapter summarizer failed for chapter {chapter_num}: {e}")

    try:
        state_task = f"""你的任务是更新当前状态卡。

{injection_note}{chapter_section}

更新状态文件：{state_path}
"""
        await call_subagent("state-settler", state_task, parent_model=model_name)
        results["state_updated"] = True
    except Exception as e:
        logger.error(f"State settler failed for chapter {chapter_num}: {e}")

    try:
        hook_task = f"""你的任务是更新伏笔池。

章节号：{chapter_num}
更新伏笔池文件：{hook_path}

{injection_note}{chapter_section}
"""
        await call_subagent("hook-manager", hook_task, parent_model=model_name)
        results["hooks_updated"] = True
    except Exception as e:
        logger.error(f"Hook manager failed for chapter {chapter_num}: {e}")

    try:
        card_task = f"""你的任务是更新小说名片。

章节号：{chapter_num}
更新名片文件：{card_path}

{injection_note}{chapter_section}
"""
        await call_subagent("card-manager", card_task, parent_model=model_name)
        results["card_updated"] = True
    except Exception as e:
        logger.error(f"Card manager failed for chapter {chapter_num}: {e}")

    return results


async def post_process(state: NovelWorkflowState) -> dict[str, Any]:
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

    # Build chapter list to process
    chapters_to_process: list[tuple[int, str | None]] = []

    if chapter_nums:
        # Multiple chapters mode
        for num in chapter_nums:
            chapters_to_process.append((num, chapter_content))
    elif chapter_num:
        # Single chapter mode
        chapters_to_process.append((chapter_num, chapter_content))
    else:
        raise ValueError("缺少必需参数: chapter_num 或 chapter_nums")

    all_results = []
    errors = []

    for num, content in chapters_to_process:
        try:
            result = await _process_single_chapter(
                novel_base=novel_base,
                chapter_num=num,
                chapter_group=chapter_group,
                chapter_content=content,
                thread_id=thread_id,
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

    # Build chapter list to sync
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

    def _inject(label: str, path: str, data: str | None) -> str:
        if data:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{data}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("细纲", outline_path, outline_data)
    sections += _inject("卷纲", volume_path, volume_data)

    all_synced = []
    errors = []

    for num in chapters_to_sync:
        logger.info(f"Post-process workflow: syncing outline for chapter {num}")

        task = f"""你的任务是同步细纲（sync模式）。

章节号：{num}
小说根目录：{novel_base}

以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

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
