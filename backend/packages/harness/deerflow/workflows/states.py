"""Workflow state definitions."""

import operator
from typing import Annotated, TypedDict


def _keep_latest(old: str | None, new: str | None) -> str | None:
    return new if new is not None else old


class NovelWorkflowState(TypedDict, total=False):
    thread_id: str
    model_name: str
    novel_name: str
    chapter_num: int
    chapter_nums: list[int]
    chapter_group: str
    world_reference: str
    character_reference: str
    item_reference: str
    storyline_reference: str
    writing_task_summary: str
    chapter_content: str
    audit_report: str
    audit_passed: bool
    audit_round: int
    chapter_summary: str
    state_updated: bool
    hooks_updated: bool
    card_updated: bool
    outline_synced: bool
    errors: Annotated[list[str], operator.add]
