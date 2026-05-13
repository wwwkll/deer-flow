"""Novel writing workflow - Writing, audit, and post-processing."""

import logging
import os
import re
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.config.subagents_config import get_subagents_app_config
from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe, update_novel_card
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState
from my_tools.path_resolver import set_current_thread_id

logger = logging.getLogger(__name__)

_AUDIT_RESULT_PATTERN = re.compile(r"\[AUDIT_RESULT:\s*(PASS|FAIL)\]", re.IGNORECASE)


def _is_parallel_enabled() -> bool:
    """Check if workflow parallel execution is enabled from config."""
    try:
        config = get_subagents_app_config()
        return config.workflow_parallel_enabled
    except Exception:
        return True


def _get_rel_path(path: str) -> str:
    """Extract relative path from novel base directory."""
    from deerflow.workflows.helpers import get_novel_base
    novel_base = get_novel_base()
    if not novel_base:
        return path
    path_normalized = path.replace("\\", "/")
    novel_base_normalized = novel_base.replace("\\", "/")
    if path_normalized.startswith(novel_base_normalized + "/"):
        return path_normalized.replace(novel_base_normalized + "/", "")
    return path_normalized


# def _inject(label: str, path: str, required: bool = True) -> str:
#     content = read_file_safe(path)
#     if content:
#         return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
#     if required:
#         return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"
#     return f"## {label}\n路径：{path}\n[文件不存在，跳过]\n"


# def _inject_data(label: str, path: str, data: str | None) -> str:
#     if data:
#         return f"## {label}（已注入，不要再用read_file读取）\n\n{data}\n"
#     return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"


async def check_task_summary(state: NovelWorkflowState) -> dict[str, Any]:
    """检查写作任务汇总文件是否已生成，未生成则终止工作流。"""
    set_current_thread_id(state.get("thread_id"))

    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    writing_task_summary = state.get("writing_task_summary", "")

    if writing_task_summary and len(writing_task_summary.strip()) > 50:
        logger.info("写作任务汇总已通过 state 注入，跳过文件检查")
        return {}

    novel_base = get_novel_base(thread_id=state.get("thread_id"))
    if not novel_base:
        return {"errors": ["无法获取小说根目录，请检查全局变量 novel_toc"]}

    chapter_group_normalized = normalize_chapter_group(chapter_group)
    task_summary_path = os.path.join(
        novel_base, "02-正文", chapter_group_normalized, "_task", "写作任务汇总.md"
    )

    if not os.path.exists(task_summary_path):
        rel_path = _get_rel_path(task_summary_path)
        error_msg = (
            f"工作流运行失败，未检测到 {rel_path} 文件，"
            f"请运行整理工作流（organize）重新生成"
        )
        logger.error(error_msg)
        return {"errors": [error_msg]}

    logger.info(f"写作任务汇总文件检查通过: {task_summary_path}")
    return {}


def _should_proceed_to_write(state: NovelWorkflowState) -> str:
    """判断是否可以进入写作阶段。"""
    errors = state.get("errors", [])
    if errors:
        for err in errors:
            if "写作任务汇总" in err:
                return "end_with_error"
    return "write_chapter"


async def write_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
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
    output_path = f"{novel_base}/02-正文/{chapter_group_normalized}/第{chapter_num}章.md"

    task = f"你的任务是撰写第{chapter_num}章正文。\n\n小说根目录：{novel_base}\n\n将正文写入：{output_path}\n"

    try:
        result_text = await call_subagent("novel-writer", task, parent_model=model_name)

        # 兜底：检查子Agent是否成功将正文写入文件
        output_path_obj = Path(output_path)
        if not output_path_obj.exists() or output_path_obj.stat().st_size < 500:
            logger.warning(
                f"Chapter file not written by sub-agent ({output_path}), "
                f"extracting from response ({len(result_text)} chars)"
            )
            chapter_content = _extract_chapter_text(result_text, chapter_num)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            output_path_obj.write_text(chapter_content, encoding="utf-8")
            logger.info(
                f"Chapter written from response fallback: {output_path} "
                f"({len(chapter_content)} chars)"
            )

        return {"chapter_content": output_path, "chapter_group": chapter_group_normalized}
    except Exception as e:
        logger.error(f"Write chapter failed: {e}")
        return {"errors": [f"Write chapter failed: {e}"]}


# 正文可能以"好的，我需要撰写第X章..."之类的规划文字开头的行首关键词
_PLANNING_PREFIX_PATTERNS = re.compile(
    r"^(好的[，,。]?|现在[，,]?\s*我需要|根据[，,]|首先[，,]|接下来[，,]|我需要|"
    r"本章[的]?|以下是|正文如下|第\d+章[\.。、，,])"
)


def _extract_chapter_text(raw_text: str, chapter_num: int) -> str:
    lines = raw_text.strip().split("\n")
    start_idx = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not _PLANNING_PREFIX_PATTERNS.match(stripped):
            start_idx = i
            break

    content_lines = lines[start_idx:]
    content = "\n".join(content_lines).strip()
    if len(content) < 100 and start_idx > 0:
        content = "\n".join(lines).strip()

    return content


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

    task = f"你的任务是审核第{chapter_num}章。\n\n小说根目录：{novel_base}\n\n审核完成后，将审计报告写入：{audit_report_path}\n\n重要：在报告末尾，必须单独一行输出审核结论标记：\n- 如果审核通过，请输出：[AUDIT_RESULT: PASS]\n- 如果审核不通过，请输出：[AUDIT_RESULT: FAIL]\n"

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
        return {
            "errors": [f"Audit chapter failed: {e}"],
            "audit_passed": False,
            "audit_round": state.get("audit_round", 0) + 1,
        }


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

    task = f"你的任务是根据审计报告修改第{chapter_num}章正文。\n\n小说根目录：{novel_base}\n\n根据审计报告中的问题逐项修改正文，修改后：\n- 覆盖写入：{output_path}\n- 将修改记录写入：{modify_record_path}\n"

    try:
        result = await call_subagent("novel-reviser", task, parent_model=model_name)
        return {"chapter_content": output_path}
    except Exception as e:
        logger.error(f"Revise chapter failed: {e}")
        return {"errors": [f"Revise chapter failed: {e}"]}


async def _post_process_state(state: NovelWorkflowState) -> dict[str, Any]:
    """Update state card via world-updater."""
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    state_path = f"{novel_base}/00-世界观/当前状态卡.md"
    chapter_group_normalized = normalize_chapter_group(chapter_group)
    chapter_path = f"{novel_base}/02-正文/{chapter_group_normalized}/第{chapter_num}章.md"

    state_task = (
        f"你的任务是更新当前状态卡。\n\n"
        f"当前阶段：writing（正文写作阶段）\n"
        f"更新对象类型：正文写完后的世界观文本\n"
        f"这意味着第{chapter_num}章正文已经写完，事件已实际发生，伏笔可以标记为正文已回收。\n\n"
        f"小说根目录：{novel_base}\n\n"
        f"正文文件路径（直接用read_file读取，不要搜索）：{chapter_path}\n"
        f"更新状态文件：{state_path}\n"
    )

    try:
        await call_subagent("world-updater", state_task, parent_model=model_name)
        return {"state_updated": True}
    except Exception as e:
        logger.error(f"State update failed: {e}")
        return {"errors": [f"State update failed: {e}"]}


async def _post_process_hooks(state: NovelWorkflowState) -> dict[str, Any]:
    """Update hooks pool via world-updater."""
    chapter_num = state.get("chapter_num", 0)
    chapter_group = state.get("chapter_group", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        return {"errors": ["无法获取小说根目录"]}
    hook_path = f"{novel_base}/00-世界观/待办事项.md"
    chapter_group_normalized = normalize_chapter_group(chapter_group)
    chapter_path = f"{novel_base}/02-正文/{chapter_group_normalized}/第{chapter_num}章.md"

    hook_task = (
        f"你的任务是更新伏笔池（待办事项.md）。\n\n"
        f"当前阶段：writing（正文写作阶段）\n"
        f"更新对象类型：正文写完后的世界观文本\n"
        f"这意味着第{chapter_num}章正文已经写完，事件已实际发生，伏笔可以标记为正文已回收。\n\n"
        f"章节号：{chapter_num}\n"
        f"小说根目录：{novel_base}\n\n"
        f"正文文件路径（直接用read_file读取，不要搜索）：{chapter_path}\n"
        f"更新伏笔池文件：{hook_path}\n"
    )

    try:
        await call_subagent("world-updater", hook_task, parent_model=model_name)
        return {"hooks_updated": True}
    except Exception as e:
        logger.error(f"Hooks update failed: {e}")
        return {"errors": [f"Hooks update failed: {e}"]}


async def post_process_sequential(state: NovelWorkflowState) -> dict[str, Any]:
    """Sequential post-processing: run all sub-agents one by one."""
    results = {}

    state_result = await _post_process_state(state)
    results.update(state_result)

    hooks_result = await _post_process_hooks(state)
    results.update(hooks_result)

    return results


async def post_process_parallel(state: NovelWorkflowState) -> dict[str, Any]:
    """Parallel post-processing: run all sub-agents concurrently."""
    import asyncio

    results = await asyncio.gather(
        _post_process_state(state),
        _post_process_hooks(state),
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


def should_revise(state: NovelWorkflowState) -> str:
    if state.get("audit_passed"):
        return "post_process"
    if state.get("audit_round", 0) >= 2:
        return "post_process"
    return "revise"


def create_writing_workflow() -> StateGraph:
    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("check_task_summary", check_task_summary)
    workflow.add_node("write_chapter", write_chapter)
    workflow.add_node("audit", audit_chapter)
    workflow.add_node("revise", revise_chapter)
    workflow.add_node("post_process", post_process)

    workflow.set_entry_point("check_task_summary")

    workflow.add_conditional_edges(
        "check_task_summary",
        _should_proceed_to_write,
        {
            "write_chapter": "write_chapter",
            "end_with_error": END,
        },
    )

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
    workflow.add_edge("post_process", END)

    return workflow.compile()


register_workflow("writing", create_writing_workflow)
