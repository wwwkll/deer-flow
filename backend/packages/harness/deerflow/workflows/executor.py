"""Workflow executor for running LangGraph workflows."""

import logging
import uuid
from datetime import datetime
from typing import Any

from deerflow.workflows.registry import get_workflow

logger = logging.getLogger(__name__)


class WorkflowStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowResult:
    def __init__(self, workflow_name: str, task_id: str | None = None):
        self.task_id = task_id or str(uuid.uuid4())[:8]
        self.workflow_name = workflow_name
        self.status = WorkflowStatus.PENDING
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


REQUIRED_PARAMS = {
    "organize": ["novel_name", "chapter_num", "chapter_group"],
    "writing": ["novel_name", "chapter_num", "chapter_group"],
}


class WorkflowExecutor:
    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        self.workflow_factory = get_workflow(workflow_name)
        if self.workflow_factory is None:
            raise ValueError(f"Unknown workflow: {workflow_name}")

    async def execute(self, params: dict[str, Any]) -> WorkflowResult:
        result = WorkflowResult(self.workflow_name)
        result.status = WorkflowStatus.RUNNING
        result.started_at = datetime.now()

        logger.info(f"[WORKFLOW_EXECUTOR] Executing workflow={self.workflow_name} params_keys={list(params.keys())} model_name={params.get('model_name')}")

        try:
            workflow = self.workflow_factory()
            self._validate_params(params)
            initial_state = self._build_initial_state(params)

            logger.info(f"[WORKFLOW_EXECUTOR] Initial state keys={list(initial_state.keys())} model_name={initial_state.get('model_name')}")

            final_state = None
            config = {"recursion_limit": 100}
            async for chunk in workflow.astream(initial_state, stream_mode="values", config=config):
                final_state = chunk

            if final_state is None:
                result.result = {}
            else:
                result.result = dict(final_state)

            result.status = WorkflowStatus.COMPLETED
            result.completed_at = datetime.now()

        except Exception as e:
            logger.exception(f"Workflow {self.workflow_name} execution failed")
            result.status = WorkflowStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now()

        return result

    def _validate_params(self, params: dict[str, Any]) -> None:
        required = REQUIRED_PARAMS.get(self.workflow_name, [])
        missing = [k for k in required if not params.get(k)]
        if missing:
            raise ValueError(f"缺少必需参数: {', '.join(missing)}")

    def _build_initial_state(self, params: dict[str, Any]) -> dict[str, Any]:
        from deerflow.workflows.states import NovelWorkflowState

        state: dict[str, Any] = {}
        for key in NovelWorkflowState.__annotations__:
            if key in params:
                state[key] = params[key]
        return state


_background_workflows: dict[str, WorkflowResult] = {}


async def execute_workflow(workflow_name: str, params: dict[str, Any]) -> WorkflowResult:
    executor = WorkflowExecutor(workflow_name)
    result = await executor.execute(params)
    _background_workflows[result.task_id] = result
    return result


def get_workflow_result(task_id: str) -> WorkflowResult | None:
    return _background_workflows.get(task_id)


def cleanup_workflow_result(task_id: str) -> None:
    _background_workflows.pop(task_id, None)
