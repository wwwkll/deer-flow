# -*- coding: utf-8 -*-
"""
诊断 novel-master 的 subagent_enabled 是否在配置加载时为 True。

目的：直接调用 load_agent_config("novel-master") 并打印关键字段，
     以验证「配置文件解析正确」这一前提，再继续往下排查。
"""
import sys
import os

# 切到 backend 工作目录，确保 .deer-flow 目录解析正确
BACKEND_DIR = r"C:\xiangmu\deer-flow\backend"
os.chdir(BACKEND_DIR)
sys.path.insert(0, os.path.join(BACKEND_DIR, "packages", "harness"))
sys.path.insert(0, BACKEND_DIR)

from deerflow.config.agents_config import load_agent_config
from deerflow.config.paths import get_paths

paths = get_paths()
print(f"[paths] base_dir       = {paths.base_dir}")
print(f"[paths] agents_dir     = {paths.agents_dir}")
print(f"[paths] agent_dir(nm)  = {paths.agent_dir('novel-master')}")
print(f"[paths] config exists  = {(paths.agent_dir('novel-master') / 'config.yaml').exists()}")
print()

cfg = load_agent_config("novel-master")
print(f"[cfg] type             = {type(cfg).__name__}")
print(f"[cfg] name             = {cfg.name!r}")
print(f"[cfg] model            = {cfg.model!r}")
print(f"[cfg] tool_groups      = {cfg.tool_groups!r}")
print(f"[cfg] skills           = {cfg.skills!r}")
print(f"[cfg] subagent_enabled = {cfg.subagent_enabled!r}")
print(f"[cfg] max_concurrent   = {cfg.max_concurrent_subagents!r}")
print()

# 模拟 lead_agent.make_lead_agent 中的覆盖逻辑
runtime_subagent_enabled = False  # 模拟前端默认值
runtime_max = 3

print("=== Simulating override logic from agent.py:386-389 ===")
print(f"before: runtime_subagent_enabled = {runtime_subagent_enabled}")
if cfg:
    if cfg.subagent_enabled:
        runtime_subagent_enabled = True
        runtime_max = cfg.max_concurrent_subagents
print(f"after:  runtime_subagent_enabled = {runtime_subagent_enabled}")
print(f"after:  max_concurrent           = {runtime_max}")
