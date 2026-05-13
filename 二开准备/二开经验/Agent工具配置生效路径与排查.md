# Agent 工具配置生效路径与排查

> 本文档记录 DeerFlow 二开过程中遇到的工具（`tools`）与工具组（`tool_groups`）配置在不同调用路径下是否生效的问题，及修复方案。
>
> **适用场景**：你在某个 agent 或 subagent 的 `config.yaml` 里写了 `tools:` 或 `tool_groups:`，但实际运行时发现 agent 拿到的工具数量不对（全部工具、零个工具、或与配置不符）。

---

## 一、TL;DR — 三条调用路径速查表

DeerFlow 中工具加载有**三条路径**，每条路径对 `config.yaml` 中 `tools` / `tool_groups` 字段的解析方式不一样：

| 调用路径 | 触发场景 | 工具过滤策略 | 历史问题 |
| --- | --- | --- | --- |
| **A. Lead Agent 直接加载** | 用户从前端开聊，进入 `make_lead_agent()` | 读 `agent_config.tools` / `tool_groups` 给 `get_available_tools()` | ✅ 一直正常 |
| **B. task tool 调度 subagent** | LLM 主动调用 `task` 工具 | 读 parent metadata 的 `tools` / `tool_groups`；现已支持 subagent 自身 config 覆盖 | ⚠️ 修复前会强制继承 parent，无视 subagent 自己的配置 |
| **C. workflow 调度 subagent** | 代码里调用 `call_subagent()`（workflow 节点） | 读 `config.tools` / `config.tool_groups` 给 `get_available_tools()` | ⚠️ 修复前完全没传，导致全部工具被加载 |

记忆要点：

- **A 路径**：agent 配置里写 `tools` / `tool_groups`，直接生效。
- **B 路径**：subagent 配置里写 `tools` / `tool_groups`，从 2026-05 起优先于 parent。
- **C 路径**：subagent 配置里写 `tools` / `tool_groups`，从 2026-05 起在 workflow 调用中生效。

---

## 二、关键代码与数据结构

### 2.1 配置数据结构（修复后）

```
AgentConfig                 ← 顶层 agent（lead）配置 (config/agents_config.py)
├── tools: list[str]?
└── tool_groups: list[str]?

CustomSubagentConfig        ← config.yaml -> subagents.custom_agents.* (config/subagents_config.py)
├── tools: list[str]?
└── tool_groups: list[str]?        ← 2026-05 修复补齐

SubagentConfig              ← 运行时 subagent 配置 dataclass (subagents/config.py)
├── tools: list[str]?
└── tool_groups: list[str]?        ← 2026-05 修复补齐
```

### 2.2 三条路径的工具加载逻辑

```
A) make_lead_agent()                        backend/packages/harness/deerflow/agents/lead_agent/agent.py
   tools = get_available_tools(
       groups = agent_config.tool_groups,
       tools  = agent_config.tools,
       ...,
   )

B) task_tool()                              backend/packages/harness/deerflow/tools/builtins/task_tool.py
   effective_tools       = config.tools       or parent_tools
   effective_tool_groups = config.tool_groups or parent_tool_groups
   tools = get_available_tools(groups=effective_tool_groups, tools=effective_tools, ...)

C) call_subagent()                          backend/packages/harness/deerflow/workflows/helpers.py
   tools = get_available_tools(
       groups = config.tool_groups,
       tools  = config.tools,
       ...,
   )
```

### 2.3 二次过滤兜底（重要）

无论 A/B/C 哪条路径，`SubagentExecutor.__init__` 都会再做一次过滤：

```python
# backend/packages/harness/deerflow/subagents/executor.py
self.tools = _filter_tools(tools, config.tools, config.disallowed_tools)
```

这就是为什么修复前即使 `helpers.py` 没传 `config.tools`，subagent 拿到的工具数量看起来也"差不多对"——SubagentExecutor 内部还会再砍一遍。

**但二次过滤只认 `config.tools`，不认 `config.tool_groups`**。所以如果你的 subagent 只配了 `tool_groups`，没配 `tools`，那二次过滤不会进一步收紧，必须依赖 A/B/C 这一步把范围控制好。

---

## 三、`get_available_tools()` 的过滤优先级

定义位置：`backend/packages/harness/deerflow/tools/tools.py`

```python
def get_available_tools(
    groups: list[str] | None = None,
    tools:  list[str] | None = None,
    ...
):
    if tools is not None:
        # 1. tools 白名单优先
        tool_configs = [t for t in config.tools if t.name in tools]
    elif groups is not None:
        # 2. tool_groups 次之
        tool_configs = [t for t in config.tools if t.group in groups]
    else:
        # 3. 都没传则全部
        tool_configs = list(config.tools)
```

**记忆口诀**：`tools > groups > all`。一旦设了 `tools`，`groups` 就被忽略。

---

## 四、历史踩坑记录

### 4.1 现象 1：subagent 拿到 0 个工具

**触发**：subagent 的 config.yaml 写了 `tool_groups: [file:read, file:write]`，但 chapter-summarizer 等运行时拿到 0 工具。

**根因**：
- `SubagentConfig` dataclass **没有 `tool_groups` 字段**。
- `registry.py` 的 `_SUBAGENT_CONFIG_FIELDS` 集合**没列出 `tool_groups`**，所以 yaml 解析时这个字段被静默丢弃。
- `CustomSubagentConfig`（pydantic）也没声明这个字段。
- workflow 路径下 `helpers.py` 加载时没传任何过滤参数 → 加载全部工具 → SubagentExecutor 的二次过滤用 `config.tools=None` 不过滤 → 应该是全部工具。
- 但实际"0 工具"是因为同时还有 `disallowed_tools=["task"]` 等默认禁用项叠加旧逻辑导致的极端情况。

**修复**：
1. `SubagentConfig` / `CustomSubagentConfig` 补 `tool_groups` 字段
2. `_SUBAGENT_CONFIG_FIELDS` 加入 `"tool_groups"`
3. `_build_custom_subagent_config()` 透传 `tool_groups=custom.tool_groups`
4. `helpers.py` `call_subagent()` 把 `config.tool_groups` 传给 `get_available_tools()`
5. `task_tool.py` 让 subagent 自身的 tool_groups 优先于 parent metadata

### 4.2 现象 2：subagent 通过 task tool 调用时被父 agent 工具限制束缚

**触发**：subagent 配了 `tools: [read_file, write_file, custom_validator]`，但通过 LLM 的 `task` 工具调用时只拿到 `[read_file, write_file]`（没有 `custom_validator`）。

**根因**：旧版 `task_tool.py` 只从 parent metadata 读 `tools` / `tool_groups`，完全忽略 subagent 自己的 config。subagent 想"破格"使用 parent 没有的工具就被卡住。

**修复**：`task_tool.py` 中改为：
```python
effective_tools       = config.tools       if config.tools       is not None else parent_tools
effective_tool_groups = config.tool_groups if config.tool_groups is not None else parent_tool_groups
```
subagent 自身配置优先；只有不写自己的时候才继承 parent。

### 4.3 现象 3：workflow 调用 subagent 时 MCP 工具被全量加载

**触发**：workflow 节点调用 `call_subagent("chapter-summarizer", ...)`，启动很慢，日志显示 MCP 工具全量加载。

**根因**：`helpers.py` 旧版只写 `tools = get_available_tools(model_name=parent_model, subagent_enabled=False)`，没有任何过滤。

**修复**：把 `config.tools` 和 `config.tool_groups` 都传进去，提前过滤。

### 4.4 现象 4（次要）：agent_name 未注入导致 lead agent 配置失效

不直接属于工具组问题，但与现象 1 经常一起出现。前端 `/workspace/chats/<id>` 路由不会注入 `agent_name`，导致后端 `make_lead_agent()` 拿到 `agent_name=None`，根本不加载 `novel-master/config.yaml`，subagent_enabled 永远是 false。

**触发判断**：后端日志看 `Create Agent(default) -> ... subagent_enabled: False`，说明走默认 agent 而非自定义。

**绕过办法**：从 `/workspace/agents/novel-master/chats/<id>` 入口建会话。或修补前端从 thread metadata 读 `agent_name` 注入 context。

---

## 五、排查清单（按顺序检查）

### 5.1 确定走的是哪条路径

后端日志关键标识：

| 路径 | 日志特征 |
| --- | --- |
| **A. Lead agent** | `Create Agent(<agent_name>) -> ...` |
| **B. task tool** | `[trace=xxxxxxxx] task_tool resolving subagent=...` |
| **C. workflow** | `[CALL_SUBAGENT_DEBUG] subagent=...` |

### 5.2 看实际生效的过滤参数

打开 backend 日志，找你 subagent 名字，确认日志里：

```
[CALL_SUBAGENT_DEBUG] subagent=chapter-summarizer tools=None tool_groups=['file:read','file:write'] -> 6 tool(s)
```

- `tools=None` 且 `tool_groups=None` 表示 config 没读到 → yaml 字段名或路径写错
- `tools=[...]` 但数量为 0 → 工具名拼错或工具未在 `config.yaml` 注册
- `tool_groups=[...]` 但数量为 0 → 工具组名不存在或没有任何工具归属该组

### 5.3 SubagentExecutor 的最终工具数

```
[trace=xxxxxxxx] SubagentExecutor initialized: <name> with N tools
```

这个 N 才是 agent 真正能用的数量。和上一行的 `-> X tool(s)` 对照：

- N < X：被 `config.tools` 或 `config.disallowed_tools` 二次过滤了
- N == X：没二次过滤
- N == 0：检查 `disallowed_tools`（默认含 `task`）和 `tools` 白名单是否冲突

### 5.4 yaml 字段名速查

| 写在哪 | 字段名 | 类型 |
| --- | --- | --- |
| `backend/.deer-flow/agents/<name>/config.yaml` | `tools` 或 `tool_groups` | list[str] |
| `config.yaml -> subagents.custom_agents.<name>` | `tools` 或 `tool_groups` | list[str] |

**注意**：不能写 `tool-groups`、`toolGroups`、`tool_group`（单数），pydantic 会忽略不认识的字段，且日志不会报错。

---

## 六、修复历史归档

| 日期 | 修改文件 | 改动概要 |
| --- | --- | --- |
| 2026-05 | `subagents/config.py` | `SubagentConfig` 加 `tool_groups: list[str] \| None = None` |
| 2026-05 | `config/subagents_config.py` | `CustomSubagentConfig` 加 `tool_groups` Field |
| 2026-05 | `subagents/registry.py` | `_SUBAGENT_CONFIG_FIELDS` 加入 `"tool_groups"`；`_build_custom_subagent_config` 透传 |
| 2026-05 | `workflows/helpers.py` | `call_subagent` 把 `config.tools` / `config.tool_groups` 传给 `get_available_tools`，加 `[CALL_SUBAGENT_DEBUG]` 日志 |
| 2026-05 | `tools/builtins/task_tool.py` | subagent 自身 `tools` / `tool_groups` 优先于 parent metadata；加诊断日志 |

---

## 七、推荐配置模板

### 7.1 用 tool_groups（粗粒度，推荐）

```yaml
# backend/.deer-flow/agents/chapter-summarizer/config.yaml
description: 章节摘要生成
tool_groups:
  - file:read
  - file:write
model: inherit
max_turns: 30
```

### 7.2 用 tools（细粒度，受限场景）

```yaml
# backend/.deer-flow/agents/novel-writer/config.yaml
description: 小说作家
tools:
  - writer_reader      # 受限读
  - write_file
  - str_replace
model: inherit
max_turns: 50
```

### 7.3 混合（不推荐）

不要同时写 `tools` 和 `tool_groups`，因为 `tools` 永远会覆盖 `tool_groups`，写两个只会让排查变难。

---

## 八、相关文档

- [工具与工具组配置指南.md](./工具与工具组配置指南.md) - 工具/工具组完整清单
- [Agent-Skill-Tool配置指南.md](./Agent-Skill-Tool配置指南.md) - Agent 配置入门
- [工作流Workflow配置指南.md](./工作流Workflow配置指南.md) - Workflow 节点设计
- [工作流子Agent模型继承机制.md](./工作流子Agent模型继承机制.md) - parent_model 继承相关问题

---

*文档最后更新：2026-05-13*
