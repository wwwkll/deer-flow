"""Test that plan workflow compiles correctly."""

import sys
sys.path.insert(0, r'c:\xiangmu\deer-flow\backend\packages\harness')
sys.path.insert(0, r'c:\xiangmu\deer-flow')

# Test 1: Import and compile workflow
print("=" * 60)
print("Test 1: Compile plan workflow")
print("=" * 60)

from deerflow.workflows.novel_plan import create_plan_workflow
workflow = create_plan_workflow()
print("OK Workflow compiled successfully:", type(workflow))
print("  Nodes:", list(workflow.nodes.keys()))

# Test 2: Check state fields
print("\n" + "=" * 60)
print("Test 2: Check NovelWorkflowState fields")
print("=" * 60)

from deerflow.workflows.states import NovelWorkflowState
fields = list(NovelWorkflowState.__annotations__.keys())
required_new_fields = ["planner_name", "planner_mode", "planner_task", "world_files", "world_updated"]
for f in required_new_fields:
    assert f in fields, "Missing field: " + f
    print("OK Field '" + f + "' exists")

# Test 3: Check registry
print("\n" + "=" * 60)
print("Test 3: Check workflow registry")
print("=" * 60)

from deerflow.workflows.registry import list_workflows, get_workflow
workflows = list_workflows()
print("Registered workflows:", workflows)
assert "plan" in workflows, "plan workflow not registered!"
print("OK plan workflow is registered")

plan_factory = get_workflow("plan")
assert plan_factory is not None, "plan factory is None!"
print("OK plan workflow factory exists")

# Test 4: Check executor REQUIRED_PARAMS
print("\n" + "=" * 60)
print("Test 4: Check executor REQUIRED_PARAMS")
print("=" * 60)

from deerflow.workflows.executor import REQUIRED_PARAMS
assert "plan" in REQUIRED_PARAMS, "plan not in REQUIRED_PARAMS"
assert "planner_name" in REQUIRED_PARAMS["plan"], "planner_name not required"
print("REQUIRED_PARAMS['plan']:", REQUIRED_PARAMS["plan"])
print("OK plan workflow has correct required params")

# Test 5: Check world-updater agent files exist
print("\n" + "=" * 60)
print("Test 5: Check world-updater agent files")
print("=" * 60)

from pathlib import Path
agent_dir = Path(r'c:\xiangmu\deer-flow\backend\.deer-flow\agents\world-updater')
assert agent_dir.exists(), "world-updater directory not found!"
assert (agent_dir / "SOUL.md").exists(), "SOUL.md not found!"
assert (agent_dir / "config.yaml").exists(), "config.yaml not found!"
print("OK world-updater directory exists")
print("OK SOUL.md exists")
print("OK config.yaml exists")

import yaml
with open(agent_dir / "config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)
assert config["model"] == "inherit", "model should be inherit"
assert "file:read" in config["tool_groups"], "file:read missing"
assert "file:write" in config["tool_groups"], "file:write missing"
print("OK config.yaml is valid: model=" + config["model"] + ", tool_groups=" + str(config["tool_groups"]))

print("\n" + "=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)
