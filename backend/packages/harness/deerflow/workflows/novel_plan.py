"""Novel plan workflow - Planning tasks with world-view auto-update."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from deerflow.config.subagents_config import get_subagents_app_config
from deerflow.workflows.helpers import call_subagent, get_novel_base
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState
from my_tools.path_resolver import set_current_thread_id

logger = logging.getLogger(__name__)

_INJECTION_NOTE = "【重要提示】以下是需要参考的文件路径，请使用 read_file 工具自行读取：\n\n"


def _is_parallel_enabled() -> bool:
    try:
        config = get_subagents_app_config()
        return config.workflow_parallel_enabled
    except Exception:
        return True


def _inject(label: str, path: str) -> str:
    return f"## {label}\n路径：{path}\n[请用read_file自行读取]\n"


async def call_planner(state: NovelWorkflowState) -> dict[str, Any]:
    set_current_thread_id(state.get("thread_id"))

    planner_name = state.get("planner_name", "")
    planner_mode = state.get("planner_mode", "")
    planner_task = state.get("planner_task", "")
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")
    novel_name = state.get("novel_name", "")

    logger.info(f"[PLAN_WORKFLOW] ====== call_planner START ======")
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

    task = "\n".join(task_parts)
    logger.info(f"[PLAN_WORKFLOW] Task prepared for {planner_name}, task_length={len(task)}")

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling subagent {planner_name} (model={model_name})")
        result = await call_subagent(planner_name, task, parent_model=model_name)
        logger.info(f"[PLAN_WORKFLOW] Subagent {planner_name} completed successfully")
        logger.info(f"[PLAN_WORKFLOW] ====== call_planner END (success) ======")
        return {}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] Subagent {planner_name} failed: {e}")
        logger.info(f"[PLAN_WORKFLOW] ====== call_planner END (failed) ======")
        return {"errors": [f"{planner_name} failed: {e}"]}


def _should_update_world(state: NovelWorkflowState) -> str:
    errors = state.get("errors", [])
    planner_name = state.get("planner_name", "")

    logger.info(f"[PLAN_WORKFLOW] _should_update_world: planner_name={planner_name}, errors_count={len(errors)}")

    if errors:
        has_planner_error = any("failed" in str(e).lower() for e in errors)
        if has_planner_error:
            logger.warning(f"[PLAN_WORKFLOW] Planner failed, skipping world update. errors={errors}")
            return "end_with_error"

    if planner_name in ("outline-planner", "volume-planner"):
        logger.info(f"[PLAN_WORKFLOW] Planner {planner_name} requires world update, route to scan_world_files")
        return "scan_world_files"

    logger.info(f"[PLAN_WORKFLOW] Planner {planner_name} does not require world update, route to end")
    return "end_no_update"


async def scan_world_files(state: NovelWorkflowState) -> dict[str, Any]:
    thread_id = state.get("thread_id")
    novel_name = state.get("novel_name", "")

    logger.info(f"[PLAN_WORKFLOW] ====== scan_world_files START ======")
    logger.info(f"[PLAN_WORKFLOW] novel_name={novel_name}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in scan_world_files")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    world_dir = Path(f"{novel_base}/00-世界观")
    logger.info(f"[PLAN_WORKFLOW] Scanning world_dir={world_dir}")

    if not world_dir.exists():
        logger.warning(f"[PLAN_WORKFLOW] World directory does not exist: {world_dir}")
        logger.info(f"[PLAN_WORKFLOW] ====== scan_world_files END (no dir) ======")
        return {"world_files": []}

    world_files = []
    for f in sorted(world_dir.iterdir()):
        if f.is_file() and f.suffix == ".md":
            world_files.append(str(f))

    logger.info(f"[PLAN_WORKFLOW] Found {len(world_files)} world files to update:")
    for idx, wf in enumerate(world_files, 1):
        logger.info(f"[PLAN_WORKFLOW]   [{idx}] {Path(wf).name}")

    logger.info(f"[PLAN_WORKFLOW] ====== scan_world_files END (found {len(world_files)} files) ======")
    return {"world_files": world_files}


async def _update_all_world_files_batch(
    world_files: list[str],
    novel_base: str,
    planner_name: str,
    planner_mode: str,
    chapter_group: str,
    model_name: str | None,
) -> dict[str, Any]:
    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_batch START ======")
    logger.info(f"[PLAN_WORKFLOW] total_files={len(world_files)}, mode=batch")

    outline_path = ""
    if planner_name == "outline-planner" and chapter_group:
        outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    elif planner_name == "volume-planner":
        outline_path = f"{novel_base}/01-规划/卷纲.md"

    card_path = f"{novel_base}/card.json"

    sections = ""
    if outline_path:
        sections += _inject("规划文件（细纲/卷纲）", outline_path)
    sections += _inject("小说名片", card_path)

    sections += "## 待更新的世界观文件\n"
    sections += "以下文件需要逐一评估，判断是否需要根据规划变更进行更新：\n\n"
    for idx, wf in enumerate(world_files, 1):
        file_name = Path(wf).name
        sections += f"{idx}. **{file_name}**：路径：{wf}\n"

    mode_desc = ""
    if planner_name == "outline-planner":
        if planner_mode == "new":
            mode_desc = "新建了细纲"
        elif planner_mode == "revise":
            mode_desc = "修改了细纲"
        elif planner_mode == "sync":
            mode_desc = "同步了细纲"
        else:
            mode_desc = "更新了细纲"
    elif planner_name == "volume-planner":
        if planner_mode == "new":
            mode_desc = "新建了卷纲"
        elif planner_mode == "revise":
            mode_desc = "修改了卷纲"
        else:
            mode_desc = "更新了卷纲"

    task = f"""你的任务是根据{mode_desc}的内容，评估并更新所有需要变更的世界观文件。

当前阶段：outline（细纲规划阶段）
这意味着只是完成了规划，正文尚未写作。更新世界观文件时，事件/伏笔等只能标记为"细纲已规划"或"待正文回收"，不能标记为已完成/已回收。

更新对象类型：细纲对应的世界观文本
规划Agent：{planner_name}（{planner_mode}模式）

{_INJECTION_NOTE}{sections}

【重要工作流程】
1. 先读取规划文件（细纲/卷纲）和小说名片
2. 逐一读取每个世界观文件，判断规划中的变更是否与该文件相关
3. 对于每个文件：
   - 如果完全不相关或无需补充 → 跳过，不操作
   - 如果有需要更新的内容 → 使用 str_replace 精确替换需要变更的部分
4. 所有需要更新的文件处理完毕后结束

【注意事项】
- 跳过不需要更新的文件是正常且鼓励的行为，不要强行修改无关文件
- 每个文件只更新与规划变更相关的内容，保留其他已有内容不变
- 使用 str_replace 精确替换（详见 world-updater 的输出策略）
- 规划文件和小说名片只需读取一次，不要重复读取
"""

    try:
        logger.info(f"[PLAN_WORKFLOW] Calling batch world-updater (model={model_name})")
        result = await call_subagent("world-updater", task, parent_model=model_name)
        logger.info(f"[PLAN_WORKFLOW] Batch world-updater completed successfully")
        logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_batch END (success) ======")
        return {"world_updated": True, "errors": []}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW] Batch world-updater failed: {e}")
        logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_batch END (failed) ======")
        return {"world_updated": True, "errors": [f"Batch world update failed: {e}"]}


async def _update_single_world_file(
    world_file_path: str,
    novel_base: str,
    planner_name: str,
    planner_mode: str,
    chapter_group: str,
    model_name: str | None,
) -> dict[str, Any]:
    file_name = Path(world_file_path).name
    logger.info(f"[PLAN_WORKFLOW] ------ updating world file (fallback): {file_name} ------")

    outline_path = ""
    if planner_name == "outline-planner" and chapter_group:
        outline_path = f"{novel_base}/01-规划/chapters/{chapter_group}-细纲.md"
    elif planner_name == "volume-planner":
        outline_path = f"{novel_base}/01-规划/卷纲.md"

    card_path = f"{novel_base}/card.json"

    sections = ""
    if outline_path:
        sections += _inject("规划文件（细纲/卷纲）", outline_path)
    sections += _inject("小说名片", card_path)
    sections += _inject("目标世界观文件", world_file_path)

    related_files = []
    world_dir = Path(f"{novel_base}/00-世界观")
    if world_dir.exists():
        for f in sorted(world_dir.iterdir()):
            if f.is_file() and f.suffix == ".md" and str(f) != world_file_path:
                related_files.append(str(f))

    if related_files:
        sections += "## 其他世界观文件（按需读取）\n"
        for rf in related_files:
            rf_name = Path(rf).name
            sections += f"- {rf_name}：路径：{rf}\n"

    mode_desc = ""
    if planner_name == "outline-planner":
        if planner_mode == "new":
            mode_desc = "新建了细纲"
        elif planner_mode == "revise":
            mode_desc = "修改了细纲"
        elif planner_mode == "sync":
            mode_desc = "同步了细纲"
        else:
            mode_desc = "更新了细纲"
    elif planner_name == "volume-planner":
        if planner_mode == "new":
            mode_desc = "新建了卷纲"
        elif planner_mode == "revise":
            mode_desc = "修改了卷纲"
        else:
            mode_desc = "更新了卷纲"

    task = f"""你的任务是根据{mode_desc}的内容，评估并更新指定的世界观文件。

当前阶段：outline（细纲规划阶段）
这意味着只是完成了规划，正文尚未写作。更新世界观文件时，事件/伏笔等只能标记为"细纲已规划"或"待正文回收"，不能标记为已完成/已回收。

更新对象类型：细纲对应的世界观文本
规划Agent：{planner_name}（{planner_mode}模式）
目标文件：{world_file_path}

{_INJECTION_NOTE}{sections}

【重要】你有权决定是否需要更新此文件：
1. 先读取规划文件和目标世界观文件
2. 判断规划中的变更是否与当前目标文件相关
3. 如果完全不相关或无需补充 → 无需任何操作，直接结束
4. 如果有需要更新的内容 → 根据规划中的变更更新目标文件
   - 只更新与规划变更相关的内容
   - 保留其他已有内容不变
   - 使用 str_replace 精确替换需要变更的部分（详见 world-updater 的输出策略）

注意：跳过不需要更新的文件是正常且鼓励的行为，不要强行修改无关文件。
"""

    try:
        logger.info(f"[PLAN_WORKFLOW]   Calling world-updater for {file_name} (model={model_name})")
        result = await call_subagent("world-updater", task, parent_model=model_name)
        logger.info(f"[PLAN_WORKFLOW]   world-updater completed for {file_name}")
        return {"file": world_file_path, "success": True}
    except Exception as e:
        logger.error(f"[PLAN_WORKFLOW]   world-updater failed for {file_name}: {e}")
        return {"file": world_file_path, "success": False, "errors": [f"Update {file_name} failed: {e}"]}


async def update_world_files_sequential(state: NovelWorkflowState) -> dict[str, Any]:
    world_files = state.get("world_files", [])
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")
    planner_name = state.get("planner_name", "")
    planner_mode = state.get("planner_mode", "")
    chapter_group = state.get("chapter_group", "")
    novel_name = state.get("novel_name", "")

    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_sequential START ======")
    logger.info(f"[PLAN_WORKFLOW] novel_name={novel_name}, total_files={len(world_files)}, mode=sequential")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in update_world_files_sequential")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    if not world_files:
        logger.info("[PLAN_WORKFLOW] No world files to update, skipping")
        logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_sequential END (no files) ======")
        return {"world_updated": True}

    errors = []
    success_count = 0
    for idx, wf in enumerate(world_files, 1):
        logger.info(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] Processing {Path(wf).name}")
        result = await _update_single_world_file(
            world_file_path=wf,
            novel_base=novel_base,
            planner_name=planner_name,
            planner_mode=planner_mode,
            chapter_group=chapter_group,
            model_name=model_name,
        )
        if result.get("success", False):
            success_count += 1
            logger.info(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] SUCCESS {Path(wf).name}")
        else:
            errors.extend(result.get("errors", []))
            logger.error(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] FAILED {Path(wf).name}")

    logger.info(f"[PLAN_WORKFLOW] Sequential update complete: success={success_count}/{len(world_files)}, errors={len(errors)}")
    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_sequential END ======")
    return {"world_updated": True, "errors": errors}


async def update_world_files_parallel(state: NovelWorkflowState) -> dict[str, Any]:
    world_files = state.get("world_files", [])
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")
    planner_name = state.get("planner_name", "")
    planner_mode = state.get("planner_mode", "")
    chapter_group = state.get("chapter_group", "")
    novel_name = state.get("novel_name", "")

    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_parallel START ======")
    logger.info(f"[PLAN_WORKFLOW] novel_name={novel_name}, total_files={len(world_files)}, mode=parallel")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in update_world_files_parallel")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    if not world_files:
        logger.info("[PLAN_WORKFLOW] No world files to update, skipping")
        logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_parallel END (no files) ======")
        return {"world_updated": True}

    logger.info(f"[PLAN_WORKFLOW] Launching {len(world_files)} parallel world-updater tasks")
    tasks = [
        _update_single_world_file(
            world_file_path=wf,
            novel_base=novel_base,
            planner_name=planner_name,
            planner_mode=planner_mode,
            chapter_group=chapter_group,
            model_name=model_name,
        )
        for wf in world_files
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = []
    success_count = 0
    for idx, r in enumerate(results, 1):
        if isinstance(r, Exception):
            errors.append(str(r))
            logger.error(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] EXCEPTION: {r}")
        elif isinstance(r, dict):
            if r.get("success", False):
                success_count += 1
                logger.info(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] SUCCESS {Path(r.get('file', '')).name}")
            else:
                errors.extend(r.get("errors", []))
                logger.error(f"[PLAN_WORKFLOW] [{idx}/{len(world_files)}] FAILED {Path(r.get('file', '')).name}")

    logger.info(f"[PLAN_WORKFLOW] Parallel update complete: success={success_count}/{len(world_files)}, errors={len(errors)}")
    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files_parallel END ======")
    return {"world_updated": True, "errors": errors}


async def update_world_files(state: NovelWorkflowState) -> dict[str, Any]:
    world_files = state.get("world_files", [])
    thread_id = state.get("thread_id")
    model_name = state.get("model_name")
    planner_name = state.get("planner_name", "")
    planner_mode = state.get("planner_mode", "")
    chapter_group = state.get("chapter_group", "")

    logger.info(f"[PLAN_WORKFLOW] ====== update_world_files START ======")
    logger.info(f"[PLAN_WORKFLOW] Total world files to update: {len(world_files)}")

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        logger.error("[PLAN_WORKFLOW] Failed to get novel_base in update_world_files")
        raise ValueError("无法获取小说根目录，请检查全局变量 novel_toc")

    if not world_files:
        logger.info("[PLAN_WORKFLOW] No world files to update, skipping")
        return {"world_updated": True, "errors": []}

    try:
        logger.info("[PLAN_WORKFLOW] Using batch mode (single world-updater call)")
        return await _update_all_world_files_batch(
            world_files=world_files,
            novel_base=novel_base,
            planner_name=planner_name,
            planner_mode=planner_mode,
            chapter_group=chapter_group,
            model_name=model_name,
        )
    except Exception as e:
        logger.warning(f"[PLAN_WORKFLOW] Batch mode failed, falling back to sequential: {e}")
        return await update_world_files_sequential(state)


def _route_after_planner(state: NovelWorkflowState) -> str:
    route = _should_update_world(state)
    logger.info(f"[PLAN_WORKFLOW] Routing after planner: {route}")
    return route


def create_plan_workflow() -> StateGraph:
    logger.info("[PLAN_WORKFLOW] Creating plan workflow")

    workflow = StateGraph(NovelWorkflowState)

    workflow.add_node("call_planner", call_planner)
    workflow.add_node("scan_world_files", scan_world_files)
    workflow.add_node("update_world_files", update_world_files)

    workflow.set_entry_point("call_planner")

    workflow.add_conditional_edges(
        "call_planner",
        _route_after_planner,
        {
            "scan_world_files": "scan_world_files",
            "end_no_update": END,
            "end_with_error": END,
        },
    )

    workflow.add_edge("scan_world_files", "update_world_files")
    workflow.add_edge("update_world_files", END)

    logger.info("[PLAN_WORKFLOW] Plan workflow created successfully")
    return workflow.compile()


logger.info("[PLAN_WORKFLOW] Registering plan workflow")
register_workflow("plan", create_plan_workflow)
logger.info("[PLAN_WORKFLOW] Plan workflow registered")