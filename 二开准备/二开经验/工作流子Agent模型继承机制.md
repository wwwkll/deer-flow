# 工作流子 Agent 模型继承机制

本文档记录 DeerFlow 二开项目中，工作流（Workflow）内部调用的子 Agent 如何继承主 Agent 所选模型的问题排查与修复过程。

---

## 一、问题现象

**用户反馈**：
- 在网页前端选择模型 A（如 `mimo-v2-omni`）作为主 Agent 的模型
- 调用工作流（organize/writing）后，工作流内部的子 Agent 却使用了模型 B（如 `qwen-3-6-online`）
- 子 Agent 的模型与主 Agent 不一致

**日志表现**：
```
[CALL_SUBAGENT_DEBUG] parent_model before fallback: None
[CALL_SUBAGENT_DEBUG] Using fallback model: qwen-3-6-online
[SUBAGENT_DEBUG] config.model: inherit, parent_model: qwen-3-6-online, resolved model_name: qwen-3-6-online
```

---

## 二、根因分析

### 2.1 模型传递链路

主 Agent 选择模型后，模型名称的传递链路如下：

```
前端选择模型
    ↓
Gateway API (build_run_config)
    ↓
make_lead_agent → config["metadata"]["model_name"] = model_name
    ↓
主 Agent 运行 (LangGraph)
    ↓
workflow_tool 被调用
    ↓
execute_workflow(params)
    ↓
工作流 StateGraph 节点执行
    ↓
call_subagent("xxx", task, parent_model=model_name)
    ↓
SubagentExecutor(parent_model=parent_model)
    ↓
_create_agent → create_chat_model(name=parent_model)
```

### 2.2 问题定位

**问题 1：workflow_tool 未正确传递 model_name**

`workflow_tool` 虽然尝试从 `runtime.config.metadata` 获取 `model_name`，但实际日志中 `[WORKFLOW_DEBUG]` 从未出现，说明提取逻辑存在问题或 `runtime.config` 结构不符合预期。

**问题 2：工作流节点未使用 model_name**

`novel_writing.py` 和 `novel_post_process.py` 中的工作流节点调用 `call_subagent` 时**没有传递 `parent_model` 参数**：

```python
# 错误示例（novel_writing.py 修复前）
await call_subagent("novel-writer", task)  # parent_model 为 None
```

**问题 3：helpers.py 中的 fallback 逻辑**

`call_subagent` 函数在 `parent_model` 为 `None` 时，自动 fallback 到 `app_config.models[0].name`（配置中的第一个模型）：

```python
# helpers.py 修复前
if parent_model is None:
    app_config = get_app_config()
    if app_config.models:
        parent_model = app_config.models[0].name  # 总是使用第一个模型！
```

这导致即使主 Agent 选择了其他模型，子 Agent 也会强制使用配置中的第一个模型。

---

## 三、修复方案

### 3.1 修复 workflow_tool 的 model_name 传递

**文件**：`backend/packages/harness/deerflow/tools/builtins/workflow_tool.py`

确保从 `runtime.config.metadata` 正确提取 `model_name` 并传入 `params`：

```python
metadata = runtime.config.get("metadata", {}) if runtime.config else {}
parent_model = metadata.get("model_name")

logger.info(f"[WORKFLOW_TOOL] Called workflow={workflow_name} model_name={parent_model}")

if parent_model:
    params["model_name"] = parent_model
```

### 3.2 修复工作流节点传递 model_name

**文件**：`backend/packages/harness/deerflow/workflows/novel_writing.py`

在每个工作流节点中从 `state` 获取 `model_name`，并传给 `call_subagent`：

```python
async def write_chapter(state: NovelWorkflowState) -> dict[str, Any]:
    # ... 其他代码 ...
    model_name = state.get("model_name")
    
    # ... 构建 task ...
    
    result = await call_subagent("novel-writer", task, parent_model=model_name)
```

需要修复的节点：
- `write_chapter` → `novel-writer`
- `audit_chapter` → `continuity-auditor`
- `revise_chapter` → `novel-reviser`
- `post_process` → `chapter-summarizer`, `state-settler`, `hook-manager`, `card-manager`
- `sync_outline` → `outline-planner`

**文件**：`backend/packages/harness/deerflow/workflows/novel_post_process.py`

同样需要修复：
- `_process_single_chapter` 中所有 `call_subagent` 调用
- `post_process` 节点传入 `model_name`
- `sync_outline` 节点传入 `model_name`

### 3.3 移除 helpers.py 的 fallback 逻辑

**文件**：`backend/packages/harness/deerflow/workflows/helpers.py`

将自动 fallback 改为显式报错，避免静默使用错误模型：

```python
# 修复前（错误）
if parent_model is None:
    app_config = get_app_config()
    if app_config.models:
        parent_model = app_config.models[0].name

# 修复后（正确）
if parent_model is None:
    raise ValueError("parent_model is required but was not provided. Make sure model_name is passed from the workflow state.")
```

### 3.4 修复 organize 工作流

**文件**：`backend/packages/harness/deerflow/workflows/novel_organize.py`

`organize` 工作流在修复前已经正确传递了 `model_name`，但需要确保 `state` 中确实有值：

```python
async def organize_world(state: NovelWorkflowState) -> dict[str, Any]:
    # ... 其他代码 ...
    model_name = state.get("model_name")
    result = await call_subagent("novel-world-organizer", task, parent_model=model_name)
```

### 3.5 确保 executor 传递 model_name

**文件**：`backend/packages/harness/deerflow/workflows/executor.py`

在 `_build_initial_state` 中，`model_name` 已经从 `params` 传入 `state`：

```python
def _build_initial_state(self, params: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for key in NovelWorkflowState.__annotations__:
        if key in params:
            state[key] = params[key]
    return state
```

同时添加日志便于调试：

```python
logger.info(f"[WORKFLOW_EXECUTOR] Executing workflow={self.workflow_name} model_name={params.get('model_name')}")
logger.info(f"[WORKFLOW_EXECUTOR] Initial state keys={list(initial_state.keys())} model_name={initial_state.get('model_name')}")
```

---

## 四、关键文件修改汇总

| 文件 | 修改内容 |
|------|----------|
| `tools/builtins/workflow_tool.py` | 从 `runtime.config.metadata` 提取 `model_name` 并传入 `params` |
| `workflows/helpers.py` | 移除 fallback 到 `app_config.models[0]` 的逻辑，改为显式报错 |
| `workflows/novel_writing.py` | 所有节点从 `state` 获取 `model_name` 并传给 `call_subagent` |
| `workflows/novel_post_process.py` | 所有节点从 `state` 获取 `model_name` 并传给 `call_subagent` |
| `workflows/novel_organize.py` | 已正确传递，无需修改 |
| `workflows/executor.py` | 添加执行日志，便于调试 |

---

## 五、验证方法

### 5.1 查看日志确认模型传递

重启服务后，调用工作流，查看 `langgraph.log`：

```powershell
Get-Content c:\xiangmu\deer-flow\logs\langgraph.log -Tail 100 | Select-String "WORKFLOW_TOOL|CALL_SUBAGENT_DEBUG|SUBAGENT_DEBUG"
```

**预期输出**：
```
[WORKFLOW_TOOL] Called workflow=organize model_name=mimo-v2-omni
[WORKFLOW_EXECUTOR] Executing workflow=organize model_name=mimo-v2-omni
[CALL_SUBAGENT_DEBUG] parent_model: mimo-v2-omni
[SUBAGENT_DEBUG] config.model: inherit, parent_model: mimo-v2-omni, resolved model_name: mimo-v2-omni
```

### 5.2 确认 HTTP 请求目标

如果子 Agent 使用了正确的模型，HTTP 请求应该发送到对应模型的 API 端点：

```powershell
Get-Content c:\xiangmu\deer-flow\logs\langgraph.log -Tail 50 | Select-String "HTTP Request"
```

**预期输出**（使用 mimo 模型时）：
```
HTTP Request: POST https://token-plan-cn.xiaomimimo.com/v1/chat/completions
```

---

## 六、经验总结

### 6.1 设计原则

1. **显式传递优于隐式 fallback**：不要静默使用默认模型，应该显式传递模型名称
2. **快速失败**：如果 `parent_model` 为 `None`，应该立即报错，而不是 fallback 到默认模型
3. **全链路传递**：从主 Agent → workflow_tool → execute_workflow → 工作流节点 → call_subagent → SubagentExecutor，每个环节都要确保 `model_name` 被正确传递

### 6.2 常见陷阱

| 陷阱 | 说明 |
|------|------|
| `call_subagent` 漏传 `parent_model` | 工作流节点调用子 Agent 时必须显式传递 `parent_model` |
| `helpers.py` fallback 逻辑 | 自动 fallback 会掩盖问题，导致使用错误模型 |
| `state` 中 `model_name` 为空 | 需要确保 `workflow_tool` 正确从 `runtime.config.metadata` 提取并传入 `params` |
| 子 Agent config 的 `model` 字段 | 子 Agent 的 `model` 配置应为 `"inherit"`，才能继承 `parent_model` |

### 6.3 调试技巧

1. **添加关键日志**：在 `workflow_tool`、`execute_workflow`、`call_subagent`、`_create_agent` 等关键位置添加日志
2. **查看 HTTP 请求日志**：通过 `langgraph.log` 中的 `HTTP Request` 确认实际调用的模型端点
3. **使用 `Select-String` 过滤日志**：快速定位相关日志行

---

## 七、相关配置

### 7.1 子 Agent 模型配置

在 `config.yaml` 的 `subagents.custom_agents` 中，子 Agent 的 `model` 应配置为 `"inherit"`：

```yaml
subagents:
  custom_agents:
    - name: novel-writer
      model: inherit  # 继承主 Agent 的模型
      # ... 其他配置
```

### 7.2 模型配置

确保 `config.yaml` 中配置了多个模型：

```yaml
models:
  - name: qwen-3-6-online
    # ...
  - name: mimo-v2-omni
    # ...
```

---

*文档创建时间：2026-05-01*
*适用版本：DeerFlow 二开项目*
