"""Novel writing workflow - Writing, audit, and post-processing."""

import logging
import re
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.config import get_app_config
from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

logger = logging.getLogger(__name__)

_AUDIT_RESULT_PATTERN = re.compile(r"\[AUDIT_RESULT:\s*(PASS|FAIL)\]", re.IGNORECASE)


def _is_parallel_enabled() -> bool:
    """Check if workflow parallel execution is enabled from config."""
    try:
        config = get_app_config()
        return config.subagents.workflow_parallel_enabled
    except Exception:
        return True


def _get_rel_path(path: str) -> str:
    """Extract relative path from novel base directory."""
    from deerflow.workflows.helpers import get_novel_base
    novel_base = get_novel_base()
    if novel_base and path.startswith(novel_base + "/"):
        return path.replace(novel_base + "/", "")
    return path


def _inject(label: str, path: str, required: bool = True) -> str:
    content = read_file_safe(path)
    rel_path = _get_rel_path(path)
    if content:
        return f"## {label}（【已注入】{rel_path} —— 严禁使用read_file重复读取，内容已完整提供）\n\n{content}\n"
    if required:
        return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[未成功注入，请用read_file自行读取]\n"
    return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[文件不存在，跳过]\n"


def _inject_data(label: str, path: str, data: str | None) -> str:
    rel_path = _get_rel_path(path)
    if data:
        return f"## {label}（【已注入】{rel_path} —— 严禁使用read_file重复读取，内容已完整提供）\n\n{data}\n"
    return f"## {label}\n路径：{path}（相对路径：{rel_path}）\n[未成功注入，请用read_file自行读取]\n"


INJECTION_NOTE = '【重要提示】以下内容已直接注入到你的上下文中：\n- 标注"【已注入】"的文件，内容已完整提供，严禁使用read_file工具重复读取，否则将严重浪费上下文窗口\n- 标注"[未成功注入]"的文件，请按提供的路径使用read_file自行读取\n\n'


async def write_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    writing_task_summary = state.get("writing_task_summary", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    if not novel_name:
        raise ValueError("缺少必需参数: novel_name")
    if not chapter_num:
        raise ValueError("缺少必需参数: chapter_num")
    if not chapter_group:
        raise ValueError("缺少必需参数: chapter_group")

    chapter_group_normalized = normalize_chapter_group(chapter_group)

    logger.info(f"Writing workflow: writing chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    prev_chapter_num = chapter_num - 1
    prev_chapter_path = f"{novel_base}/02-正文/{chapter_group_normalized}/第{prev_chapter_num}章.md"
    style_path = f"{novel_base}/05-参考/样式指纹.md"
    output_path = f"{novel_base}/02-正文/{chapter_group_normalized}/第{chapter_num}章.md"

    sections = _inject("写作任务汇总", writing_task_summary)
    sections += _inject("样式指纹", style_path)
    sections += _inject("上一章正文", prev_chapter_path, required=False)

    task = f"""你的任务是撰写第{chapter_num}章正文。

{INJECTION_NOTE}{sections}

根据写作任务汇总中的细纲、世界观、人物、道具等参考信息，撰写第{chapter_num}章正文。

将正文写入：{output_path}
"""

    try:
        result = await call_subagent("novel-writer", task, parent_model=model_name)
        return {"chapter_content": output_path, "chapter_group": chapter_group_normalized}
    except Exception as e:
        logger.error(f"Write chapter failed: {e}")
        return {"errors": [f"Write chapter failed: {e}"]}


def _parse_audit_result(text: str) -> bool:
    match = _AUDIT_RESULT_PATTERN.search(text)
    if match:
        return match.group(1).upper() == "PASS"
    logger.warning("Audit result marker not found, defaulting to FAIL")
    return False


async def audit_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: auditing chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    audit_report_path = f"{novel_base}/04-审稿/第{chapter_num}章-审计报告.md"

    bible_path = f"{novel_base}/00-世界观/故事圣经.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"
    matrix_path = f"{novel_base}/00-世界观/角色矩阵.md"

    content_data = read_file_safe(chapter_content)

    sections = _inject_data("章节正文", chapter_content, content_data)
    sections += _inject("故事圣经", bible_path)
    sections += _inject("章节细纲", outline_path)
    sections += _inject("当前状态", state_path)
    sections += _inject("伏笔池", hook_path)
    sections += _inject("章节摘要汇总", summary_path, required=False)
    sections += _inject("角色矩阵", matrix_path, required=False)

    task = f"""你的任务是审核第{chapter_num}章。

{INJECTION_NOTE}{sections}

审核完成后，将审计报告写入：{audit_report_path}

重要：在报告末尾，必须单独一行输出审核结论标记：
- 如果审核通过，请输出：[AUDIT_RESULT: PASS]
- 如果审核不通过，请输出：[AUDIT_RESULT: FAIL]
"""

    try:
        result = await call_subagent("continuity-auditor", task, parent_model=model_name)
        passed = _parse_audit_result(result)
        logger.info(f"Audit result for chapter {chapter_num}: {'PASS' if passed else 'FAIL'}")
        return {
            "audit_report": audit_report_path,
            "audit_passed": passed,
            "audit_round": state.get("audit_round", 0) + 1,
        }
    except Exception as e:
        logger.error(f"Audit chapter failed: {e}")
        return {"errors": [f"Audit chapter failed: {e}"]}


async def revise_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    chapter_content = state.get("chapter_content", "")
    audit_report = state.get("audit_report", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: revising chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    output_path = f"{novel_base}/02-正文/{chapter_group}/第{chapter_num}章.md"
    modify_record_path = f"{novel_base}/04-审稿/第{chapter_num}章-修改记录.md"

    bible_path = f"{novel_base}/00-世界观/故事圣经.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"

    content_data = read_file_safe(chapter_content)
    report_data = read_file_safe(audit_report)
    bible_data = read_file_safe(bible_path)
    outline_data = read_file_safe(outline_path)

    sections = _inject_data("章节正文", chapter_content, content_data)
    sections += _inject_data("审计报告", audit_report, report_data)
    sections += _inject_data("故事圣经", bible_path, bible_data)
    sections += _inject_data("章节细纲", outline_path, outline_data)

    task = f"""你的任务是根据审计报告修改第{chapter_num}章正文。

{INJECTION_NOTE}{sections}

根据审计报告中的问题逐项修改正文，修改后：
- 覆盖写入：{output_path}
- 将修改记录写入：{modify_record_path}
"""

    try:
        result = await call_subagent("novel-reviser", task, parent_model=model_name)
        return {"chapter_content": output_path}
    except Exception as e:
        logger.error(f"Revise chapter failed: {e}")
        return {"errors": [f"Revise chapter failed: {e}"]}


async def _post_process_summary(state: NovelWorkflowState) -> dict[str, Any]:
    """Generate chapter summary."""
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"

    content_data = read_file_safe(chapter_content)
    summary_data = read_file_safe(summary_path)

    summary_sections = _inject_data("章节正文", chapter_content, content_data)
    summary_sections += _inject_data("已有章节摘要汇总", summary_path, summary_data)

    summary_task = f"""你的任务是生成第{chapter_num}章摘要。

{INJECTION_NOTE}{summary_sections}

生成摘要后，追加写入：{summary_path}
"""

    try:
        summary_result = await call_subagent("chapter-summarizer", summary_task, parent_model=model_name)
        return {"chapter_summary": summary_result}
    except Exception as e:
        logger.error(f"Chapter summarizer failed: {e}")
        return {"errors": [f"Chapter summarizer failed: {e}"]}


async def _post_process_state(state: NovelWorkflowState) -> dict[str, Any]:
    """Update state card."""
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    matrix_path = f"{novel_base}/00-世界观/角色矩阵.md"
    subplot_path = f"{novel_base}/00-世界观/支线板.md"
    emotional_path = f"{novel_base}/00-世界观/情感弧线.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"

    content_data = read_file_safe(chapter_content)
    state_data = read_file_safe(state_path)
    hook_data = read_file_safe(hook_path)
    summary_data = read_file_safe(summary_path)
    matrix_data = read_file_safe(matrix_path)
    subplot_data = read_file_safe(subplot_path)
    emotional_data = read_file_safe(emotional_path)
    outline_data = read_file_safe(outline_path)

    state_sections = _inject_data("章节正文", chapter_content, content_data)
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
        return {"state_updated": True}
    except Exception as e:
        logger.error(f"State settler failed: {e}")
        return {"errors": [f"State settler failed: {e}"]}


async def _post_process_hooks(state: NovelWorkflowState) -> dict[str, Any]:
    """Update hooks pool."""
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"

    content_data = read_file_safe(chapter_content)
    hook_data = read_file_safe(hook_path)
    outline_data = read_file_safe(outline_path)

    hook_sections = _inject_data("章节正文", chapter_content, content_data)
    hook_sections += _inject_data("伏笔池", hook_path, hook_data)
    hook_sections += _inject_data("章节细纲", outline_path, outline_data)

    hook_task = f"""你的任务是更新伏笔池。

章节号：{chapter_num}
更新伏笔池文件：{hook_path}

{INJECTION_NOTE}{hook_sections}
"""

    try:
        await call_subagent("hook-manager", hook_task, parent_model=model_name)
        return {"hooks_updated": True}
    except Exception as e:
        logger.error(f"Hook manager failed: {e}")
        return {"errors": [f"Hook manager failed: {e}"]}


async def _post_process_card(state: NovelWorkflowState) -> dict[str, Any]:
    """Update novel card."""
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    card_path = f"{novel_base}/card.json"

    card_data = read_file_safe(card_path)
    content_data = read_file_safe(chapter_content)

    card_sections = _inject_data("小说名片", card_path, card_data)
    card_sections += _inject_data("章节正文", chapter_content, content_data)

    card_task = f"""你的任务是更新小说名片。

章节号：{chapter_num}
更新名片文件：{card_path}

{INJECTION_NOTE}{card_sections}
"""

    try:
        await call_subagent("card-manager", card_task, parent_model=model_name)
        return {"card_updated": True}
    except Exception as e:
        logger.error(f"Card manager failed: {e}")
        return {"errors": [f"Card manager failed: {e}"]}


async def post_process_sequential(state: NovelWorkflowState) -> dict[str, Any]:
    """Sequential post-processing: run all sub-agents one by one."""
    results = {}

    summary_result = await _post_process_summary(state)
    results.update(summary_result)

    state_result = await _post_process_state(state)
    results.update(state_result)

    hooks_result = await _post_process_hooks(state)
    results.update(hooks_result)

    card_result = await _post_process_card(state)
    results.update(card_result)

    return results


async def post_process_parallel(state: NovelWorkflowState) -> dict[str, Any]:
    """Parallel post-processing: run all sub-agents concurrently."""
    import asyncio

    results = await asyncio.gather(
        _post_process_summary(state),
        _post_process_state(state),
        _post_process_hooks(state),
        _post_process_card(state),
        return_exceptions=True,
    )

    merged = {}
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
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)

    logger.info(f"Writing workflow: post-processing chapter {chapter_num}")

    if _is_parallel_enabled():
        logger.info("Post-process: using parallel execution")
        return await post_process_parallel(state)
    else:
        logger.info("Post-process: using sequential execution")
        return await post_process_sequential(state)


async def sync_outline(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: syncing outline for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    volume_path = f"{novel_base}/01-规划/卷纲.md"

    outline_data = read_file_safe(outline_path)
    volume_data = read_file_safe(volume_path)

    sections = _inject_data("细纲", outline_path, outline_data)
    sections += _inject_data("卷纲", volume_path, volume_data)

    task = f"""你的任务是同步细纲（sync模式）。

章节号：{chapter_num}
小说根目录：{novel_base}

{INJECTION_NOTE}{sections}

请根据正文内容，更新当前章节的完成状态。
"""

    try:
        await call_subagent("outline-planner", task, parent_model=model_name)
        return {"outline_synced": True}
    except Exception as e:
        logger.error(f"Sync outline failed: {e}")
        return {"errors": [f"Sync outline failed: {e}"]}


def should_revise(state: NovelWorkflowState) -> str:
    if state.get("audit_passed"):
        return "post_process"
    if state.get("audit_round", 0) >= 2:
        return "post_process"
    return "revise"


def create_writing_workflow() -> StateGraph:
    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("write_chapter", write_chapter)
    workflow.add_node("audit", audit_chapter)
    workflow.add_node("revise", revise_chapter)
    workflow.add_node("post_process", post_process)
    workflow.add_node("sync_outline", sync_outline)

    workflow.set_entry_point("write_chapter")
    workflow.add_edge("write_chapter", "audit")

    workflow.add_conditional_edges(
        "audit",
        should_revise,
        {
            "revise": "revise",
            "post_process": "post_process",
        },
    )

    workflow.add_edge("revise", "audit")
    workflow.add_edge("post_process", "sync_outline")
    workflow.add_edge("sync_outline", END)

    return workflow.compile()


register_workflow("writing", create_writing_workflow)
