"""Novel writing workflow - Writing, audit, and post-processing."""

import logging
import re
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.workflows.helpers import call_subagent, get_novel_base, normalize_chapter_group, read_file_safe
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

logger = logging.getLogger(__name__)

_AUDIT_RESULT_PATTERN = re.compile(r"\[AUDIT_RESULT:\s*(PASS|FAIL)\]", re.IGNORECASE)


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

    def _inject(label: str, path: str, required: bool = True) -> str:
        content = read_file_safe(path)
        if content:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{content}\n"
        if required:
            return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"
        return f"## {label}\n路径：{path}\n[文件不存在，跳过]\n"

    sections = _inject("写作任务汇总", writing_task_summary)
    sections += _inject("样式指纹", style_path)
    sections += _inject("上一章正文", prev_chapter_path, required=False)

    task = f"""你的任务是撰写第{chapter_num}章正文。

以下参考内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

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
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: auditing chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    audit_report_path = f"{novel_base}/04-审稿/第{chapter_num}章-审计报告.md"

    content_data = read_file_safe(chapter_content)
    if content_data:
        chapter_section = f"## 章节正文（已注入，不要再用read_file读取）\n\n{content_data}\n"
    else:
        chapter_section = f"## 章节正文\n路径：{chapter_content}\n[未成功注入，请用read_file自行读取]\n"

    task = f"""你的任务是审核第{chapter_num}章。

以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{chapter_section}

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

    content_data = read_file_safe(chapter_content)
    report_data = read_file_safe(audit_report)

    def _inject(label: str, path: str, data: str | None) -> str:
        if data:
            return f"## {label}（已注入，不要再用read_file读取）\n\n{data}\n"
        return f"## {label}\n路径：{path}\n[未成功注入，请用read_file自行读取]\n"

    sections = _inject("章节正文", chapter_content, content_data)
    sections += _inject("审计报告", audit_report, report_data)

    task = f"""你的任务是根据审计报告修改第{chapter_num}章正文。

以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

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


async def post_process(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    chapter_content = state.get("chapter_content", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: post-processing chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    summary_path = f"{novel_base}/03-状态/章节摘要汇总.md"
    state_path = f"{novel_base}/03-状态/当前状态卡.md"
    hook_path = f"{novel_base}/03-状态/待办事项.md"
    card_path = f"{novel_base}/card.json"

    content_data = read_file_safe(chapter_content)
    if content_data:
        chapter_section = f"## 章节正文（已注入，不要再用read_file读取）\n\n{content_data}\n"
    else:
        chapter_section = f"## 章节正文\n路径：{chapter_content}\n[未成功注入，请用read_file自行读取]\n"

    injection_note = '以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。\n标注"未成功注入"的，请用read_file按路径自行读取。\n\n'

    results = {}

    try:
        summary_task = f"""你的任务是生成第{chapter_num}章摘要。

{injection_note}{chapter_section}

生成摘要后，追加写入：{summary_path}
"""
        summary_result = await call_subagent("chapter-summarizer", summary_task, parent_model=model_name)
        results["chapter_summary"] = summary_result
    except Exception as e:
        logger.error(f"Chapter summarizer failed: {e}")

    try:
        state_task = f"""你的任务是更新当前状态卡。

{injection_note}{chapter_section}

更新状态文件：{state_path}
"""
        await call_subagent("state-settler", state_task, parent_model=model_name)
        results["state_updated"] = True
    except Exception as e:
        logger.error(f"State settler failed: {e}")

    try:
        hook_task = f"""你的任务是更新伏笔池。

章节号：{chapter_num}
更新伏笔池文件：{hook_path}

{injection_note}{chapter_section}
"""
        await call_subagent("hook-manager", hook_task, parent_model=model_name)
        results["hooks_updated"] = True
    except Exception as e:
        logger.error(f"Hook manager failed: {e}")

    try:
        card_task = f"""你的任务是更新小说名片。

章节号：{chapter_num}
更新名片文件：{card_path}

{injection_note}{chapter_section}
"""
        await call_subagent("card-manager", card_task, parent_model=model_name)
        results["card_updated"] = True
    except Exception as e:
        logger.error(f"Card manager failed: {e}")

    return results


async def sync_outline(state: NovelWorkflowState) -> dict[str, Any]:
    novel_name = state.get("novel_name", "")
    chapter_num = state.get("chapter_num", 0)
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")

    logger.info(f"Writing workflow: syncing outline for chapter {chapter_num}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    chapter_group = state.get("chapter_group", "")
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

    task = f"""你的任务是同步细纲（sync模式）。

章节号：{chapter_num}
小说根目录：{novel_base}

以下内容已为你注入，标注"已注入"的不要用read_file重复读取，因为上下文有限。
标注"未成功注入"的，请用read_file按路径自行读取。

{sections}

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
