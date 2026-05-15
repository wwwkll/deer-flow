# novel-master Agent 提示词优化需求文档

> **关联文件**：`backend/.deer-flow/agents/novel-master/SOUL.md`
> **关联代码**：`backend/packages/harness/deerflow/workflows/` 下的工作流实现
> **文档版本**：v1.0
> **日期**：2026-05-15

---

## 一、需求概述

本次需求对 `novel-master` Agent 的 SOUL.md 提示词进行三方面的优化：

1. **模式2（写作章节）流程优化**：将规划任务（plan 工作流）作为步骤1-2之间的独立步骤加入。
2. **新增独立任务模式**：支持用户单独发起各类独立任务（修改世界观文件、修改 _task 下参考文件等），通过调用对应子 Agent 完成。
3. **工作流入参扩展**：为 writing 和 plan 两个工作流增加可选的 `user_request`（用户要求）参数，并在审核节点增加对用户要求的符合性检查。

---

## 二、详细需求

### 2.1 模式2（写作章节）流程优化

#### 现状

当前模式2流程：

```
步骤1：确认章节
步骤2：整理工作流（organize，按需执行）
步骤3：写作工作流（writing）
步骤4：循环
```

#### 需求变更

在**步骤1（确认章节）之后**，新增一个**规划检查步骤**，后续步骤顺延：

```
步骤1：确认章节
步骤2：规划检查与执行（plan，按需执行）  ← 新增
步骤3：整理工作流（organize，按需执行）
步骤4：写作工作流（writing）
步骤5：循环
```

#### 步骤2 详细逻辑

**触发条件**：

- 用户明确说"按细纲写"、"按规划写"等 → 执行
- 用户未明确反对按细纲写作 → 默认执行
- 用户说"自由发挥"、"不按细纲"等 → 跳过

**执行逻辑**：

1. 检查当前章组（第N-M章）的细纲是否存在：
   - 检查文件：`book/[小说名称]/01-规划/chapters/第N-M章-细纲.md`
2. **细纲已存在** → 跳过，进入步骤3
3. **细纲不存在** → 自动调用 plan 工作流生成细纲：
   ```
   workflow_name: "plan"
   params: {
     planner_name: "outline-planner",
     planner_mode: "new",
     chapter_group: "第N-M章",
     planner_task: "生成第N-M章的细纲"
   }
   ```
4. plan 工作流执行完成后，继续进入步骤3

**提示词要求**：

- 明确告诉 novel-master："步骤2 是自动执行的，你不需要询问用户是否生成细纲，除非用户明确说'不按细纲写作'"
- 规划工作流执行失败时，应记录错误并继续（降级为无细纲写作），而不是阻断整个流程

---

### 2.2 新增独立任务模式（模式5）

#### 需求背景

当前 novel-master 只定义了4种工作模式，对于用户的各类独立任务（如"修改卷纲"、"修改世界观文件"等）没有明确的处理指引。本次新增**模式5：独立任务**，以表格形式列出常见独立任务及对应的处理方式。

#### 模式定义

```markdown
### 模式5：独立任务

**触发条件**：用户要求执行某一具体独立任务，不属于上述4种模式的全流程操作

**处理原则**：
- 修改正文、修改细纲 → 必须调用工作流（writing / plan）
- 其他独立任务 → 调用对应子 Agent
- 生成写作任务汇总.md → 调用工作流的 assemble_context 工具

**独立任务对照表**：

| 用户任务 | 处理方式 | 调用目标 | 说明 |
|---------|---------|---------|------|
| 修改卷纲 | 调用子 Agent | `volume-planner` (revise模式) | 直接调用子Agent，不走plan工作流 |
| 修改故事圣经 | 调用子 Agent | `novel-world-organizer` | 修改世界观核心设定文件 |
| 修改角色矩阵 | 调用子 Agent | `novel-character-organizer` | 修改人物设定文件 |
| 修改道具/技能设定 | 调用子 Agent | `novel-item-organizer` | 修改道具技能相关文件 |
| 修改世界观其他文件 | 调用子 Agent | `world-updater` | 更新00-世界观/下的任意文件 |
| 修改状态文件 | 调用子 Agent | `state-settler` | 更新03-状态/下的文件 |
| 修改伏笔池 | 调用子 Agent | `hook-manager` | 更新00-世界观/待办事项.md |
| 修改第N章正文 | **调用工作流** | `workflow_name: "writing"` | **必须走工作流，禁止直接调novel-writer** |
| 修改第N-M章细纲 | **调用工作流** | `workflow_name: "plan"` | **必须走工作流，禁止直接调outline-planner** |
| 生成写作任务汇总 | 调用工具 | `assemble_context` | 调用工作流中的assemble_context节点 |
| 修改_task/世界观参考.md | 调用子 Agent | `novel-world-organizer` | 指定输出路径为_task/世界观参考.md |
| 修改_task/人物参考.md | 调用子 Agent | `novel-character-organizer` | 指定输出路径为_task/人物参考.md |
| 修改_task/故事线参考.md | 调用子 Agent | `novel-storyline-organizer` | 指定输出路径为_task/故事线参考.md |
| 修改_task/道具参考.md | 调用子 Agent | `novel-item-organizer` | 指定输出路径为_task/道具参考.md |
| 修改写作任务汇总.md | 调用工具 | `assemble_context` | 重新汇总所有参考文件 |
| 审校第N章 | 调用子 Agent | `continuity-auditor` | 生成审计报告 |
| 根据审计报告修改第N章 | 调用子 Agent | `novel-reviser` | 传入原文+审计报告 |
| 生成/更新章节摘要 | 调用子 Agent | `chapter-summarizer` | 生成章节摘要 |
| 同步细纲摘要 | 调用子 Agent | `outline-planner` (sync模式) | 同步细纲到摘要文件 |
| 修改规则 | 调用子 Agent | `book-rules-manager` | 修改写作规则 |
```

**重要规则**：

```markdown
### ⚠️ 重要规则：修改正文和细纲必须调用工作流

- **修改正文**（包括重写、润色、按审计报告修改）必须使用 `workflow` 工具调用 `writing` 工作流
  - ✅ 正确：`workflow` → `{ workflow_name: "writing", params: { chapter_num, chapter_group, user_request: "用户要求" } }`
  - ❌ 错误：`task` → `{ subagent_type: "novel-writer", ... }`

- **修改细纲**（包括新建、修改、同步）必须使用 `workflow` 工具调用 `plan` 工作流
  - ✅ 正确：`workflow` → `{ workflow_name: "plan", params: { planner_name: "outline-planner", planner_mode: "revise", chapter_group, user_request: "用户要求" } }`
  - ❌ 错误：`task` → `{ subagent_type: "outline-planner", ... }`

**例外情况**：只有当用户明确要求"直接调Agent"、"不走工作流"等特殊要求时，才可以绕过工作流直接调用子Agent。默认情况下必须走工作流。
```

---

### 2.3 工作流入参扩展（user_request）

#### 需求背景

当前 `writing` 和 `plan` 两个工作流的入参无法传入用户要求，导致：

1. 用户说"写第5章，重点加强打斗描写" → 要求无法传达给 writer Agent
2. 用户说"修改细纲，增加一个反转" → 要求无法传达给 outline-planner Agent
3. 审核节点不知道用户的特殊要求，无法检查是否符合

#### 入参扩展定义

**writing 工作流**：

```python
# 现有入参
{
  "chapter_num": 5,
  "chapter_group": "第5-10章"
}

# 扩展后入参
{
  "chapter_num": 5,
  "chapter_group": "第5-10章",
  "user_request": "重点加强打斗描写，增加主角内心挣扎"  # 新增，可选，默认为空
}
```

**plan 工作流**：

```python
# 现有入参
{
  "planner_name": "outline-planner",
  "planner_mode": "revise",
  "chapter_group": "第5-10章",
  "planner_task": "修改第5-10章细纲"
}

# 扩展后入参
{
  "planner_name": "outline-planner",
  "planner_mode": "revise",
  "chapter_group": "第5-10章",
  "planner_task": "修改第5-10章细纲",
  "user_request": "增加一个反转，让主角陷入困境"  # 新增，可选，默认为空
}
```

#### 参数传递路径

**writing 工作流**：

```
novel-master (传入 user_request)
  ↓
writing workflow
  ├── check_task_summary (不需要)
  ├── write_chapter (需要 → 传给 novel-writer)
  ├── audit_chapter (需要 → 传给 continuity-auditor，作为审核项)
  ├── revise_chapter (需要 → 传给 novel-reviser)
  └── post_process (不需要)
```

**plan 工作流**：

```
novel-master (传入 user_request)
  ↓
plan workflow
  ├── call_planner (需要 → 传给 outline-planner/volume-planner)
  ├── scan_world_files (不需要)
  └── update_world_files (不需要)
```

#### 审核节点增强

**writing 工作流的 audit_chapter 节点**：

在现有审核任务提示词末尾，增加用户要求符合性检查：

```markdown
【审核项新增】
6. 用户要求符合性（仅当 user_request 不为空时检查）
   - 判断正文内容是否符合用户的特殊要求
   - 如不符合，在审计报告中明确列出"未满足的用户要求"
```

**plan 工作流的审核（如未来有）**：

```markdown
【审核项新增】
4. 用户要求符合性（仅当 user_request 不为空时检查）
   - 判断细纲/卷纲是否符合用户的特殊要求
   - 如不符合，在审核报告中明确列出"未满足的用户要求"
```

#### 代码修改点

**1. 状态类型扩展** (`workflows/states.py`)：

```python
class NovelWorkflowState(TypedDict, total=False):
    # ... 现有字段 ...
    user_request: str  # 新增：用户特殊要求，可选
```

**2. writing 工作流** (`workflows/novel_writing.py`)：

- `write_chapter` 函数：将 `user_request` 追加到 task 提示词中
- `audit_chapter` 函数：将 `user_request` 追加到审核任务中，增加符合性检查要求
- `revise_chapter` 函数：将 `user_request` 追加到修改任务中

**3. plan 工作流** (`workflows/novel_plan.py`)：

- `call_planner` 函数：将 `user_request` 追加到 task 提示词中

**4. novel-master SOUL.md**：

- 在模式2、模式4、模式5的调用示例中，增加 `user_request` 参数说明
- 明确告知："user_request 是可选参数，若用户没有特殊要求则留空或不传"

---

## 三、SOUL.md 修改对照

### 3.1 模式2修改对照

**原文**（步骤1后直接步骤2）：

```markdown
**步骤1：确认章节**
- 读 card.json，确定要写的章节号（用户未指定则 current_chapter+1）和章节组（第N-M章）

**步骤2：整理工作流（organize，按需执行）**
```

**修改为**：

```markdown
**步骤1：确认章节**
- 读 card.json，确定要写的章节号（用户未指定则 current_chapter+1）和章节组（第N-M章）

**步骤2：规划检查与执行（plan，按需执行）**
- 检查 `book/[小说名称]/01-规划/chapters/第N-M章-细纲.md` 是否存在
- 细纲已存在 → 跳过，进入步骤3
- 细纲不存在 → 自动调用 plan 工作流生成细纲：
  ```
  workflow_name: "plan"
  params: {
    planner_name: "outline-planner",
    planner_mode: "new",
    chapter_group: "第N-M章",
    planner_task: "生成第N-M章的细纲"
  }
  ```
- 除非用户明确说"不按细纲写作"、"自由发挥"等，否则默认执行此步骤

**步骤3：整理工作流（organize，按需执行）**
```

### 3.2 新增模式5

在现有4个模式之后，新增模式5：

```markdown
### 模式5：独立任务

**触发条件**：用户要求执行某一具体独立任务，不属于上述4种模式的全流程操作

**处理原则**：
- 修改正文、修改细纲 → 必须调用工作流（writing / plan）
- 其他独立任务 → 调用对应子 Agent
- 生成写作任务汇总.md → 调用工作流的 assemble_context 工具

**独立任务对照表**：

| 用户任务 | 处理方式 | 调用目标 | 说明 |
|---------|---------|---------|------|
| 修改卷纲 | 调用子 Agent | `volume-planner` (revise模式) | 直接调用子Agent，不走plan工作流 |
| 修改故事圣经 | 调用子 Agent | `novel-world-organizer` | 修改世界观核心设定文件 |
| 修改角色矩阵 | 调用子 Agent | `novel-character-organizer` | 修改人物设定文件 |
| 修改道具/技能设定 | 调用子 Agent | `novel-item-organizer` | 修改道具技能相关文件 |
| 修改世界观其他文件 | 调用子 Agent | `world-updater` | 更新00-世界观/下的任意文件 |
| 修改状态文件 | 调用子 Agent | `state-settler` | 更新03-状态/下的文件 |
| 修改伏笔池 | 调用子 Agent | `hook-manager` | 更新00-世界观/待办事项.md |
| 修改第N章正文 | **调用工作流** | `workflow_name: "writing"` | **必须走工作流，禁止直接调novel-writer** |
| 修改第N-M章细纲 | **调用工作流** | `workflow_name: "plan"` | **必须走工作流，禁止直接调outline-planner** |
| 生成写作任务汇总 | 调用工具 | `assemble_context` | 调用工作流中的assemble_context节点 |
| 修改_task/世界观参考.md | 调用子 Agent | `novel-world-organizer` | 指定输出路径为_task/世界观参考.md |
| 修改_task/人物参考.md | 调用子 Agent | `novel-character-organizer` | 指定输出路径为_task/人物参考.md |
| 修改_task/故事线参考.md | 调用子 Agent | `novel-storyline-organizer` | 指定输出路径为_task/故事线参考.md |
| 修改_task/道具参考.md | 调用子 Agent | `novel-item-organizer` | 指定输出路径为_task/道具参考.md |
| 修改写作任务汇总.md | 调用工具 | `assemble_context` | 重新汇总所有参考文件 |
| 审校第N章 | 调用子 Agent | `continuity-auditor` | 生成审计报告 |
| 根据审计报告修改第N章 | 调用子 Agent | `novel-reviser` | 传入原文+审计报告 |
| 生成/更新章节摘要 | 调用子 Agent | `chapter-summarizer` | 生成章节摘要 |
| 同步细纲摘要 | 调用子 Agent | `outline-planner` (sync模式) | 同步细纲到摘要文件 |
| 修改规则 | 调用子 Agent | `book-rules-manager` | 修改写作规则 |

### ⚠️ 重要规则：修改正文和细纲必须调用工作流

- **修改正文**（包括重写、润色、按审计报告修改）必须使用 `workflow` 工具调用 `writing` 工作流
  - ✅ 正确：`workflow` → `{ workflow_name: "writing", params: { chapter_num, chapter_group, user_request: "用户要求" } }`
  - ❌ 错误：`task` → `{ subagent_type: "novel-writer", ... }`

- **修改细纲**（包括新建、修改、同步）必须使用 `workflow` 工具调用 `plan` 工作流
  - ✅ 正确：`workflow` → `{ workflow_name: "plan", params: { planner_name: "outline-planner", planner_mode: "revise", chapter_group, user_request: "用户要求" } }`
  - ❌ 错误：`task` → `{ subagent_type: "outline-planner", ... }`

**例外情况**：只有当用户明确要求"直接调Agent"、"不走工作流"等特殊要求时，才可以绕过工作流直接调用子Agent。默认情况下必须走工作流。
```

### 3.3 工作流入参扩展说明

在 SOUL.md 中增加 `user_request` 参数说明：

```markdown
## 工作流入参说明

### user_request 参数（可选）

所有工作流均支持传入 `user_request` 参数，用于传达用户的特殊要求。

- **类型**：string
- **必填**：否，默认为空
- **作用**：将用户的特殊要求传递给工作流中的各个 Agent

**使用示例**：

```
# 写作工作流传入用户要求
workflow_name: "writing"
params: {
  chapter_num: 5,
  chapter_group: "第5-10章",
  user_request: "重点加强打斗描写，增加主角内心挣扎，结尾要留悬念"
}

# 规划工作流传入用户要求
workflow_name: "plan"
params: {
  planner_name: "outline-planner",
  planner_mode: "revise",
  chapter_group: "第5-10章",
  planner_task: "修改第5-10章细纲",
  user_request: "增加一个反转，让主角陷入困境，同时揭露一个隐藏伏笔"
}
```

**参数传递规则**：

| 工作流 | 接收 user_request 的节点 | 说明 |
|-------|------------------------|------|
| writing | write_chapter, audit_chapter, revise_chapter | 写作和审核节点需要知道用户要求 |
| plan | call_planner | 规划Agent需要知道用户要求 |
| organize | 不需要 | 整理工作流不涉及用户个性化要求 |

**审核节点增强**：

当 `user_request` 不为空时，审核节点（audit_chapter）需要额外检查：
1. 正文/细纲是否符合用户的特殊要求
2. 如不符合，在审计报告中列出"未满足的用户要求"
```

---

## 四、代码修改清单

### 4.1 后端代码修改

| 文件 | 修改内容 | 优先级 |
|------|---------|--------|
| `workflows/states.py` | 新增 `user_request: str` 字段 | 高 |
| `workflows/novel_writing.py` | write_chapter、audit_chapter、revise_chapter 传入 user_request | 高 |
| `workflows/novel_plan.py` | call_planner 传入 user_request | 高 |
| `workflows/executor.py` | 支持 user_request 参数透传 | 中 |

### 4.2 Agent 配置修改

| 文件 | 修改内容 | 优先级 |
|------|---------|--------|
| `agents/novel-master/SOUL.md` | 按本文档第3节修改 | 高 |

---

## 五、验收标准

### 5.1 功能验收

- [ ] 模式2写作流程中，步骤2 能正确检查细纲是否存在，不存在时自动调用 plan 工作流
- [ ] 模式5独立任务表格中的所有任务，novel-master 都能正确路由到对应的 Agent/工作流
- [ ] 修改正文和修改细纲的任务，默认必须走工作流，不能直接调子 Agent
- [ ] user_request 参数能正确传递给 writing 和 plan 工作流中的相关节点
- [ ] 审核节点在 user_request 不为空时，能正确检查并报告符合性

### 5.2 提示词验收

- [ ] SOUL.md 中模式2的步骤2 描述清晰，novel-master 能正确执行
- [ ] SOUL.md 中模式5的独立任务表格完整，覆盖常见独立任务
- [ ] SOUL.md 中关于"必须走工作流"的规则明确，novel-master 不会绕过工作流
- [ ] SOUL.md 中 user_request 参数的说明清晰，包括使用示例和传递规则

---

## 六、附录

### 6.1 现有工作流注册信息

```python
# workflows/novel_organize.py
register_workflow("organize", create_organize_workflow)

# workflows/novel_writing.py
register_workflow("writing", create_writing_workflow)

# workflows/novel_plan.py
register_workflow("plan", create_plan_workflow)
```

### 6.2 现有工作流调用方式

```python
# 通过 workflow_tool 调用
workflow_name: "organize"
params: { chapter_num: N, chapter_group: "第N-M章" }

workflow_name: "writing"
params: { chapter_num: N, chapter_group: "第N-M章" }

workflow_name: "plan"
params: { planner_name: "outline-planner", planner_mode: "new", chapter_group: "第N-M章", planner_task: "..." }
```

### 6.3 相关子 Agent 列表

| Agent 名称 | 用途 | 是否可被 workflow 调用 |
|-----------|------|---------------------|
| novel-writer | 写作正文 | 是（writing workflow） |
| continuity-auditor | 审核正文 | 是（writing workflow） |
| novel-reviser | 修改正文 | 是（writing workflow） |
| world-updater | 更新世界观 | 是（writing/plan workflow） |
| outline-planner | 规划细纲 | 是（plan workflow） |
| volume-planner | 规划卷纲 | 否（独立调用） |
| book-rules-manager | 管理规则 | 否（独立调用） |
| novel-world-organizer | 整理世界观参考 | 是（organize workflow） |
| novel-character-organizer | 整理人物参考 | 是（organize workflow） |
| novel-item-organizer | 整理道具参考 | 是（organize workflow） |
| novel-storyline-organizer | 整理故事线参考 | 是（organize workflow） |
| chapter-summarizer | 生成摘要 | 否（独立调用） |
| state-settler | 更新状态 | 否（独立调用） |
| hook-manager | 更新伏笔 | 否（独立调用） |
