"""Diagnostic: test if the LLM can properly output tool_calls."""

import json
import logging
import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages")

from deerflow.models.factory import create_chat_model
from langchain.tools import tool


@tool
def test_tool(query: str) -> str:
    """A simple test tool. Call this tool when you need to look something up.

    Args:
        query: The query string to look up.
    """
    return f"Result for: {query}"


model = create_chat_model(name="qwen-3-6-local", thinking_enabled=False)

model_with_tools = model.bind_tools([test_tool])

result = model_with_tools.invoke([
    {"role": "system", "content": "You are a helpful assistant. Use tools when needed."},
    {"role": "user", "content": "Search for information about chapter groups."},
])

print("=" * 60)
print(f"Result type: {type(result).__name__}")
print(f"Has tool_calls: {hasattr(result, 'tool_calls') and bool(result.tool_calls)}")
print(f"Content: {result.content[:200] if result.content else '(empty)'}")

if hasattr(result, "tool_calls") and result.tool_calls:
    for tc in result.tool_calls:
        print(f"\nTool call: {tc['name']}")
        print(f"Args: {json.dumps(tc['args'], ensure_ascii=False)}")
else:
    print("\n*** NO TOOL CALLS - model returned text instead ***")
    print("Full response:")
    print(result.content)

print("=" * 60)