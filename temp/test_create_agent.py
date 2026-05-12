"""Diagnostic: test tool calling through the actual create_agent flow."""

import json
import sys

sys.path.insert(0, r"c:\xiangmu\deer-flow\backend\packages")

from langchain.agents import create_agent
from langchain.tools import tool
from deerflow.models.factory import create_chat_model
from deerflow.agents.lead_agent.prompt import apply_prompt_template


@tool
def test_tool(query: str) -> str:
    """A simple test tool. Call this tool when you need to look something up.

    Args:
        query: The query string to look up.
    """
    return f"Result for: {query}"


model = create_chat_model(name="qwen-3-6-local", thinking_enabled=False)

# Test 1: create_agent WITHOUT middleware
print("=" * 60)
print("Test 1: create_agent with NO middleware")
print("=" * 60)

agent = create_agent(
    model=model,
    tools=[test_tool],
    system_prompt=apply_prompt_template(
        subagent_enabled=True,
        max_concurrent_subagents=3,
        agent_name="novel-master",
    ),
)

result = agent.invoke({
    "messages": [
        {"role": "user", "content": "Search for information about chapter groups in the novel."},
    ]
})

msgs = result["messages"]
last_msg = msgs[-1]
has_tc = hasattr(last_msg, "tool_calls") and bool(last_msg.tool_calls)
print(f"Messages count: {len(msgs)}")
print(f"Last msg type: {type(last_msg).__name__}")
print(f"Has tool_calls: {has_tc}")
if has_tc:
    for tc in last_msg.tool_calls:
        print(f"  -> {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})")
else:
    print(f"  Content: {last_msg.content[:300] if last_msg.content else '(empty)'}")

# Show all messages
print("\nAll messages:")
for i, m in enumerate(msgs):
    role = getattr(m, "type", type(m).__name__)
    has_tc = hasattr(m, "tool_calls") and bool(m.tool_calls)
    content_preview = (m.content[:100] if m.content else "") if hasattr(m, "content") else ""
    if has_tc:
        tc_names = [tc["name"] for tc in m.tool_calls]
        print(f"  [{i}] {role} - tool_calls={tc_names}")
    else:
        print(f"  [{i}] {role} - {content_preview[:80] if content_preview else '(empty)'}")

print("=" * 60)
print("DONE")