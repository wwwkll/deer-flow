# Novel-Master Agent 工作流调用修复总结

**生成日期**：2026-05-09  
**当前状态**：代码修改完成，待验证

---

## 📌 核心需求

用户最终目标：**让 novel-master 主控 agent 调用工作流（workflow）来执行章节整理（organize）和写作（writing）任务**。

用户的疑惑：不确定 novel-master 是否真的在调用工作流。

---

## ✅ 已完成的修复

### 1. Tool Groups 配置系统实装（5 个文件）

**问题**：chapter-summarizer、state-settler 等 subagent 拿不到任何工具，无法工作。根因是 SubagentConfig 没有 tool_groups 字段，注册器忽视了此字段。

**修复文件及改动**：

#### a) `backend/packages/harness/deerflow/config/subagents_config.py`
```python
# 添加到 CustomSubagentConfig dataclass 中
tool_groups: list[str] | None = None  # e.g. ["file:read", "file:write"]
```

#### b) `backend/packages/harness/deerflow/subagents/config.py`
```python
# 添加到 SubagentConfig dataclass 中（第 ~15 行）
tool_groups: list[str] | None = None
# 并在 docstring 中补充说明：
# """
# tool_groups: Available tool groups for this subagent.
#   Priority: subagent's own tool_groups > parent agent's tool_groups (if inherited).
#   Example: ["file:read", "file:write"]
# """
```

#### c) `backend/packages/harness/deerflow/subagents/registry.py`
```python
# 修改 1：在 _SUBAGENT_CONFIG_FIELDS 集合中加入 "tool_groups"（第 ~25 行）
_SUBAGENT_CONFIG_FIELDS = {
    "system_prompt",
    "tools",
    "tool_groups",  # ← 添加这行
    "disallowed_tools",
    "skills",
    ...
}

# 修改 2：在 _build_custom_subagent_config() 中透传 tool_groups（第 ~110 行）
return SubagentConfig(
    ...
    tool_groups=custom.tool_groups,  # ← 添加这行
    ...
)
```

#### d) `backend/packages/harness/deerflow/workflows/helpers.py`
```python
# 修改 call_subagent() 函数（第 ~50 行）
config = get_subagent_config(subagent_name)
...
# 改变工具加载逻辑，使用 config.tool_groups
tools = get_available_tools(
    model_name=parent_model,
    groups=config.tool_groups,  # ← 改这里，原来是 parent_tool_groups
    subagent_enabled=False,
)
# 添加诊断日志
logger.info(f"[CALL_SUBAGENT_DEBUG] subagent={subagent_name} tool_groups={config.tool_groups} -> {len(tools)} tool(s)")
```

#### e) `backend/packages/harness/deerflow/tools/builtins/task_tool.py`
```python
# 修改 task_tool() 函数中工具加载逻辑（第 ~140 行）
# 让 subagent 自身的 tool_groups 优先于父 agent 继承的
parent_tool_groups = metadata.get("tool_groups")
effective_tool_groups = config.tool_groups if config.tool_groups is not None else parent_tool_groups

tools = get_available_tools(
    model_name=parent_model,
    groups=effective_tool_groups,  # ← 使用 effective_tool_groups
    subagent_enabled=False
)
# 添加诊断日志
logger.info(
    f"[trace={trace_id}] task_tool resolving subagent={subagent_type}: "
    f"own_tool_groups={config.tool_groups}, parent_tool_groups={parent_tool_groups}, "
    f"effective={effective_tool_groups} -> {len(tools)} tool(s)"
)
```

**验证**：运行 `python backend/packages/harness/deerflow/tools/builtins/verify_subagent_tool_groups.py`
- 期望：chapter-summarizer 等从 0 工具恢复为 6~12 工具

---

### 2. Windows 进程管理补丁（serve.sh）

**问题**：`make stop` 失效，pkill/lsof 在 Windows Git Bash 中看不到原生 .exe 进程。

**修复文件**：`backend/scripts/serve.sh`

**关键改动**：

```bash
# 1. 添加 Windows 检测函数
_is_windows() {
    [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]
}

# 2. 添加 Windows 特定的进程杀除函数
_windows_kill_by_cmdline() {
    local pattern="$1"
    powershell.exe -NoProfile -NonInteractive -Command \
        "Get-CimInstance Win32_Process -Filter 'CommandLine LIKE ''%${pattern}%''' -ErrorAction SilentlyContinue | \
         Where-Object { \$_.Name -in 'uv.exe','python.exe','node.exe','langgraph.exe','uvicorn.exe' } | \
         Stop-Process -Force -ErrorAction SilentlyContinue"
}

_windows_taskkill_services() {
    taskkill.exe /F /IM uv.exe 2>/dev/null
    taskkill.exe /F /IM python.exe 2>/dev/null
    taskkill.exe /F /IM node.exe 2>/dev/null
}

# 3. 修改 _kill_port() 函数使用 Windows netstat
_kill_port() {
    local port="$1"
    if _is_windows; then
        # Windows: netstat + taskkill
        local pids=$(netstat -ano 2>/dev/null | grep "LISTENING" | grep ":${port}" | awk '{print $5}' | sort -u)
        for pid in $pids; do
            [[ -n "$pid" ]] && taskkill.exe /F /PID "$pid" 2>/dev/null
        done
    else
        # Unix: lsof
        local pids=$(lsof -ti :$port 2>/dev/null)
        for pid in $pids; do
            [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null
        done
    fi
}

# 4. 修改 stop_all() 函数使用 Windows 进程杀除
stop_all() {
    if _is_windows; then
        _windows_kill_by_cmdline "langgraph dev"
        _windows_kill_by_cmdline "uvicorn"
        _windows_kill_by_cmdline "next dev"
        _windows_taskkill_services
    else
        pkill -f "langgraph dev" 2>/dev/null || true
        pkill -f "uvicorn" 2>/dev/null || true
        pkill -f "next dev" 2>/dev/null || true
    fi
}
```

**关键细节**：
- PowerShell 引号：`-Filter 'CommandLine LIKE ''%pattern%'''`（单引号嵌套）
- 变量转义：`\$_` 而非 `$_`
- 进程过滤：只杀 uv.exe、python.exe、node.exe、langgraph.exe、uvicorn.exe，避免误伤 shell wrapper

---

### 3. 后端诊断日志（agent.py）

**文件**：`backend/packages/harness/deerflow/agents/lead_agent/agent.py`

**添加位置与内容**：

```python
# 位置 1：make_lead_agent() 入口（第 ~350 行）
logger.info(f"[DIAG-NOVEL-MASTER] IN | agent_name={agent_name} | context keys={context.keys() if context else 'NoneType'}")

# 位置 2：agent_name 覆盖后（第 ~450 行）
logger.info(f"[DIAG-NOVEL-MASTER] OUT | resolved agent_name='{agent_name}' | agent_config_loaded={agent_config is not None} | agent_config.subagent_enabled={agent_config.subagent_enabled if agent_config else 'N/A'}")

# 位置 3：工具加载后（第 ~480 行）
logger.info(f"[DIAG-NOVEL-MASTER] TOOLS | after_override | subagent_enabled={agent_config.subagent_enabled if agent_config else False} | tool_groups={agent_config.tool_groups if agent_config else None} | -> {len(tools)} tool(s)")
```

---

## ❌ 剩余问题

### 关键问题：agent_name 未被前端正确注入

**症状**：用户从通用聊天页面入口时，后端日志显示 `agent_name=None`，导致 novel-master 配置从未被加载。

**根本原因**：前端有两个入口，只有其中一个注入 agent_name：

| 入口 | 路径 | agent_name 注入 | 说明 |
|------|------|----------|------|
| ✅ Agent 专属 | `/workspace/agents/novel-master/chats/<id>` | 是 | frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx L55 |
| ❌ 通用聊天 | `/workspace/chats/<id>` | 否 | frontend/src/app/workspace/chats/[thread_id]/page.tsx L53 |

**当前状态**：
- 所有代码修复（tool_groups、Windows 补丁）已实装
- 但因 agent_name 注入问题，novel-master 的配置从未被触发验证
- 用户无法确认工作流是否真的被调用

---

## 🔍 待验证事项

### 第一步：验证 tool_groups 真的生效

**前置条件**：必须从正确的 agent 专属页面入口

**操作步骤**：
1. 打开 `http://localhost:3000/workspace/agents/novel-master/chats/<你的thread_id>`
2. 发起写章节请求（例如"写第一章"）
3. 查看后端日志，确认看到：
   ```
   [DIAG-NOVEL-MASTER] IN | agent_name=novel-master
   [DIAG-NOVEL-MASTER] OUT | resolved agent_name='novel-master' | agent_config_loaded=True | agent_config.subagent_enabled=True
   [DIAG-NOVEL-MASTER] TOOLS | after_override | subagent_enabled=True | tool_groups=['file:read', 'file:write'] | -> 12 tool(s)
   ```

**预期结果**：
- novel-master 被正确激活
- tool_groups 配置生效，subagent（如 chapter-summarizer）获得 12 个工具（不是 0）
- 工作流被调用（workflow 日志中出现调度信息）

### 第二步（可选）：补丁通用聊天页面

让用户从任何入口都能自动使用正确的 agent。

**修改文件**：`frontend/src/app/workspace/chats/[thread_id]/page.tsx`

**修改内容**（第 ~50-55 行）：
```typescript
// 从 thread metadata 读取 agent_name
const agentName = thread?.metadata?.agent_name;
const context = settings.context || {};
if (agentName) {
  context.agent_name = agentName;
}
const finalContext = { ...context };
// 然后在 useThread 调用中使用 finalContext 而非 settings.context
```

---

## 📚 其他必须内容

### 配置文件参考

**novel-master 配置**：`backend/.deer-flow/agents/novel-master/config.yaml`

应包含以下字段（示例）：
```yaml
model: qwen-3-6-online
subagent_enabled: true
tool_groups:
  - file:read
  - file:write
disallowed_tools:
  - bash
  - read_file_via_git
```

### 工具群组系统

可用的工具群组：
- `file:read` → read_file, glob, grep, ls
- `file:write` → write_file, str_replace
- `file:*` → 包含所有文件工具

### 后续清理

验证完成后，删除 agent.py 中的 3 处诊断日志（3 处 `[DIAG-NOVEL-MASTER]`）。

---

## 🎯 下一步行动清单

- [ ] **第一步**：从正确的 agent 专属页面入口发起测试
- [ ] **验证**：检查后端日志，确认 tool_groups 生效
- [ ] **验证**：确认工作流被调用（workflow 日志）
- [ ] **可选**：补丁前端通用聊天页面
- [ ] **清理**：删除诊断日志
- [ ] **文档更新**：记录 tool_groups 支持

---

## 📖 重要文件路径汇总

### 后端修改
- `backend/packages/harness/deerflow/config/subagents_config.py` ← tool_groups 字段定义
- `backend/packages/harness/deerflow/subagents/config.py` ← SubagentConfig 类
- `backend/packages/harness/deerflow/subagents/registry.py` ← 字段映射
- `backend/packages/harness/deerflow/workflows/helpers.py` ← 工具加载逻辑
- `backend/packages/harness/deerflow/tools/builtins/task_tool.py` ← 优先级处理
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py` ← 诊断日志
- `backend/scripts/serve.sh` ← Windows 进程管理

### 前端修改（可选）
- `frontend/src/app/workspace/chats/[thread_id]/page.tsx` ← 通用聊天页面（待补丁）
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` ← agent 专属页面（已正确）

---

**生成时间**：2026-05-09  
**准备状态**：可直接用于新对话
