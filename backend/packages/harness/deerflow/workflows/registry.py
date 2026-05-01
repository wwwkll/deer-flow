"""Workflow registry for managing available workflows."""

import logging
from collections.abc import Callable

from langgraph.graph import StateGraph

logger = logging.getLogger(__name__)

_workflow_registry: dict[str, Callable[..., StateGraph]] = {}


def register_workflow(name: str, factory: Callable[..., StateGraph]) -> None:
    _workflow_registry[name] = factory
    logger.info(f"Registered workflow: {name}")


def get_workflow(name: str) -> Callable[..., StateGraph] | None:
    return _workflow_registry.get(name)


def list_workflows() -> list[str]:
    return list(_workflow_registry.keys())
