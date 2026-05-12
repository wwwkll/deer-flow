"""Diagnostic: test tool calling with the agent's actual system prompt."""

import json
import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages")

from deerflow.models.factory import create_chat_model
from deerflow.agents.lead_agent.prompt import apply_prompt_template
from langchain.tools import tool


@tool
def test_tool(query: str) -> str:
    """A simple test tool. Call this tool when you need to look something up.

    Args:
        query: The query string to look up.
    """
    return f"Result for: {query}"


# Build the same system prompt the agent uses
system_prompt = apply_prompt_template(
    subagent_enabled=True,
    max_concurrent_subagents=3,
    agent_name="novel-master",
)

print("=" * 60)
print("Testing with agent system prompt (first 300 chars):")
print(system_prompt[:300])
print("...")
print(f"Total prompt length: {len(system_prompt)} chars")
print("=" * 60)

model = create_chat_model(name="qwen-3-6-local", thinking_enabled=False)
model_with_tools = model.bind_tools([test_tool])

result = model_with_tools.invoke([
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Search for information about chapter groups in the novel."},
])

print(f"\nResult type: {type(result).__name__}")
print(f"Has tool_calls: {hasattr(result, 'tool_calls') and bool(result.tool_calls)}")

if hasattr(result, "tool_calls") and result.tool_calls:
    for tc in result.tool_calls:
        print(f"\nTool call: {tc['name']}")
        print(f"Args: {json.dumps(tc['args'], ensure_ascii=False)}")
else:
    print(f"\n*** NO TOOL CALLS ***")
    print(f"Content preview: {result.content[:500] if result.content else '(empty)'}")

print("=" * 60)