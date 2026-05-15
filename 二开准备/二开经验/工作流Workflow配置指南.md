# 工作流 (Workflow) 配置指南

本文档说明如何在 DeerFlow 二开项目中配置和使用工作流。

---

## 一、工作流是什么

工作流是**确定性的任务编排**，使用 LangGraph StateGraph 构建，不依赖 LLM 决策，保证流程完整执行。

### 1.1 与 Agent/Skill 的区别

| 概念 | 本质 | 决策方式 | 调用方式 |
|------|------|----------|----------|
| **Agent** | 独立 LLM 会话 | LLM 自主决策 | `task` 工具调用 |
| **Skill** | 提示词模板 | 无决策，自动注入上下文 | `Skill` 工具加载 |
| **Workflow** | 确定性编排 | 代码预定义，无 LLM 决策 | `workflow` 工具调用 |

### 1.2 为什么需要工作流

**问题**：主 Agent 通过 SOUL.md 提示词控制流程顺序，但 LLM 决策存在不确定性，经常遗漏步骤。

**解决**：将固定流程编码为工作流，由代码保证步骤顺序，主 Agent 只需一次工具调用即可触发整个流程。

---

## 二、工作流架构

### 2.1 文件结构

```
backend/packages/harness/deerflow/workflows/
├── __init__.py           # 模块入口，注册工作流
├── states.py             # 状态类型定义
├── registry.py           # 工作流注册表
├── executor.py           # 工作流执行引擎
├── helpers.py            # 辅助函数（调用子Agent）
├── novel_organize.py     # 整理工作流
├── novel_plan.py         # 规划工作流
├── novel_post_process.py # 后处理工作流
└── novel_writing.py      # 写作工作流
```

### 2.2 核心组件

| 组件 | 文件 | 作用 |
|------|------|------|
| `NovelWorkflowState` | states.py | 定义工作流状态类型 |
| `register_workflow` | registry.py | 注册工作流到注册表 |
| `WorkflowExecutor` | executor.py | 执行工作流 |
| `call_subagent` | helpers.py | 调用子 Agent |

---

## 三、内置工作流

### 3.1 整理工作流 (organize)

**流程**：
```
confirm_chapter → create_task_folder → [检查文件] → organize_world ──┐
                                         ↓ [文件存在则跳过]        → organize_characters ─┼→ assemble_context
                                                                  → organize_items ─────┘
                                                                  → organize_storyline ─┘
```

**节点说明**：

| 节点 | 功能 | 调用的子Agent | 输出文件 |
|------|------|---------------|----------|
| confirm_chapter | 确认章节号和章节组 | 无（纯代码） | - |
| create_task_folder | 创建 _task/ 目录 | 无（纯代码） | - |
| organize_world | 整理世界观 | novel-world-organizer | 世界观参考.md |
| organize_characters | 整理人物 | novel-character-organizer | 人物参考.md |
| organize_items | 整理道具 | novel-item-organizer | 道具参考.md |
| organize_storyline | 整理故事线 | novel-storyline-organizer | 故事线参考.md |
| assemble_context | 汇总写作任务 | 无（纯代码） | 写作任务汇总.md |

**文件检查机制**：

工作流在调用每个 organize agent 前会检查对应的参考文件是否已存在：
- 如果文件已存在，跳过该 agent 的调用（节省 LLM 调用）
- 如果文件不存在，正常调用 agent 生成文件
- 最后的 `assemble_context`（合并）**始终会重新执行**，确保汇总文件是最新的

**检查逻辑**：
```
_task/世界观参考.md 存在 → 跳过 organize_world
_task/人物参考.md 存在 → 跳过 organize_characters
_task/道具参考.md 存在 → 跳过 organize_items
_task/故事线参考.md 存在 → 跳过 organize_storyline
```

**调用示例**：
```
调用 workflow 工具：
- workflow_name: "organize"
- params: {"novel_name": "都市逍遥仙", "chapter_num": 6, "chapter_group": "06-10"}
- description: "整理第6章参考信息"
```

### 3.2 写作工作流 (writing)

**流程**：
```
check_task_summary → [通过] → write_chapter → audit → [AUDIT_RESULT: PASS] → post_process → sync_outline
                   → [失败] → END（返回错误信息给主Agent）
                                                          → [AUDIT_RESULT: FAIL] → revise → audit (最多2次)
```

**节点说明**：

| 节点 | 功能 | 调用的子Agent |
|------|------|---------------|
| check_task_summary | 检查写作任务汇总是否已生成 | 无（纯逻辑检查） |
| write_chapter | 写章节正文 | novel-writer |
| audit | 审核章节 | continuity-auditor |
| revise | 修改章节 | novel-reviser |
| post_process | 后处理（摘要+状态+伏笔+名片） | chapter-summarizer, state-settler, hook-manager, card-manager |
| sync_outline | 同步细纲 | outline-planner |

**check_task_summary 说明**：
- 工作流入口节点，首先检查 `_task/写作任务汇总.md` 是否存在
- 如果 state 中已有 `writing_task_summary` 内容（通过参数注入），则跳过文件检查
- 如果文件不存在，工作流直接终止，返回错误信息给主 Agent
- 错误信息格式：`工作流运行失败，未检测到 {目录结构}/写作任务汇总.md 文件，请运行整理工作流重新生成`

**审核判断机制**：

工作流要求 `continuity-auditor` 在报告末尾输出结构化标记：
- `[AUDIT_RESULT: PASS]` - 审核通过
- `[AUDIT_RESULT: FAIL]` - 审核不通过

脚本用正则解析标记，不依赖关键词匹配。找不到标记时默认为 FAIL（安全降级）。

**调用示例**：
```
调用 workflow 工具：
- workflow_name: "writing"
- params: {"novel_name": "都市逍遥仙", "chapter_num": 6, "chapter_group": "06-10", "writing_task_summary": "book/都市逍遥仙/02-正文/第6-10章/_task/写作任务汇总.md"}
- description: "写第6章"
```

### 3.3 规划工作流 (plan)

**流程**：
```
call_planner ──→ [outline-planner / volume-planner] ──→ scan_world_files ──→ update_world_files ──→ END
             │                                            (并行/串行调用 world-updater)
             │
             └─→ [book-rules-manager] ──→ END (不更新世界观)
             
             └─→ [规划失败] ──→ END (返回错误)
```

**节点说明**：

| 节点 | 功能 | 调用的子Agent |
|------|------|---------------|
| call_planner | 调用指定的规划Agent完成规划任务 | outline-planner / volume-planner / book-rules-manager |
| scan_world_files | 扫描 `00-世界观/` 目录下所有 `.md` 文件 | 无（纯代码） |
| update_world_files | 对每个世界观文件调用 `world-updater` 更新内容 | world-updater（并行或串行） |

**路由判断机制**：

`_should_update_world` 函数根据 planner_name 决定后续流程：
- `outline-planner` / `volume-planner` → 进入 `scan_world_files` → 更新世界观
- `book-rules-manager` → 直接 END（不触发世界观更新）
- 规划失败（errors 中存在 failed）→ 直接 END（返回错误）

**并行/串行执行**：

由 `workflow_parallel_enabled` 配置控制：
- `true`：并行调用多个 `world-updater`（适合线上模型）
- `false`：串行逐个调用（适合本地模型）

**调用示例**：
```
# 新建细纲（会触发世界观更新）
调用 workflow 工具：
- workflow_name: "plan"
- params: {"planner_name": "outline-planner", "planner_mode": "new", "chapter_group": "第1-5章", "planner_task": "前5章的细纲"}
- description: "新建第1-5章细纲"

# 修改卷纲（会触发世界观更新）
调用 workflow 工具：
- workflow_name: "plan"
- params: {"planner_name": "volume-planner", "planner_mode": "revise", "planner_task": "第二卷增加一个转折"}
- description: "修改卷纲"

# 修改规则（不会触发世界观更新）
调用 workflow 工具：
- workflow_name: "plan"
- params: {"planner_name": "book-rules-manager", "planner_task": "增加禁用词列表"}
- description: "修改本书规则"
```

**日志输出**：

规划工作流使用 `[PLAN_WORKFLOW]` 前缀输出日志，关键节点都有 START/END 标记：
```
[PLAN_WORKFLOW] ====== call_planner START ======
[PLAN_WORKFLOW] planner_name=outline-planner, planner_mode=new, novel_name=都市逍遥仙
[PLAN_WORKFLOW] Calling subagent outline-planner (model=mimo-v2-omni)
[PLAN_WORKFLOW] Subagent outline-planner completed successfully
[PLAN_WORKFLOW] ====== call_planner END (success) ======
[PLAN_WORKFLOW] _should_update_world: planner_name=outline-planner, errors_count=0
[PLAN_WORKFLOW] Planner outline-planner requires world update, route to scan_world_files
[PLAN_WORKFLOW] ====== scan_world_files START ======
[PLAN_WORKFLOW] Found 6 world files to update:
[PLAN_WORKFLOW]   [1] 故事圣经.md
[PLAN_WORKFLOW]   [2] 角色矩阵.md
[PLAN_WORKFLOW]   [3] 情感弧线.md
[PLAN_WORKFLOW]   [4] 支线板.md
[PLAN_WORKFLOW]   [5] 当前状态卡.md
[PLAN_WORKFLOW]   [6] 待办事项.md
[PLAN_WORKFLOW] ====== update_world_files START ======
[PLAN_WORKFLOW] Total world files to update: 6
[PLAN_WORKFLOW] Parallel execution enabled
[PLAN_WORKFLOW] [1/6] SUCCESS 故事圣经.md
[PLAN_WORKFLOW] [2/6] SUCCESS 角色矩阵.md
...
[PLAN_WORKFLOW] Parallel update complete: success=6/6, errors=0
```

---

## 四、全局变量替换

### 4.1 问题背景

子 Agent 的 `system_prompt`（来自 config.yaml 的 `custom_agents`）中可能包含 `{{workdir}}`、`{{novel_toc}}` 等全局变量。

**原有问题**：子 Agent 的中间件链 `build_subagent_runtime_middlewares()` 不包含 `GlobalVariablesMiddleware`，导致变量不被替换。

**修复方案**：在 `build_subagent_runtime_middlewares()` 中加入 `GlobalVariablesMiddleware`。

### 4.2 替换机制

全局变量替换在两个位置发生：

| 位置 | 触发时机 | 作用对象 |
|------|----------|----------|
| `assemble_from_features` | Agent 创建时 | 主 Agent 的 SOUL.md |
| `build_subagent_runtime_middlewares` | 子 Agent 创建时 | 子 Agent 的 system_prompt |

替换使用 `replace_template_variables()` 函数，正则匹配 `{{变量名}}` 并替换为实际值。

### 4.3 变量来源

| 来源 | 说明 |
|------|------|
| 系统内置 | `workdir`、`novel_dir_structure` 等硬编码变量 |
| 数据库 | 用户通过 API 或 LLM 工具设置的变量 |
| 合并策略 | thread 级别 > project 级别 > 系统内置 |

---

## 五、如何新增工作流

### 5.1 创建工作流文件

在 `backend/packages/harness/deerflow/workflows/` 下创建新文件：

```python
# my_workflow.py
from langgraph.graph import StateGraph, END
from deerflow.workflows.registry import register_workflow
from deerflow.workflows.states import NovelWorkflowState

def my_node(state: NovelWorkflowState) -> dict:
    # 节点逻辑
    return {"key": "value"}

def create_my_workflow() -> StateGraph:
    workflow = StateGraph(NovelWorkflowState)
    workflow.add_node("my_node", my_node)
    workflow.set_entry_point("my_node")
    workflow.add_edge("my_node", END)
    return workflow.compile()

register_workflow("my_workflow", create_my_workflow)
```

### 5.2 注册工作流

在 `__init__.py` 中导入新模块：

```python
from deerflow.workflows import my_workflow
```

### 5.3 在 SOUL.md 中使用

```
调用 workflow 工具：
- workflow_name: "my_workflow"
- params: {"novel_name": "xxx", "chapter_num": 1}
- description: "执行自定义工作流"
```

---

## 六、调试技巧

### 6.1 验证工作流是否注册

```python
from deerflow.workflows import list_workflows
print(list_workflows())  # 应包含 'organize', 'plan', 'post_process', 'writing'
```

### 6.2 验证子 Agent 全局变量替换

检查 `build_subagent_runtime_middlewares()` 返回的中间件列表是否包含 `GlobalVariablesMiddleware`。

### 6.3 查看工作流执行日志

工作流节点执行时会输出日志，格式为：
```
Organize workflow: confirm chapter 6 for 都市逍遥仙
Writing workflow: writing chapter 6
Writing workflow: auditing chapter 6
Audit result for chapter 6: PASS
```
