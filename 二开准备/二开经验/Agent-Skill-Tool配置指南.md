# Agent / Skill / Tool 配置指南

本文档说明如何在 DeerFlow 二开项目中配置 Agent、Skill 和 Tool。

---

## 一、整体架构

```
config.yaml (全局配置)
├── models          → 模型配置（LLM 连接信息）
├── tool_groups     → 工具组声明
├── tools           → 工具注册（名称 → Python 模块映射）
├── skills          → Skills 目录配置
├── subagents       → 子 Agent 超时/轮次配置
└── custom_agents   → 自定义子 Agent 定义（描述、提示词、工具、模型）

backend/.deer-flow/agents/
├── novel-master/           ← 主 Agent
│   ├── SOUL.md             ← 人格/指令提示词
│   └── config.yaml         ← Agent 配置（模型、工具组、技能、子 Agent 开关）
├── novel-writer/           ← 子 Agent 1
│   ├── SOUL.md
│   └── config.yaml
├── continuity-auditor/     ← 子 Agent 2
│   └── ...
└── ...                     ← 更多子 Agent
```

---

## 二、配置 Tool（工具）

### 2.1 工具注册流程

工具在 `config.yaml` 中注册，分为两步：

#### 步骤 1：声明工具组

```yaml
tool_groups:
  - name: web              # 网络搜索组
  - name: file:read        # 文件读取组
  - name: file:write       # 文件写入组
  - name: bash             # 命令行组
  - name: novel:tools      # 小说系统工具组（context_assembler、card_validator 等）
  - name: master:write     # 主控专用写入组（受限白名单，master_writer）
```

#### 步骤 2：注册具体工具

```yaml
tools:
  # === 内置工具示例 ===
  - name: read_file
    group: file:read
    use: deerflow.sandbox.tools:read_file_tool

  - name: write_file
    group: file:write
    use: deerflow.sandbox.tools:write_file_tool

  # === 自定义工具示例 ===
  - name: context_assembler
    group: novel:tools
    use: my_tools.context_assembler:context_assembler

  - name: card_validator
    group: novel:tools
    use: my_tools.card_validator:card_validator

  # === 主控专用工具（受限白名单）===
  - name: master_writer
    group: master:write
    use: my_tools.master_writer:master_writer
```

**字段说明**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 工具名称（Agent 调用时使用的名称） | `card_validator` |
| `group` | 所属工具组 | `novel` |
| `use` | Python 模块映射：`模块路径:函数名` | `my_tools.card_validator:card_validator` |

### 2.2 编写自定义 Tool

在 `my_tools/` 目录下创建 Python 文件：

```python
# my_tools/card_validator.py
from langchain.tools import tool

@tool("card_validator")
def card_validator(card_path: str, fix: bool = True) -> str:
    """验证并规范化 card.json 文件格式。

    Args:
        card_path: card.json 文件路径
        fix: 是否自动修复格式问题
    """
    # ... 工具逻辑
    return "验证结果报告"
```

**要点**：
- 使用 `@tool("工具名")` 装饰器
- 函数必须有类型注解和 docstring
- 返回字符串作为工具输出
- 在 `config.yaml` 中注册后，Agent 即可调用

### 2.3 工具使用示例

Agent 在对话中调用工具：

```
调用 card_validator 验证文件：
- card_path: "book/测试项目/card.json"
- fix: true
```

### 2.4 受限白名单工具模式

当需要限制 Agent 只能操作特定文件时，可以创建受限白名单工具，替代通用的 `file:write`。

**设计思路**：
- 移除 Agent 的通用写入权限（`file:write`、`bash`）
- 创建专用工具，内部使用白名单验证路径
- 只允许写入特定目录/文件

**示例：master_writer 工具**（novel-master 专用）：

| 操作 | 允许 | 说明 |
|------|------|------|
| 创建目录 | ✅ | 新建小说时创建目录结构 |
| 写入 `03-状态/` 目录 | ✅ | 阶段性总结等状态文件 |
| 写入 `card.json` | ❌ | 由 `card_validator` 工具处理 |
| 写入 `02-正文/` | ❌ | 由 `novel-writer` 子 Agent 处理 |
| 写入 `01-规划/` | ❌ | 由 `outline-planner` 等子 Agent 处理 |

**核心验证逻辑**：

```python
def _is_allowed_path(file_path: str) -> bool:
    path_obj = Path(file_path)
    # 白名单：只允许 03-状态 目录下的文件
    if path_obj.parent.name == "03-状态":
        return True
    return False
```

**配置方式**：

```yaml
# config.yaml - 工具组和工具注册
tool_groups:
  - name: master:write     # 受限写入组

tools:
  - name: master_writer
    group: master:write
    use: my_tools.master_writer:master_writer

# novel-master/config.yaml - Agent 引用
tool_groups:
  - file:read
  - master:write    # 替代 file:write + bash
  - novel:tools
```

**优势**：
- 最小权限原则：Agent 只获得完成任务所需的最小权限
- 防止越权：主控 Agent 无法直接写正文/规划文件
- 职责分离：所有业务文件写入由对应子 Agent 完成

**示例：novel_reader 工具**（novel-writer 专用）：

| 路径 | 允许 | 说明 |
|------|------|------|
| `*/_task/*` | ✅ | 写作任务汇总等 |
| `*/05-参考/*` | ✅ | 样式指纹等 |
| `*/02-正文/*` | ✅ | 正文章节（上一章参考） |
| `*/03-状态/*` | ❌ | 由 state-settler 等处理 |
| `*/00-世界观/*` | ❌ | 由 organizer 处理 |
| `*/01-规划/*` | ❌ | 由 outline-planner 处理 |

配置方式：

```yaml
# config.yaml
tool_groups:
  - name: novel:reader

tools:
  - name: novel_reader
    group: novel:reader
    use: my_tools.novel_reader:novel_reader

# novel-writer/config.yaml
tool_groups:
  - novel:reader    # 替代 file:read
  - file:write      # 保留写入权限
```

---

## 三、配置 Agent

### 3.1 Agent 目录结构

每个 Agent 在 `backend/.deer-flow/agents/<agent-name>/` 下有一个目录：

```
backend/.deer-flow/agents/novel-master/
├── SOUL.md      # Agent 人格/指令提示词（核心）
└── config.yaml  # Agent 运行配置
```

### 3.2 config.yaml 配置

```yaml
name: novel-master
description: |
  小说创作系统主控Agent，负责协调所有子Agent完成小说创作任务。
  接收用户指令，判断任务类型，调用合适的子Agent，管理整个创作流程。
model: null                        # null = 使用全局默认模型
tool_groups:                       # 此 Agent 可用的工具组
  - file:read
  - master:write                   # 主控专用写入组（master_writer）
  - novel:tools                    # 小说系统工具组（card_validator 等）
skills:                            # 此 Agent 可用的技能
  - novel-post-write-validator
  - novel-anti-ai-detector
  - novel-plan-compliance
subagent_enabled: true             # 是否允许调用子 Agent
max_concurrent_subagents: 3        # 最大并发子 Agent 数量
```

**字段说明**：

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `name` | Agent 名称 | `novel-master` |
| `description` | Agent 描述（用于子 Agent 发现） | 多行文本 |
| `model` | 使用的模型（null=继承全局） | `null` 或模型名 |
| `tool_groups` | 可用工具组列表 | `["file:read", "novel"]` |
| `skills` | 可用技能列表 | `["novel-post-write-validator"]` |
| `subagent_enabled` | 是否启用子 Agent 调用 | `true`/`false` |
| `max_concurrent_subagents` | 最大并发子 Agent 数 | `3` |

### 3.3 SOUL.md 配置

SOUL.md 是 Agent 的核心人格文件，定义了：
- Agent 的角色和职责
- 工作流程和决策树
- 输入输出规范
- 目录结构认知
- 注意事项和约束

**标准 SOUL.md 结构**：

```markdown
# [系统名称] - [Agent名称] Agent

你是 [描述]。

## 职责
1. ...
2. ...

## 工作流程
### 步骤1：...
### 步骤2：...

## 输入输出
...

## 目录结构
...

## 当前环境
- 工作目录：${__WORKING_DIR__}
```

### 3.4 子 Agent 配置

子 Agent 在 `config.yaml` 的 `subagents.custom_agents` 中定义：

```yaml
subagents:
  timeout_seconds: 900              # 默认超时
  max_turns: 50                     # 默认最大轮次

  # 特定 Agent 的超时覆盖
  agents:
    novel-writer:
      timeout_seconds: 1800
      max_turns: 80

  # 自定义子 Agent 定义
  custom_agents:
    novel-writer:
      description: |
        长篇网文写手，负责根据写作任务汇总撰写小说正文。
      system_prompt: |
        你是一个专业的长篇网文写手...
        ## 写作风格要求
        1. ...
        2. ...
      tools:                        # 此子 Agent 可用的具体工具
        - read_file
        - write_file
      model: inherit                # inherit = 继承父 Agent 模型
      max_turns: 80
      timeout_seconds: 1800
```

**字段说明**：

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `description` | 子 Agent 描述（用于主 Agent 发现） | 多行文本 |
| `system_prompt` | 子 Agent 的系统提示词 | 多行文本 |
| `tools` | 子 Agent 可用的工具列表 | `["read_file", "write_file"]` |
| `model` | 使用的模型 | `inherit` 或模型名 |
| `max_turns` | 最大对话轮次 | `80` |
| `timeout_seconds` | 超时时间（秒） | `1800` |

### 3.5 新增 Agent 的完整流程

1. **创建 Agent 目录**：
   ```
   backend/.deer-flow/agents/my-new-agent/
   ├── SOUL.md
   └── config.yaml
   ```

2. **编写 SOUL.md**：定义 Agent 人格和职责

3. **编写 config.yaml**：
   ```yaml
   name: my-new-agent
   description: 描述此 Agent 的功能
   model: null
   tool_groups:
     - file:read
     - file:write
   subagent_enabled: false
   ```

4. **如需作为子 Agent 被调用**，在 `config.yaml` 的 `subagents.custom_agents` 中添加定义

5. **重启服务**使配置生效

### 3.6 world-updater Agent（规划工作流专用）

**用途**：规划工作流（plan）内部调用，根据新写或新修改的细纲/卷纲，自动更新世界观文件。

**目录结构**：
```
backend/.deer-flow/agents/world-updater/
├── SOUL.md          # Agent 人格/指令提示词
└── config.yaml      # Agent 运行配置
```

**config.yaml**：
```yaml
name: world-updater
description: |
  世界观更新员，负责根据新写或新修改的细纲/卷纲，更新指定的世界观文件，确保世界观与最新规划保持一致。
model: inherit
tool_groups:
  - file:read
  - file:write
max_turns: 60
timeout_seconds: 600
```

**特点**：
- 由 `plan` 工作流自动调用，**不直接由主 Agent 调用**
- 每次只更新一个世界观文件（并行/串行由工作流控制）
- 入参：细纲/卷纲路径 + 目标世界观文件路径
- 工具组：系统自带的 `file:read` + `file:write`

**SOUL.md 核心要求**：
1. 读取指定的细纲/卷纲文件，理解最新规划中的世界观变更
2. 读取目标世界观文件，了解当前内容
3. 只更新与规划变更相关的内容，保留其他已有内容不变
4. 将更新后的完整文件内容写入目标文件路径
5. 不得输出英文单双引号，必须使用中文 "" ''

**注册方式**（无需在 `subagents.custom_agents` 中定义）：
- 只需在 `backend/.deer-flow/agents/` 下创建 `world-updater/` 目录
- 放入 `SOUL.md` 和 `config.yaml`
- 服务启动时会自动扫描并注册
- 如需覆盖超时配置，在 `config.yaml` 的 `subagents.agents` 中添加：
  ```yaml
  subagents:
    agents:
      world-updater:
        timeout_seconds: 600
        max_turns: 60
  ```

---

## 四、配置 Skill（技能）

### 4.1 Skill 注册

Skill 在 `config.yaml` 中配置目录：

```yaml
skills:
  path: skills                    # 相对于项目根目录的路径
  container_path: /mnt/skills     # 沙箱内的路径
```

### 4.2 在 Agent 中使用

在 Agent 的 `config.yaml` 中声明要使用的技能：

```yaml
skills:
  - novel-post-write-validator
  - novel-anti-ai-detector
  - novel-plan-compliance
```

### 4.3 Skill 目录结构

每个 Skill 是一个独立的目录，包含：

```
skills/novel-post-write-validator/
├── SKILL.md          # 技能描述和使用说明
├── prompt.md         # 技能提示词
└── ...               # 其他相关文件
```

---

## 五、工具 / 技能 / Agent 的关系

```
Agent (novel-master)
├── 使用 tool_groups → 获得一组工具
│   ├── file:read     → read_file, glob, grep
│   ├── master:write  → master_writer（受限白名单：创建目录 + 写入 03-状态）
│   └── novel:tools   → context_assembler, card_validator, ...
│
├── 使用 skills      → 加载技能提示词
│   ├── novel-post-write-validator
│   └── novel-anti-ai-detector
│
└── 调用子 Agent     → 通过 task 工具委派任务
    ├── novel-writer        （有 file:write，可写正文）
    ├── novel-architect
    └── continuity-auditor
```

**区别**：

| 概念 | 本质 | 用途 | 执行方式 |
|------|------|------|----------|
| **Tool** | Python 函数 | 执行具体操作（读写文件、验证格式等） | Agent 直接调用 |
| **受限白名单Tool** | Python 函数（带路径验证） | 限制 Agent 只能操作特定文件（如 master_writer） | Agent 直接调用，白名单拦截 |
| **Skill** | 提示词模板 | 增强 Agent 的特定能力 | 自动加载到上下文 |
| **Agent** | 独立 LLM 会话 | 执行复杂任务（写正文、审核等） | 通过 task 工具委派 |

---

## 六、常用配置示例

### 6.1 给 Agent 添加新工具

1. 在 `my_tools/` 下创建工具文件
2. 在 `config.yaml` 的 `tools` 段注册
3. 确保工具所属的 `tool_group` 已声明
4. Agent 的 `config.yaml` 中引用该工具组

### 6.2 修改子 Agent 超时

```yaml
subagents:
  agents:
    my-agent:
      timeout_seconds: 3600    # 改为 1 小时
      max_turns: 100           # 改为 100 轮
```

### 6.3 创建新的工具组

```yaml
tool_groups:
  - name: my:custom-group    # 新增工具组（建议使用冒号分隔的命名风格）

tools:
  - name: my-tool
    group: my:custom-group   # 归入新工具组
    use: my_tools.my_module:my_function
```

然后在 Agent 配置中引用：

```yaml
tool_groups:
  - file:read
  - my:custom-group          # 引用新工具组
```

---

## 七、调试技巧

### 7.1 验证工具是否注册

检查 `config.yaml` 中 `tools` 段是否有对应条目。

### 7.2 验证 Agent 是否能使用工具

检查 Agent 的 `config.yaml` 中 `tool_groups` 是否包含该工具所属的组。

### 7.3 查看 Agent 提示词

直接读取 `backend/.deer-flow/agents/<agent-name>/SOUL.md`。

### 7.4 重启服务

修改配置后需要重启服务：
```bash
make dev
```
