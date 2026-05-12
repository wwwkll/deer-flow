# -*- coding: utf-8 -*-
"""
直接调用 make_lead_agent 模拟前端的请求场景，捕获 logger 输出，
查看 subagent_enabled 在真实调用链中是否被覆盖为 True。
"""
import sys
import os
import logging
import io

BACKEND_DIR = r"C:\xiangmu\deer-flow\backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "packages", "harness"))
sys.path.insert(0, BACKEND_DIR)

# 捕获日志
log_buffer = io.StringIO()
log_handler = logging.StreamHandler(log_buffer)
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(logging.Formatter("[%(name)s][%(levelname)s] %(message)s"))
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(log_handler)

# 也输出到控制台
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("[%(name)s][%(levelname)s] %(message)s"))
root_logger.addHandler(console_handler)

print("=" * 60)
print("Test 1: configurable 中带 agent_name=novel-master")
print("=" * 60)

config1 = {
    "configurable": {
        "thread_id": "test-thread-1",
        "agent_name": "novel-master",
    }
}

try:
    from deerflow.agents.lead_agent.agent import make_lead_agent
    agent1 = make_lead_agent(config1)
    print("\n[Test1] OK, agent created")
except Exception as e:
    print(f"\n[Test1] FAILED: {type(e).__name__}: {e}")

print()
print("=" * 60)
print("Test 2: context 中带 agent_name=novel-master (LangGraph >= 0.6 风格)")
print("=" * 60)

config2 = {
    "configurable": {"thread_id": "test-thread-2"},
    "context": {
        "agent_name": "novel-master",
        "subagent_enabled": False,  # 模拟前端默认值
    }
}

try:
    agent2 = make_lead_agent(config2)
    print("\n[Test2] OK, agent created")
except Exception as e:
    print(f"\n[Test2] FAILED: {type(e).__name__}: {e}")

print()
print("=" * 60)
print("Test 3: 没有 agent_name (默认 lead_agent)")
print("=" * 60)

config3 = {
    "configurable": {"thread_id": "test-thread-3"}
}

try:
    agent3 = make_lead_agent(config3)
    print("\n[Test3] OK, agent created")
except Exception as e:
    print(f"\n[Test3] FAILED: {type(e).__name__}: {e}")

print()
print("=" * 60)
print("CAPTURED LOGS:")
print("=" * 60)
print(log_buffer.getvalue())
