"""Workflow tool for executing predefined workflows."""

import logging
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langgraph.config import get_stream_writer
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


def _auto_detect_novel_name(thread_id: str | None = None) -> str | None:
    from deerflow.workflows.helpers import get_novel_base

    novel_base = get_novel_base(thread_id=thread_id)
    if novel_base:
        return Path(novel_base).name
    from deerflow.workflows.helpers import get_workdir

    book_dir = Path(f"{get_workdir(thread_id=thread_id)}/book")
    if not book_dir.exists():
        return None
    novels = [d.name for d in book_dir.iterdir() if d.is_dir()]
    if len(novels) == 1:
        return novels[0]
    return None


def _auto_detect_chapter_group(novel_name: str, thread_id: str | None = None) -> str | None:
    from deerflow.workflows.helpers import get_novel_base

    novel_base = get_novel_base(thread_id=thread_id)
    if not novel_base:
        from deerflow.workflows.helpers import get_workdir

        novel_base = f"{get_workdir(thread_id=thread_id)}/book/{novel_name}"
    novel_dir = Path(f"{novel_base}/02-正文")
    if not novel_dir.exists():
        return None
    groups = [d.name for d in novel_dir.iterdir() if d.is_dir() and d.name.startswith("第")]
    if len(groups) == 1:
        return groups[0]
    return None


def _auto_detect_params(workflow_name: str, params: dict[str, Any], thread_id: str | None = None) -> dict[str, Any]:
    if workflow_name not in ("organize", "writing", "plan"):
        return params

    params = params.copy()

    if not params.get("novel_name"):
        detected = _auto_detect_novel_name(thread_id=thread_id)
        if detected:
            params["novel_name"] = detected

    if not params.get("chapter_group") and params.get("novel_name"):
        detected = _auto_detect_chapter_group(params["novel_name"], thread_id=thread_id)
        if detected:
            params["chapter_group"] = detected

    return params


@tool("workflow", parse_docstring=True)
async def workflow_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    workflow_name: str,
    params: dict[str, Any],
    description: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> str:
    """Execute a predefined workflow for deterministic task orchestration.

    Available workflows:
    - organize: Organize reference materials (world, characters, items)
    - writing: Write chapter with audit loop (write → audit → revise)
    - plan: Planning tasks with outline audit loop (call planner → audit outline → revise if needed → update summary)

    Required params for organize/writing:
    - novel_name: Novel name (optional, auto-detected if only one exists)
    - chapter_num: Chapter number (required, e.g., 5)
    - chapter_group: Chapter group range (optional, auto-detected if only one exists, e.g., "第5-10章")

    Required params for plan:
    - planner_name: Planner agent name (required, one of: outline-planner, volume-planner, book-rules-manager)
    - planner_mode: Planner mode (optional, one of: new, revise, sync)
    - planner_task: Task description for the planner (optional)
    - chapter_group: Chapter group range (optional, for outline-planner, e.g., "第5-10章")

    Args:
        workflow_name: Name of the workflow to execute.
        params: Parameters for the workflow.
        description: Optional description for logging.
    """
    from deerflow.workflows import list_workflows
    from deerflow.workflows.executor import execute_workflow

    available = list_workflows()
    if workflow_name not in available:
        return f"Error: Unknown workflow '{workflow_name}'. Available: {', '.join(available)}"

    thread_id = runtime.context.get("thread_id") if runtime.context else None
    params = _auto_detect_params(workflow_name, params, thread_id=thread_id)
    params["thread_id"] = thread_id

    # Get the model name from runtime metadata (same as task_tool)
    metadata = runtime.config.get("metadata", {}) if runtime.config else {}
    parent_model = metadata.get("model_name")
    
    logger.info(f"[WORKFLOW_TOOL] Called workflow={workflow_name} model_name={parent_model}")
    
    if parent_model:
        params["model_name"] = parent_model

    writer = get_stream_writer()
    writer({"type": "workflow_started", "workflow_name": workflow_name, "description": description})

    try:
        result = await execute_workflow(workflow_name, params)

        if result.status == "completed":
            writer({"type": "workflow_completed", "workflow_name": workflow_name, "result": result.result})
            return f"Workflow '{workflow_name}' completed. Result: {result.result}"
        else:
            writer({"type": "workflow_failed", "workflow_name": workflow_name, "error": result.error})
            return f"Workflow '{workflow_name}' failed: {result.error}"

    except Exception as e:
        logger.exception(f"Workflow {workflow_name} execution failed")
        writer({"type": "workflow_failed", "workflow_name": workflow_name, "error": str(e)})
        error_msg = str(e)
        if workflow_name in ("organize", "writing"):
            detected_info = []
            if params.get("novel_name"):
                detected_info.append(f"novel_name: {params['novel_name']} (auto-detected)")
            if params.get("chapter_group"):
                detected_info.append(f"chapter_group: {params['chapter_group']} (auto-detected)")
            if detected_info:
                error_msg += "\n\n当前自动检测到的信息：\n" + "\n".join(f"- {info}" for info in detected_info)
                error_msg += "\n\n请重新调用 workflow 工具，提供缺失的参数。"
        return f"Workflow '{workflow_name}' failed: {error_msg}"
