# DeerFlow Agent 配置读取优先级

> 本文档说明 DeerFlow 系统中 Agent 配置的多个来源、读取优先级及调用链路。
> 文档日期：2026-05-07（更新）

---

## 一、系统中存在三套 Agent 配置

你的项目中有 **三套** 不同的 Agent 配置体系，分别位于不同位置，服务于不同目的：

### 1. 根目录 `agents/` 文件夹（文档/模板目录）

**路径**：`{repo_root}/agents/`

**内容**：每个子目录包含 `config.yaml` + `SOUL.md`

```
agents/
├── blank-agent/
├── code-reviewer/
├── custom-agent/
├── novel-architect/
├── novel-master/
├── novel-writer/
├── search/
├── template-agent/
└── ...（共12个）
```

**作用**：这是**项目级别的文档/模板目录**，用来记录和管理所有 Agent 的定义。它本身**不直接参与运行时加载**。

**结论**：⚠️ 运行时**不会**从这里读取 Agent 配置。

---

### 2. 后端 `backend/.deer-flow/agents/` 文件夹（运行时目录）⭐ 主要配置源

**路径**：`{repo_root}/backend/.deer-flow/agents/`

**计算方式**（[paths.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/config/paths.py#L12-L15)）：

```python
def _default_local_base_dir() -> Path:
    backend_dir = Path(__file__).resolve().parents[4]  # -> backend/
    return backend_dir / ".deer-flow"                   # -> backend/.deer-flow/
```

所以 `Paths().agents_dir` = `backend/.deer-flow/agents/`

**当前内容**：
```
backend/.deer-flow/agents/
├── book-rules-manager/      (config.yaml + SOUL.md)
├── chapter-summarizer/      (config.yaml + SOUL.md)
├── continuity-auditor/      (config.yaml + SOUL.md)
├── hook-manager/            (config.yaml + SOUL.md)
├── novel-architect/         (config.yaml + SOUL.md)
├── novel-character-organizer/ (config.yaml + SOUL.md)
├── novel-item-organizer/    (config.yaml + SOUL.md)
├── novel-master/            (SOUL.md，Lead Agent)
├── novel-reviser/           (config.yaml + SOUL.md)
├── novel-storyline-organizer/ (config.yaml + SOUL.md)
├── novel-world-organizer/   (config.yaml + SOUL.md)
├── novel-writer/            (config.yaml + SOUL.md)
├── outline-planner/         (config.yaml + SOUL.md)
├── state-settler/           (config.yaml + SOUL.md)
├── style-analyzer/          (SOUL.md)
└── volume-planner/          (config.yaml + SOUL.md)
```

**每个 Agent 目录的文件**：
- `config.yaml`：元数据（description、tools、model、max_turns、timeout_seconds）
- `SOUL.md`：提示词/人设（system_prompt）

**作用**：
- **Lead Agent**：`load_agent_soul()` 从这里读取 SOUL.md 注入 system prompt
- **Subagent**：`_build_subagent_from_agents_dir()` 从这里读取 config.yaml + SOUL.md 作为 fallback

**结论**：✅ 运行时**会**从这里读取 Agent 配置。这是当前 subagent 的**主要配置源**。

---

### 3. 根目录 `config.yaml` 中的 `subagents.custom_agents`（已清空）

**路径**：`{repo_root}/config.yaml` → `subagents.custom_agents` 段

**当前状态**：`custom_agents: {}` （已清空，配置已迁移到 agents 目录）

**作用**：如果需要临时覆盖某个 subagent 的配置，可以在这里添加。优先级高于 agents 目录。

**结论**：⚠️ 当前为空，仅作为**可选的覆盖层**。

---

## 二、Subagent 配置读取优先级

当主 Agent（Lead Agent）使用 `Task` 工具调用子 Agent，或工作流通过 `call_subagent` 调用子 Agent 时，系统按以下**严格优先级**查找配置：

### 查找链路（[registry.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/subagents/registry.py)）

```
get_subagent_config("novel-writer")
    ↓
Step 1: 查 BUILTIN_SUBAGENTS（内置子 Agent）
    ├── "general-purpose" → 通用子 Agent
    └── "bash" → Bash 执行子 Agent
    → 如果匹配，返回内置配置
    
Step 2: 查 config.yaml 的 subagents.custom_agents["novel-writer"]
    → 如果找到，返回 description + system_prompt + tools + model 等
    → 当前为空 {}，跳过
    
Step 3: 查 backend/.deer-flow/agents/novel-writer/ 目录
    → 读取 config.yaml 获取元数据（tools、model、max_turns 等）
    → 读取 SOUL.md 作为 system_prompt
    → 构建 SubagentConfig 返回
    
Step 4: 如果都没找到，返回 None（子 Agent 不可用）
```

### 查找优先级总结

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1（最高）| `config.yaml` 的 `custom_agents` | 临时覆盖，当前为空 |
| 2 | `backend/.deer-flow/agents/{name}/` | 主要配置源（config.yaml + SOUL.md） |
| 3 | BUILTIN_SUBAGENTS | 内置 agent（general-purpose、bash） |

---

## 三、Lead Agent 配置读取

Lead Agent（如 novel-master）的读取链路与 Subagent 不同：

```
make_lead_agent(name="novel-master")
    ↓
load_agent_config("novel-master")
    → 查 backend/.deer-flow/agents/novel-master/config.yaml
    → 加载 model、tool_groups、skills、subagent_enabled 等
    ↓
load_agent_soul("novel-master")
    → 查 backend/.deer-flow/agents/novel-master/SOUL.md
    → 读取内容，注入到 system_prompt
    ↓
构建 Lead Agent
```

---

## 四、两套目录的关系

| 特性 | 根目录 `agents/` | `backend/.deer-flow/agents/` | `config.yaml` 的 `custom_agents` |
|------|------------------|------------------------------|-------------------------------------------|
| 有 `config.yaml` | ✅ 每个都有 | ✅ 每个 subagent 都有 | ✅ 在 YAML 中定义（当前为空） |
| 有 `SOUL.md` | ✅ 每个都有 | ✅ 每个都有 | ❌ 纯文本配置 |
| 被 `Paths` 引用 | ❌ | ✅ 是运行时路径 | ❌ |
| 被 Agents API 扫描 | ❌ | ✅ `list_custom_agents()` | ❌ |
| 被 Subagent 调用 | ❌ | ✅ fallback 来源 | ✅ 优先来源（当前为空） |
| 被 Lead Agent 加载 SOUL | ❌ | ✅ `load_agent_soul()` | ❌ |

---

## 五、工作流调用链路

### 工作流注册

系统中有 3 个工作流，通过 `register_workflow()` 注册：

| 工作流 | 文件 | 说明 |
|--------|------|------|
| `organize` | [novel_organize.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/workflows/novel_organize.py) | 整理参考材料（世界观、人物、道具等） |
| `writing` | [novel_writing.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/workflows/novel_writing.py) | 写作流程（写正文 → 审核 → 修改） |
| `post_process` | [novel_post_process.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/workflows/novel_post_process.py) | 后处理（总结、状态更新、伏笔管理） |

### 工作流调用 Subagent 的方式

工作流通过 `call_subagent()` 调用子 Agent（[helpers.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/workflows/helpers.py#L87-L121)）：

```python
async def call_subagent(subagent_name: str, task: str, ...) -> str:
    config = get_subagent_config(subagent_name)  # 走上面的查找链路
    tools = get_available_tools(...)              # 获取工具列表
    executor = SubagentExecutor(config=config, tools=tools, ...)
    result = await executor._aexecute(task)
    return result.result or ""
```

### writing 工作流的子 Agent 调用链

```
novel-master (Lead Agent)
    ↓ workflow("writing", params)
WritingWorkflow (StateGraph)
    ├── write_chapter() → call_subagent("novel-writer", task)
    ├── audit_chapter() → call_subagent("continuity-auditor", task)
    ├── revise_chapter() → call_subagent("novel-reviser", task)
    └── post_process:
        ├── call_subagent("chapter-summarizer", task)
        ├── call_subagent("state-settler", task)
        └── call_subagent("hook-manager", task)
```

### organize 工作流的子 Agent 调用链

```
novel-master (Lead Agent)
    ↓ workflow("organize", params)
OrganizeWorkflow (StateGraph)
    ├── 世界观整理 → call_subagent("novel-world-organizer", task)
    ├── 人物整理 → call_subagent("novel-character-organizer", task)
    ├── 道具整理 → call_subagent("novel-item-organizer", task)
    └── 故事线整理 → call_subagent("novel-storyline-organizer", task)
```

### SubagentExecutor 执行流程

```
SubagentExecutor._create_agent()
    ↓
model = create_chat_model(name=model_name)  # 继承父 Agent 的模型
tools = _filter_tools(all_tools, allowed, disallowed)  # 按白名单过滤
system_prompt = config.system_prompt  # 从 SOUL.md 读取
    ↓
create_agent(model, tools, middleware, system_prompt)
    ↓
agent.astream(state)  # 流式执行，最多 max_turns 轮
    ↓
收集 AIMessage → 返回结果
```

---

## 六、实际调用链路总结

### 场景 1：用户访问 Web 界面，选择 "novel-master" Agent

```
用户选择 novel-master
    ↓
POST /agents/novel-master/threads/{thread_id}/runs
    ↓
make_lead_agent(name="novel-master")
    ↓
load_agent_config("novel-master")  # 查 backend/.deer-flow/agents/novel-master/config.yaml
    → 文件不存在！返回 None
    ↓
使用默认配置（name="novel-master", subagent_enabled=True）
    ↓
load_agent_soul("novel-master")  # 查 backend/.deer-flow/agents/novel-master/SOUL.md
    → 文件存在！读取内容
    ↓
构建 Lead Agent，将 SOUL.md 内容注入 system prompt
```

### 场景 2：Lead Agent 通过工作流调用子 Agent "novel-writer"

```
Lead Agent 调用 workflow("writing", params)
    ↓
WritingWorkflow.write_chapter()
    ↓
call_subagent("novel-writer", task)
    ↓
get_subagent_config("novel-writer")
    ↓
Step 1: BUILTIN_SUBAGENTS.get("novel-writer") → None
Step 2: config.yaml custom_agents["novel-writer"] → 空 {}，跳过
Step 3: _build_subagent_from_agents_dir("novel-writer")
    → 读取 backend/.deer-flow/agents/novel-writer/config.yaml → 获取 tools、model 等
    → 读取 backend/.deer-flow/agents/novel-writer/SOUL.md → 获取 system_prompt
    → 构建 SubagentConfig 返回
    ↓
SubagentExecutor 创建 Agent 并执行
```

### 场景 3：Lead Agent 通过 Task 工具直接调用子 Agent

```
Lead Agent 调用 task(subagent_type="novel-writer", prompt="...")
    ↓
Task 工具执行
    ↓
get_subagent_config("novel-writer")  # 同场景 2 的查找链路
    ↓
SubagentExecutor 创建 Agent 并执行
```

---

## 七、重要结论

1. **根目录 `agents/` 文件夹**：
   - 是**文档/模板**，运行时不读取
   - 如果你想让某个 Agent 生效，需要把它的文件复制到 `backend/.deer-flow/agents/`

2. **`backend/.deer-flow/agents/` 文件夹**：
   - 是**运行时目录**，也是当前 subagent 的**主要配置源**
   - 每个 agent 目录包含 `config.yaml`（元数据）和 `SOUL.md`（提示词）
   - Lead Agent 的 SOUL.md 从这里读取
   - Subagent 的 config.yaml + SOUL.md 也从这里读取（作为 fallback）

3. **`config.yaml` 的 `subagents.custom_agents`**：
   - 当前已清空为 `{}`
   - 如果需要临时覆盖某个 subagent 的配置，可以在这里添加
   - 优先级高于 `backend/.deer-flow/agents/` 目录

4. **修改 Agent 配置的方法**：
   - 修改提示词：编辑 `backend/.deer-flow/agents/{name}/SOUL.md`
   - 修改工具/模型等：编辑 `backend/.deer-flow/agents/{name}/config.yaml`
   - 临时覆盖：在 `config.yaml` 的 `custom_agents` 中添加条目

5. **工作流调用子 Agent**：
   - 工作流通过 `call_subagent()` 调用子 Agent
   - 查找链路与 Task 工具相同
   - 子 Agent 的工具按 config.yaml 中的 `tools` 白名单过滤
