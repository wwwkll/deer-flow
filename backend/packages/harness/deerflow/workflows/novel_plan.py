"""Novel plan workflow - Planning tasks with outline audit loop and summary update."""

import logging
from typing import Any

from langgraph.graph import END, StateGraph
from my_tools.path_resolver import set_current_thread_id

from deerflow.workflows.helpers import call_subagent, get_novel_base, parse_audit_result
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

logger = logging.getLogger(__name__)


async def call_planner(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    planner_name = state.get("planner_name", "")
    planner_mode = state.get("planner_mode", "")
    planner_task = state.get("planner_task", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")
    novel_name = state.get("novel_name", "")
    user_request = state.get("user_request", "")

    logger.info("[PLAN_WORKFLOW] ====== call_planner START ======")
    logger.info(f"[PLAN_WORKFLOW] planner_name={planner_name}, planner_mode={planner_mode}, novel_name={novel_name}")
    logger.info(f"[PLAN_WORKFLOW] chapter_group={state.get('chapter_group', '')}, model_name={model_name}")

    if not planner_name:
        logger.error("[PLAN_WORKFLOW] Missing required parameter: planner_name")
        raise ValueError("缺少必需参数: planner_name")

    valid_planners = {"outline-planner", "volume-planner", "book-rules-manager"}
    if planner_name not in valid_planners:
        logger.error(f"[PLAN_WORKFLOW] Invalid planner_name={planner_name}, valid={valid_planners}")
        raise ValueError(f"不支持的规划Agent: {planner_name}，可选: {', '.join(valid_planners)}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base, check global variable novel_toc")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")
    logger.info(f"[PLAN_WORKFLOW] novel_base={novel_base}")

    chapter_group = state.get("chapter_group", "")

    task_parts = []
    if planner_mode:
        task_parts.append(f"任务模式：{planner_mode}")
    if chapter_group:
        task_parts.append(f"章节范围：{chapter_group}")
    if planner_task:
        task_parts.append(f"具体要求：{planner_task}")
    task_parts.append(f"小说根目录：{novel_base}")

    if user_request and user_request.strip():
        task_parts.append(f"【用户特殊要求】\n{user_request.strip()}\n请务必在规划中落实以上用户要求。")

    task = "\n".join(task_parts)
    logger.info(f"[PLAN_WORKFLOW] Task prepared for {planner_name}, task_length={len(task)}")

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling subagent {planner_name} (model={model_name})")
        await call_subagent(planner_name, task, parent_model=model_name)
        logger.info(f"[PLAN_WORKFLOW] Subagent {planner_name} completed successfully")
        logger.info("[PLAN_WORKFLOW] ====== call_planner END (success) ======")
        return {}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] Subagent {planner_name} failed: {e}")
        logger.info("[PLAN_WORKFLOW] ====== call_planner END (failed) ======")
        return {"errors": [f"{planner_name} failed: {e}"]}


def _route_after_planner(state: NovelWorkflowState) -> str:
    errors = state.get("errors", [])
    planner_name = state.get("planner_name", "")

    logger.info(f"[PLAN_WORKFLOW] _route_after_planner: planner_name={planner_name}, errors_count={len(errors)}")

    if errors:
        has_planner_error = any("failed" in str(e).lower() for e in errors)
        if has_planner_error:
            logger.warning(f"[PLAN_WORKFLOW] Planner failed, ending workflow. errors={errors}")
            return "end_with_error"

    if planner_name == "book-rules-manager":
        logger.info("[PLAN_WORKFLOW] book-rules-manager does not need audit or summary update, route to end")
        return "end_no_update"

    if planner_name == "outline-planner":
        logger.info("[PLAN_WORKFLOW] outline-planner requires audit, route to audit_outline")
        return "audit_outline"

    if planner_name == "volume-planner":
        logger.info("[PLAN_WORKFLOW] volume-planner does not need audit, route to update_outline_summary")
        return "update_outline_summary"

    logger.info(f"[PLAN_WORKFLOW] Unknown planner_name={planner_name}, route to end")
    return "end_no_update"


async def audit_outline(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    chapter_group = state.get("chapter_group", "")
    model_name = state.get("model_name")
    thread_id = state.get("thread_id")
    user_request = state.get("user_request", "")
    outline_audit_round = state.get("outline_audit_round", 0)

    logger.info(f"[PLAN_WORKFLOW] ====== audit_outline START (round={outline_audit_round}) ======")
    logger.info(f"[PLAN_WORKFLOW] chapter_group={chapter_group}, model_name={model_name}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in audit_outline")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    audit_report_path = f"{novel_base}/04-审稿/{chapter_group}-审核报告.md"

    logger.info(f"[PLAN_WORKFLOW] outline_path={outline_path}")
    logger.info(f"[PLAN_WORKFLOW] audit_report_path={audit_report_path}")

    task_parts = [
        f"请对细纲进行第 {outline_audit_round + 1} 轮审核。",
        f"章节范围：{chapter_group}",
        f"小说根目录：{novel_base}",
        f"待审核细纲路径：{outline_path}",
        f"审核报告输出路径：{audit_report_path}",
    ]

    if user_request and user_request.strip():
        task_parts.append(f"【用户特殊要求】\n{user_request.strip()}\n请额外检查细纲是否符合以上用户要求。")

    task = "\n".join(task_parts)

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling outline-auditor (model={model_name})")
        await call_subagent("outline-auditor", task, parent_model=model_name)
        logger.info("[PLAN_WORKFLOW] outline-auditor completed successfully")

        import os

        if os.path.exists(audit_report_path):
            with open(audit_report_path, encoding="utf-8") as f:
                report_content = f.read()
            audit_passed = parse_audit_result(report_content)
            logger.info(f"[PLAN_WORKFLOW] Audit result: {'PASS' if audit_passed else 'FAIL'}")
        else:
            logger.warning(f"[PLAN_WORKFLOW] Audit report not found at {audit_report_path}, defaulting to FAIL")
            audit_passed = False

        logger.info(f"[PLAN_WORKFLOW] ====== audit_outline END (passed={audit_passed}) ======")
        return {
            "outline_audit_passed": audit_passed,
            "outline_audit_round": outline_audit_round + 1,
            "outline_audit_report": audit_report_path,
        }
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] outline-auditor failed: {e}")
        logger.info("[PLAN_WORKFLOW] ====== audit_outline END (failed) ======")
        return {
            "outline_audit_passed": False,
            "outline_audit_round": outline_audit_round + 1,
            "errors": [f"outline-auditor failed: {e}"],
        }


def _should_revise_outline(state: NovelWorkflowState) -> str:
    outline_audit_passed = state.get("outline_audit_passed", False)
    outline_audit_round = state.get("outline_audit_round", 0)

    logger.info(f"[PLAN_WORKFLOW] _should_revise_outline: passed={outline_audit_passed}, round={outline_audit_round}")

    if outline_audit_passed:
        logger.info("[PLAN_WORKFLOW] Audit passed, route to update_outline_summary")
        return "update_outline_summary"

    if outline_audit_round >= 2:
        logger.warning("[PLAN_WORKFLOW] Audit failed after 2 rounds, forcing update_outline_summary")
        return "update_outline_summary"

    logger.info("[PLAN_WORKFLOW] Audit failed, route to revise_outline")
    return "revise_outline"


async def revise_outline(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    chapter_group = state.get("chapter_group", "")
    model_name = state.get("model_name")
    thread_id = state.get("thread_id")
    user_request = state.get("user_request", "")
    outline_audit_round = state.get("outline_audit_round", 0)

    logger.info(f"[PLAN_WORKFLOW] ====== revise_outline START (round={outline_audit_round}) ======")
    logger.info(f"[PLAN_WORKFLOW] chapter_group={chapter_group}, model_name={model_name}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in revise_outline")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    audit_report_path = f"{novel_base}/04-审稿/{chapter_group}-审核报告.md"
    modify_record_path = f"{novel_base}/04-审稿/{chapter_group}-修改记录.md"

    logger.info(f"[PLAN_WORKFLOW] outline_path={outline_path}")
    logger.info(f"[PLAN_WORKFLOW] audit_report_path={audit_report_path}")
    logger.info(f"[PLAN_WORKFLOW] modify_record_path={modify_record_path}")

    task_parts = [
        "请根据审核报告修改细纲。",
        f"章节范围：{chapter_group}",
        f"小说根目录：{novel_base}",
        f"待修改细纲路径：{outline_path}",
        f"审核报告路径：{audit_report_path}",
        f"修改记录输出路径：{modify_record_path}",
    ]

    if user_request and user_request.strip():
        task_parts.append(f"【用户特殊要求】\n{user_request.strip()}\n请在修改时参考以上用户要求。")

    task = "\n".join(task_parts)

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling outline-reviser (model={model_name})")
        await call_subagent("outline-reviser", task, parent_model=model_name)
        logger.info("[PLAN_WORKFLOW] outline-reviser completed successfully")
        logger.info("[PLAN_WORKFLOW] ====== revise_outline END (success) ======")
        return {}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] outline-reviser failed: {e}")
        logger.info("[PLAN_WORKFLOW] ====== revise_outline END (failed) ======")
        return {"errors": [f"outline-reviser failed: {e}"]}


async def update_outline_summary(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    chapter_group = state.get("chapter_group", "")
    model_name = state.get("model_name")
    thread_id = state.get("thread_id")

    logger.info("[PLAN_WORKFLOW] ====== update_outline_summary START ======")
    logger.info(f"[PLAN_WORKFLOW] chapter_group={chapter_group}, model_name={model_name}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in update_outline_summary")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    summary_path = f"{novel_base}/00-世界观/细纲摘要.md"

    logger.info(f"[PLAN_WORKFLOW] outline_path={outline_path}")
    logger.info(f"[PLAN_WORKFLOW] summary_path={summary_path}")

    task_parts = [
        "请根据细纲内容更新细纲摘要文档。",
        f"章节范围：{chapter_group}",
        f"小说根目录：{novel_base}",
        f"细纲路径：{outline_path}",
        f"细纲摘要路径：{summary_path}",
    ]

    task = "\n".join(task_parts)

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling outline-summarizer (model={model_name})")
        await call_subagent("outline-summarizer", task, parent_model=model_name)
        logger.info("[PLAN_WORKFLOW] outline-summarizer completed successfully")
        logger.info("[PLAN_WORKFLOW] ====== update_outline_summary END (success) ======")
        return {"outline_summary_updated": True}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] outline-summarizer failed: {e}")
        logger.info("[PLAN_WORKFLOW] ====== update_outline_summary END (failed) ======")
        return {"outline_summary_updated": False, "errors": [f"outline-summarizer failed: {e}"]}


def create_plan_workflow() -> StateGraph:
    logger.info("[PLAN_WORKFLOW] Creating plan workflow")

    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("call_planner", call_planner)
    workflow.add_node("audit_outline", audit_outline)
    workflow.add_node("revise_outline", revise_outline)
    workflow.add_node("update_outline_summary", update_outline_summary)

    workflow.set_entry_point("call_planner")

    workflow.add_conditional_edges(
        "call_planner",
        _route_after_planner,
        {
            "audit_outline": "audit_outline",
            "update_outline_summary": "update_outline_summary",
            "end_no_update": END,
            "end_with_error": END,
        },
    )

    workflow.add_conditional_edges(
        "audit_outline",
        _should_revise_outline,
        {
            "revise_outline": "revise_outline",
            "update_outline_summary": "update_outline_summary",
        },
    )

    workflow.add_edge("revise_outline", "audit_outline")
    workflow.add_edge("update_outline_summary", END)

    logger.info("[PLAN_WORKFLOW] Plan workflow created successfully")
    return workflow.compile()


logger.info("[PLAN_WORKFLOW] Registering plan workflow")
register_workflow("plan", create_plan_workflow)
logger.info("[PLAN_WORKFLOW] Plan workflow registered")
