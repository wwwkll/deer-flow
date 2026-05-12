# -*- coding: utf-8 -*-
"""
验证 subagent tool_groups 修复效果。

模拟 workflows/helpers.py:call_subagent 加载工具的过程，
确认每个 subagent 实际拿到的工具数和工具名。

期望结果：
- chapter-summarizer / state-settler / hook-manager / outline-planner
  / novel-architect / novel-character-organizer / novel-item-organizer
  / novel-storyline-organizer / novel-world-organizer / volume-planner
  这些 tool_groups=[file:read, file:write] 的 subagent 应拿到 6 个工具：
    [ls, read_file, glob, grep, write_file, str_replace]
- continuity-auditor / novel-reviser / book-rules-manager / style-analyzer
  也是 tool_groups=[file:read, file:write]，预期同上 6 个工具。
- novel-writer 走 _build_subagent_from_agents_dir 路径但其 yaml 是嵌套结构，
  顶层无 tools 字段 → tools=None → 拿到全部工具（侥幸生效，不在本次修复范围）。
"""

import os
import sys

BACKEND_DIR = r"C:\xiangmu\deer-flow\backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "packages", "harness"))
sys.path.insert(0, BACKEND_DIR)

# IMPORTANT: import lead_agent first to trigger correct module load order,
# avoiding the circular import in deerflow.subagents/tools/agents.
import deerflow.agents.lead_agent.agent  # noqa: F401, E402

from deerflow.subagents.registry import get_subagent_config  # noqa: E402
from deerflow.tools import get_available_tools  # noqa: E402

print("=" * 80)
print("Subagent tool_groups 修复后验证")
print("=" * 80)

NAMES = [
    "chapter-summarizer",
    "state-settler",
    "hook-manager",
    "outline-planner",
    "novel-architect",
    "novel-character-organizer",
    "novel-item-organizer",
    "novel-storyline-organizer",
    "novel-world-organizer",
    "volume-planner",
    "continuity-auditor",
    "novel-reviser",
    "book-rules-manager",
    "style-analyzer",
    "novel-writer",
]

PARENT_MODEL = "qwen-3-6-online"  # 任意一个能解析的模型即可

for name in NAMES:
    print(f"\n--- {name} ---")
    try:
        cfg = get_subagent_config(name)
    except Exception as e:
        print(f"  [ERROR] get_subagent_config failed: {e}")
        continue
    if cfg is None:
        print("  [ERROR] config is None")
        continue
    print(f"  cfg.tools       = {cfg.tools}")
    print(f"  cfg.tool_groups = {cfg.tool_groups}")
    print(f"  cfg.disallowed  = {cfg.disallowed_tools}")
    try:
        tools = get_available_tools(
            model_name=PARENT_MODEL,
            groups=cfg.tool_groups,
            subagent_enabled=False,
        )
    except Exception as e:
        print(f"  [ERROR] get_available_tools failed: {e}")
        continue
    # 模拟 SubagentExecutor._filter_tools 的 allowed/disallowed 逻辑
    if cfg.tools is not None:
        allowed = set(cfg.tools)
        tools = [t for t in tools if t.name in allowed]
    if cfg.disallowed_tools is not None:
        disallowed = set(cfg.disallowed_tools)
        tools = [t for t in tools if t.name not in disallowed]
    names = [t.name for t in tools]
    print(f"  -> {len(names)} tool(s): {names}")
