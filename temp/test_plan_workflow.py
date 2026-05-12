"""Test script for plan workflow registration."""

import asyncio
import sys
sys.path.insert(0, r'c:\xiangmu\deer-flow\backend\packages\harness')

from deerflow.workflows.registry import list_workflows, get_workflow
from deerflow.subagents.registry import get_subagent_config, get_subagent_names

print("=" * 60)
print("Testing Plan Workflow Registration")
print("=" * 60)

# 1. Check workflows
workflows = list_workflows()
print(f"\n1. Registered workflows: {workflows}")
assert "plan" in workflows, "plan workflow not registered!"
print("   ✓ plan workflow is registered")

# 2. Check workflow factory
plan_factory = get_workflow("plan")
print(f"\n2. Plan workflow factory: {plan_factory}")
assert plan_factory is not None, "plan workflow factory is None!"
print("   ✓ plan workflow factory exists")

# 3. Check world-updater agent
subagent_names = get_subagent_names()
print(f"\n3. Available subagents: {subagent_names}")
assert "world-updater" in subagent_names, "world-updater not found!"
print("   ✓ world-updater is registered")

# 4. Check world-updater config
config = get_subagent_config("world-updater")
print(f"\n4. World-updater config:")
print(f"   name: {config.name}")
print(f"   model: {config.model}")
print(f"   tool_groups: {config.tool_groups}")
print(f"   max_turns: {config.max_turns}")
print(f"   timeout_seconds: {config.timeout_seconds}")
assert config.model == "inherit", "model should be inherit"
assert "file:read" in config.tool_groups, "file:read should be in tool_groups"
assert "file:write" in config.tool_groups, "file:write should be in tool_groups"
print("   ✓ world-updater config is correct")

# 5. Check NovelWorkflowState has new fields
from deerflow.workflows.states import NovelWorkflowState
state_fields = list(NovelWorkflowState.__annotations__.keys())
print(f"\n5. NovelWorkflowState fields: {state_fields}")
assert "planner_name" in state_fields, "planner_name field missing"
assert "planner_mode" in state_fields, "planner_mode field missing"
assert "planner_task" in state_fields, "planner_task field missing"
assert "world_files" in state_fields, "world_files field missing"
assert "world_updated" in state_fields, "world_updated field missing"
print("   ✓ All new state fields exist")

# 6. Check executor REQUIRED_PARAMS
from deerflow.workflows.executor import REQUIRED_PARAMS
print(f"\n6. REQUIRED_PARAMS: {REQUIRED_PARAMS}")
assert "plan" in REQUIRED_PARAMS, "plan not in REQUIRED_PARAMS"
assert "planner_name" in REQUIRED_PARAMS["plan"], "planner_name not required"
print("   ✓ plan workflow has required params")

print("\n" + "=" * 60)
print("All tests passed!")
print("=" * 60)
