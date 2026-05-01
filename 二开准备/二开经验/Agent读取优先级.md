# DeerFlow Agent 配置读取优先级

> 本文档说明 DeerFlow 系统中 Agent 配置的多个来源、读取优先级及调用链路。
> 文档日期：2026-05-01

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

### 2. 后端 `backend/.deer-flow/agents/` 文件夹（运行时目录）

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
└── novel-master/
    └── SOUL.md   （没有 config.yaml）
```

**作用**：这是**运行时实际扫描的目录**。`list_custom_agents()` 函数会扫描此目录下的 `config.yaml` 文件，构建自定义 Agent 列表。

**结论**：✅ 运行时**会**从这里读取 Agent 配置（如果有 `config.yaml`）。

---

### 3. 根目录 `config.yaml` 中的 `subagents.custom_agents`（Subagent 配置）

**路径**：`{repo_root}/config.yaml` → `subagents.custom_agents` 段

**示例**：

```yaml
subagents:
  timeout_seconds: 900
  max_turns: 50

  # Per-agent overrides
  agents:
    novel-architect:
      timeout_seconds: 1800
      max_turns: 80

  # Custom subagents
  custom_agents:
    novel-architect:
      description: "小说架构师，负责新建小说时生成完整基础设定..."
      system_prompt: |
        你是小说创作系统的架构师...
    novel-writer:
      description: "小说写手..."
      system_prompt: |
        你是小说创作系统的写手...
```

**作用**：这是**完全独立的一套配置**，专门用于定义 **Subagent**（子 Agent）的行为。这些 Subagent 通过 `Task` 工具被主 Agent（Lead Agent）调用。

**结论**：✅ 这是主 Agent 调用子 Agent 时的**主要配置来源**。

---

## 二、主 Agent 调用子 Agent 的读取优先级

当主 Agent（Lead Agent）使用 `Task` 工具调用子 Agent 时，系统按以下**严格优先级**查找配置：

### 查找链路（[registry.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/subagents/registry.py#L42-L111)）

```
Task(subagent_type="novel-writer")
    ↓
get_subagent_config("novel-writer")
    ↓
Step 1: 查 BUILTIN_SUBAGENTS（内置子 Agent）
    ├── "general-purpose" → 通用子 Agent
    └── "bash" → Bash 执行子 Agent
    → 如果匹配，返回内置配置
    
Step 2: 查 config.yaml 的 subagents.custom_agents["novel-writer"]
    → 如果找到，返回 description + system_prompt + tools + model 等
    
Step 3: 如果都没找到，返回 None（子 Agent 不可用）
```

**注意**：`backend/.deer-flow/agents/` 目录**不**参与 Subagent 的查找链路！它只用于自定义 Agent 的 API 管理（如 Agents API 的 `list_custom_agents()`）。

---

## 三、两套目录的关系

| 特性 | 根目录 `agents/` | `backend/.deer-flow/agents/` | `config.yaml` 的 `subagents.custom_agents` |
|------|------------------|------------------------------|-------------------------------------------|
| 有 `config.yaml` | ✅ 每个都有 | ❌ 没有 | ✅ 在 YAML 中定义 |
| 有 `SOUL.md` | ✅ 每个都有 | ✅ 只有 novel-master | ❌ 纯文本配置 |
| 被 `Paths` 引用 | ❌ | ✅ 是运行时路径 | ❌ |
| 被 Agents API 扫描 | ❌ | ✅ `list_custom_agents()` | ❌ |
| 被 Subagent 调用 | ❌ | ❌ | ✅ 主要来源 |
| 被 Lead Agent 加载 SOUL | ❌ | ✅ `load_agent_soul()` | ❌ |

---

## 四、关键代码证据

### 1. Subagent 配置查找（[registry.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/subagents/registry.py#L56-L61)）

```python
def get_subagent_config(name: str) -> SubagentConfig | None:
    # Step 1: 查内置
    config = BUILTIN_SUBAGENTS.get(name)
    # Step 2: 查 config.yaml custom_agents
    if config is None:
        config = _build_custom_subagent_config(name)
    if config is None:
        return None
```

### 2. 内置 Subagent 列表（[builtins/__init__.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/subagents/builtins/__init__.py#L12-L15)）

```python
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
}
```

**注意**：`novel-writer`、`novel-architect` 等**不在** `BUILTIN_SUBAGENTS` 中！它们完全依赖 `config.yaml` 的 `custom_agents` 段。

### 3. Lead Agent 加载 SOUL（[agents_config.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/config/agents_config.py#L93-L110)）

```python
def load_agent_soul(agent_name: str | None) -> str | None:
    agent_dir = get_paths().agent_dir(agent_name)  # -> backend/.deer-flow/agents/{name}/
    soul_path = agent_dir / "SOUL.md"
    if not soul_path.exists():
        return None
    return soul_path.read_text(encoding="utf-8").strip()
```

**注意**：`load_agent_soul` 只从 `backend/.deer-flow/agents/` 读取，**不**从根目录 `agents/` 读取。

### 4. Lead Agent 构建时注入 SOUL（[agent.py](file:///c:/xiangmu/deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py#L76-L82)）

```python
async def _build_system_prompt(self) -> str:
    soul = load_agent_soul(self.agent_name)
    if soul:
        system_prompt = f"{self.system_prompt}\n\n{soul}"
    else:
        system_prompt = self.system_prompt
```

---

## 五、实际调用链路总结

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

### 场景 2：Lead Agent 调用子 Agent "novel-writer"

```
Lead Agent 调用 task(subagent_type="novel-writer")
    ↓
Task 工具执行
    ↓
get_subagent_config("novel-writer")
    ↓
Step 1: BUILTIN_SUBAGENTS.get("novel-writer") → None（不在内置列表中）
    ↓
Step 2: _build_custom_subagent_config("novel-writer")
    → 查 config.yaml 的 subagents.custom_agents["novel-writer"]
    → 找到！返回 SubagentConfig(description=..., system_prompt=...)
    ↓
使用 config.yaml 中的 system_prompt 创建子 Agent
```

---

## 六、重要结论

1. **根目录 `agents/` 文件夹**：
   - 是**文档/模板**，运行时不读取
   - 如果你想让某个 Agent 生效，需要把它的文件复制到 `backend/.deer-flow/agents/`

2. **`backend/.deer-flow/agents/` 文件夹**：
   - 是**运行时目录**
   - Lead Agent 的 SOUL.md 从这里读取
   - 但 Subagent 的 system_prompt **不**从这里读取

3. **`config.yaml` 的 `subagents.custom_agents`**：
   - 是**Subagent 的主要配置来源**
   - 你的 `novel-writer`、`novel-architect` 等子 Agent 的 system_prompt 都在这里定义
   - 这是主 Agent 调用子 Agent 时的**唯一有效配置**

4. **如果你修改了根目录 `agents/novel-writer/SOUL.md`**：
   - 这对 Subagent 调用**没有影响**
   - 因为 Subagent 的 system_prompt 来自 `config.yaml` 的 `custom_agents`
   - 如果要生效，需要同步修改 `config.yaml` 中对应的 `system_prompt`
