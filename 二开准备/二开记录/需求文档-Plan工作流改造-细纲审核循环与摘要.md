# 需求文档：Plan 工作流改造 — 细纲审核循环 + 细纲摘要

**日期**: 2026-05-14
**版本**: v1.0
**状态**: 待审核

---

## 一、需求概述

对现有的 `plan` 工作流进行改造，主要包含以下变更：

1. **移除世界观自动更新**：去掉 plan 工作流中 `scan_world_files` → `update_world_files` 的世界观并发更新流程
2. **增加细纲审核循环**：参考 `writing` 工作流的审核机制，为细纲增加最多 2 轮的审核-修改循环
3. **新增 2 个 Agent**：细纲审核师（outline-auditor）、细纲修改师（outline-reviser）
4. **新增细纲摘要文档**：在 `00-世界观/` 下增加 `细纲摘要.md`，由新增的细纲摘要维护 Agent（outline-summarizer）负责更新
5. **同步更新所有相关 Agent 提示词和目录结构**

---

## 二、现有 Plan 工作流分析

### 2.1 当前流程

```
call_planner ──→ _route_after_planner ──→ scan_world_files ──→ update_world_files ──→ END
                    │
                    ├── "end_no_update" ──→ END (book-rules-manager)
                    └── "end_with_error" ──→ END (planner 失败)
```

### 2.2 当前问题

1. **世界观并发更新不可控**：world-updater 并发执行时，多个 Agent 同时读写同一世界观文件，容易产生冲突
2. **细纲无质量把关**：outline-planner 输出细纲后直接结束，没有审核环节，细纲质量完全依赖 LLM 的一次性输出
3. **缺少细纲摘要**：后续 Agent（如 writer、auditor）需要读取完整细纲才能了解剧情走向，缺少简洁的摘要参考

---

## 三、改造后 Plan 工作流设计

### 3.1 新流程

```
call_planner ──→ audit_outline ──→ [AUDIT_RESULT: PASS] ──→ update_outline_summary ──→ END
                     │
                     └── [AUDIT_RESULT: FAIL & round<2] ──→ revise_outline ──→ audit_outline (回到审核)
                     
                     └── [AUDIT_RESULT: FAIL & round>=2] ──→ update_outline_summary ──→ END

call_planner 失败 ──→ END (返回错误)
```

### 3.2 节点说明

| 节点 | 功能 | 调用的子 Agent | 输出文件 |
|------|------|---------------|----------|
| `call_planner` | 调用规划 Agent 完成细纲/卷纲编写 | outline-planner / volume-planner / book-rules-manager | 细纲/卷纲文件 |
| `audit_outline` | 审核细纲质量 | outline-auditor | `04-审稿/第N-M章-审核报告.md` |
| `revise_outline` | 根据审核报告修改细纲 | outline-reviser | 更新细纲文件 + `04-审稿/第N-M章-修改记录.md` |
| `update_outline_summary` | 更新细纲摘要 | outline-summarizer | 更新 `00-世界观/细纲摘要.md` |

### 3.3 路由逻辑

#### `_route_after_planner`（call_planner 后路由）

| 条件 | 路由目标 | 说明 |
|------|----------|------|
| planner 执行失败 | END | 返回错误信息 |
| planner_name == book-rules-manager | END | 规则管理不需要审核 |
| planner_name == outline-planner | audit_outline | 细纲需要审核 |
| planner_name == volume-planner | update_outline_summary | 卷纲不需要审核，直接更新摘要 |

#### `_should_revise_outline`（audit_outline 后路由）

| 条件 | 路由目标 | 说明 |
|------|----------|------|
| audit_passed == True | update_outline_summary | 审核通过，更新摘要 |
| audit_round >= 2 | update_outline_summary | 已审核 2 轮仍未通过，强制结束 |
| audit_passed == False & audit_round < 2 | revise_outline | 审核未通过，修改细纲 |

### 3.4 审核循环说明

- **最多 2 轮审核**：与 writing 工作流一致
- **Round 1**：call_planner → audit_outline（audit_round 变为 1）
  - PASS → update_outline_summary → END
  - FAIL → revise_outline → audit_outline（Round 2）
- **Round 2**：revise_outline → audit_outline（audit_round 变为 2）
  - PASS → update_outline_summary → END
  - FAIL → update_outline_summary → END（强制结束，即使仍有问题）

### 3.5 审核结论标记

与 writing 工作流一致，outline-auditor 必须在审核报告末尾输出结构化标记：

- `[AUDIT_RESULT: PASS]` — 审核通过
- `[AUDIT_RESULT: FAIL]` — 审核不通过

解析逻辑复用 `_parse_audit_result()` 函数（从 novel_writing.py 提取为公共函数）。

---

## 四、新增 Agent 设计

### 4.1 细纲审核师（outline-auditor）

#### 基本信息

| 属性 | 值 |
|------|------|
| 名称 | outline-auditor |
| 描述 | 细纲审核师，负责对细纲规划师输出的细纲进行多维度审核，确保细纲与卷纲、世界观、角色设定等保持一致 |
| 模型 | inherit（继承父 Agent 模型） |
| 工具组 | file:read, file:write |
| 最大轮次 | 40 |
| 超时时间 | 600s |

#### 必须读取的文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 故事圣经 | `00-世界观/故事圣经.md` | 世界观设定 |
| 角色矩阵 | `00-世界观/角色矩阵.md` | 角色设定 |
| 支线板 | `00-世界观/支线板.md` | 支线剧情 |
| 情感弧线 | `00-世界观/情感弧线.md` | 情感线设定 |
| 细纲摘要 | `00-世界观/细纲摘要.md` | 已有章节的剧情摘要 |
| 卷纲 | `01-规划/卷纲.md` | 卷纲规划 |
| 本书规则 | `01-规划/本书规则.json` | 创作规则 |
| 创作计划 | `01-规划/创作计划.md` | 创作计划 |
| 待审核细纲 | `01-规划/chapters/第N-M章-细纲.md` | 本次审核对象 |
| 待办事项 | `03-状态/待办事项.md` | 伏笔池 |

**二轮审核时额外读取**：
- 上一轮审核报告：`04-审稿/第N-M章-审核报告.md`

#### 审核维度（5 大维度）

##### 维度 1：章节内容审核

审核要点：
- **卷纲一致性**：本章目标与主要事件是否符合卷纲规划
- **世界观一致性**：剧情背景是否与故事圣经设定吻合
- **剧情合理性**：情节发展是否合理，有无逻辑漏洞
- **人物行为合理性**：角色有无出现瞬移（上一章在A地，本章突然出现在B地且无交代）、复活（已确认死亡的角色无故出现）、能力突变（未经过修炼/事件突然获得远超设定的能力）等不科学现象
- **信息越界**：角色是否知道不应该知道的信息（如未获知的秘密、未发生的剧情）
- **时间线一致性**：时间推进是否合理，有无时间矛盾
- **场景转换合理性**：场景切换是否自然，有无突兀跳跃

##### 维度 2：人物审核

审核要点：
- **出场人物完整性**：出场人物列表是否合理，有无多列（不该出场的角色被列入）或少列（应该出场但遗漏的角色）
- **人设一致性**：人物的言行、决策是否符合角色矩阵中的人设
- **角色关系一致性**：角色之间的互动是否符合当前关系状态
- **角色功能合理性**：每个出场角色是否有明确的剧情作用，而非"背景板"
- **角色能力边界**：角色展现的能力是否在设定范围内

##### 维度 3：伏笔处理审核

审核要点：
- **伏笔推进**：待办事项中标记为需推进的伏笔，细纲中是否有对应安排
- **伏笔解决**：待办事项中标记为需解决的伏笔，细纲中是否有对应回收
- **伏笔遗漏**：是否有应该处理但被忽略的伏笔
- **新伏笔合理性**：新增的伏笔是否与主线/支线关联，是否有明确的预期揭示规划
- **伏笔密度**：伏笔埋设和回收的节奏是否合理，避免过度堆积或一次性回收过多

##### 维度 4：节奏与爽点审核

审核要点：
- **爽点安排**：是否安排了合适的爽点（打脸、逆袭、获得、揭秘等）
- **爽点类型多样性**：爽点类型是否单一，是否需要变化
- **节奏张弛**：开篇/中段/结尾的节奏是否合理，有无全程紧绷或全程平淡
- **高潮分布**：章组内高潮是否合理分布（通常第3或最后1章为高潮）
- **钩子设计**：每章结尾是否留有钩子，吸引读者继续阅读
- **情绪曲线**：章组整体情绪走向是否符合卷纲规划

##### 维度 5：可执行性审核

审核要点：
- **信息完整度**：细纲中的信息是否足够写手直接写作（场景、时间、氛围是否明确）
- **事件描述具体性**：主要事件是否有起因、经过、结果，而非模糊概述
- **与前后章节衔接**：章组内前后章节是否衔接自然
- **写作指导明确性**：节奏安排、场景设置等是否足够具体
- **字数可行性**：每章规划的内容量是否在 1600-3000 字范围内可实现

#### 审核报告模板

```markdown
# 第N-M章 细纲审核报告

## 审核摘要
- 审核时间：[时间]
- 审核轮次：第[X]轮
- 审核维度：5 项
- 发现问题：[数量] 个
- 严重程度分布：高[X] / 中[X] / 低[X]
- 审核结论：通过 / 需修改

## 分维度评估

### 1. 章节内容审核：通过/需修改
- 卷纲一致性：✅/⚠️/❌ [说明]
- 世界观一致性：✅/⚠️/❌ [说明]
- 剧情合理性：✅/⚠️/❌ [说明]
- 人物行为合理性：✅/⚠️/❌ [说明]
- 信息越界检查：✅/⚠️/❌ [说明]
- 时间线一致性：✅/⚠️/❌ [说明]
- 场景转换合理性：✅/⚠️/❌ [说明]

### 2. 人物审核：通过/需修改
- 出场人物完整性：✅/⚠️/❌ [说明]
- 人设一致性：✅/⚠️/❌ [说明]
- 角色关系一致性：✅/⚠️/❌ [说明]
- 角色功能合理性：✅/⚠️/❌ [说明]
- 角色能力边界：✅/⚠️/❌ [说明]

### 3. 伏笔处理审核：通过/需修改
- 伏笔推进：✅/⚠️/❌ [说明]
- 伏笔解决：✅/⚠️/❌ [说明]
- 伏笔遗漏：✅/⚠️/❌ [说明]
- 新伏笔合理性：✅/⚠️/❌ [说明]
- 伏笔密度：✅/⚠️/❌ [说明]

### 4. 节奏与爽点审核：通过/需修改
- 爽点安排：✅/⚠️/❌ [说明]
- 爽点类型多样性：✅/⚠️/❌ [说明]
- 节奏张弛：✅/⚠️/❌ [说明]
- 高潮分布：✅/⚠️/❌ [说明]
- 钩子设计：✅/⚠️/❌ [说明]
- 情绪曲线：✅/⚠️/❌ [说明]

### 5. 可执行性审核：通过/需修改
- 信息完整度：✅/⚠️/❌ [说明]
- 事件描述具体性：✅/⚠️/❌ [说明]
- 前后章节衔接：✅/⚠️/❌ [说明]
- 写作指导明确性：✅/⚠️/❌ [说明]
- 字数可行性：✅/⚠️/❌ [说明]

## 详细问题列表

### 问题 1：[问题标题]
- **严重程度**：高/中/低
- **所属维度**：[维度名称]
- **涉及章节**：第[X]章
- **问题描述**：[具体问题描述]
- **修改建议**：[具体可操作的修改建议]

### 问题 2：[问题标题]
[同上格式]

## 二轮审核对比（仅二轮审核时填写）
- 上一轮问题数：[X]
- 本轮已修复：[X]
- 本轮仍存在：[X]
- 本轮新增：[X]

## 总体评价
[整体评价和改进建议]

[AUDIT_RESULT: PASS/FAIL]
```

---

### 4.2 细纲修改师（outline-reviser）

#### 基本信息

| 属性 | 值 |
|------|------|
| 名称 | outline-reviser |
| 描述 | 细纲修改师，负责根据审核报告修改细纲，确保细纲通过审核 |
| 模型 | inherit（继承父 Agent 模型） |
| 工具组 | file:read, file:write |
| 最大轮次 | 40 |
| 超时时间 | 600s |

#### 必须读取的文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 故事圣经 | `00-世界观/故事圣经.md` | 世界观设定 |
| 角色矩阵 | `00-世界观/角色矩阵.md` | 角色设定 |
| 细纲摘要 | `00-世界观/细纲摘要.md` | 已有章节的剧情摘要 |
| 卷纲 | `01-规划/卷纲.md` | 卷纲规划 |
| 本书规则 | `01-规划/本书规则.json` | 创作规则 |
| 待修改细纲 | `01-规划/chapters/第N-M章-细纲.md` | 修改对象 |
| 审核报告 | `04-审稿/第N-M章-审核报告.md` | 审核问题 |
| 待办事项 | `03-状态/待办事项.md` | 伏笔池 |

#### 修改原则

1. **优先修复高严重度问题**：先处理严重程度为"高"的问题
2. **保持卷纲框架**：修改不得偏离卷纲规划的方向
3. **保持章节结构**：只修改问题部分，不重写整份细纲
4. **使用 str_replace**：优先使用 str_replace 精确替换，避免全量重写
5. **修改后自检**：修改完成后检查是否引入新问题

#### 输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 修改后细纲 | `01-规划/chapters/第N-M章-细纲.md` | 覆盖写入 |
| 修改记录 | `04-审稿/第N-M章-修改记录.md` | 记录修改内容 |

#### 修改记录模板

```markdown
# 第N-M章 细纲修改记录

## 修改摘要
- 修改时间：[时间]
- 修改轮次：第[X]轮
- 修改原因：[审核报告中的主要问题]
- 修改范围：[整体/部分章节/具体问题点]

## 修改详情

### 修改 1：[问题描述]
- **涉及章节**：第[X]章
- **原内容**：[原文引用]
- **修改为**：[修改后内容]
- **修改原因**：[对应审核报告中的问题编号和说明]

### 修改 2：[问题描述]
[同上格式]

## 未修改的问题
[审核报告中存在但因故未修改的问题，说明原因]
```

---

### 4.3 细纲摘要维护师（outline-summarizer）

#### 基本信息

| 属性 | 值 |
|------|------|
| 名称 | outline-summarizer |
| 描述 | 细纲摘要维护师，负责根据细纲内容更新细纲摘要文档，为其他 Agent 提供简洁的剧情走向参考 |
| 模型 | inherit（继承父 Agent 模型） |
| 工具组 | file:read, file:write |
| 最大轮次 | 30 |
| 超时时间 | 300s |

#### 必须读取的文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 本次细纲 | `01-规划/chapters/第N-M章-细纲.md` | 本次工作流产出的细纲 |
| 现有细纲摘要 | `00-世界观/细纲摘要.md` | 当前摘要（如已存在） |

#### 输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 细纲摘要 | `00-世界观/细纲摘要.md` | 更新或新建 |

#### 细纲摘要文档模板

```markdown
# 细纲摘要

## 第1-5章
- 第1章：[一句话剧情概述]
- 第2章：[一句话剧情概述]
- 第3章：[一句话剧情概述]
- 第4章：[一句话剧情概述]
- 第5章：[一句话剧情概述]

## 第6-10章
- 第6章：[一句话剧情概述]
- 第7章：[一句话剧情概述]
...
```

#### 更新规则

1. **增量更新**：只添加/更新本次工作流涉及的章节组，不修改其他章节组的内容
2. **简洁原则**：每章用一句话（20-40字）概述剧情走向
3. **使用 str_replace**：如果文件已存在，使用 str_replace 精确替换对应章节组的内容
4. **新建场景**：如果文件不存在，使用 write_file 创建

---

## 五、目录结构变更

### 5.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `00-世界观/细纲摘要.md` | 细纲摘要，每章一句话概述 |
| `04-审稿/第N-M章-审核报告.md` | 细纲审核报告 |
| `04-审稿/第N-M章-修改记录.md` | 细纲修改记录 |

### 5.2 更新后的完整目录结构

```
工作目录/book/[小说名称]/
├── card.json                    # 小说名片（JSON 格式，记录进度等元数据）
├── 00-世界观/
│   ├── 故事圣经.md           # 故事圣经（世界观、力量体系、核心冲突）
│   ├── 角色矩阵.md      # 角色矩阵（角色档案、关系网）
│   ├── 支线板.md         # 支线板（多条故事线跟踪）
│   ├── 情感弧线.md        # 情感弧线（角色情感发展）
│   └── 细纲摘要.md       # 细纲摘要（每章一句话剧情概述）【新增】
├── 01-规划/
│   ├── 卷纲.md        # 卷纲（分卷概览 + 章节分组规划）
│   ├── 本书规则.json          # 本书规则（JSON 格式，硬规则+风格指南）
│   ├── 创作计划.md             # 创作计划
│   └── chapters/                # 章节细纲（每 5 章一组）
│       ├── 第1-5章-细纲.md
│       ├── 第6-10章-细纲.md
│       └── ...
├── 02-正文/                     # 正文按章节组组织
│   └── 第N-M章/                 # 每组一个文件夹（如：第1-5章/）
│       ├── _task/               # 临时任务目录（写作时创建，完成后清理）
│       │   ├── 世界观参考.md
│       │   ├── 人物参考.md
│       │   ├── 道具参考.md
│       │   ├── 故事线参考.md
│       │   ├── 用户要求.md
│       │   └── 写作任务汇总.md
│       ├── 第N章.md             # 各章节正文
│       ├── 第N+1章.md
│       └── ...
├── 03-状态/
│   ├── 当前状态卡.md         # 当前状态卡（主角位置、目标、敌人等）
│   ├── 待办事项.md         # 伏笔池（未解决伏笔跟踪）
│   └── 章节摘要汇总.md     # 章节摘要汇总
├── 04-审稿/
│   ├── 第1章-审计报告.md     # 正文审计报告
│   ├── 第1章-修改记录.md     # 正文修改记录
│   ├── 第1-5章-审核报告.md  # 细纲审核报告【新增】
│   ├── 第1-5章-修改记录.md  # 细纲修改记录【新增】
│   └── ...
├── 05-参考/
│   ├── 样式指纹.md         # 风格指纹（从样章提取）
│   └── 市场分析.md          # 市场分析（如适用）
└── 06-归档/
    ├── 合并后的卷摘要.md # 压缩后的卷摘要
    └── 历史版本/                 # 重要修改前备份
```

---

## 六、Agent 提示词更新清单

### 6.1 需要更新"必须读取文件"的 Agent

以下 Agent 需要在其 SOUL.md 中新增 `00-世界观/细纲摘要.md` 作为必须或推荐读取的文件：

| Agent | 更新内容 | 说明 |
|-------|----------|------|
| outline-planner | 新增细纲摘要为必须读取文件 | 编写细纲时需参考已有章节的剧情走向 |
| outline-auditor | 新增细纲摘要为必须读取文件 | 审核时需参考已有章节的剧情走向 |
| outline-reviser | 新增细纲摘要为必须读取文件 | 修改时需参考已有章节的剧情走向 |
| outline-summarizer | 新增细纲摘要为必须读取文件 | 更新摘要时需读取现有内容 |
| continuity-auditor | 新增细纲摘要为补充读取文件 | 审核正文时可快速了解前情 |
| novel-writer | 新增细纲摘要为补充读取文件 | 写作时可快速了解前情 |
| novel-reviser | 新增细纲摘要为补充读取文件 | 修稿时可快速了解前情 |
| world-updater | 新增细纲摘要为按需读取文件 | 更新世界观时可参考剧情走向 |
| novel-world-organizer | 新增细纲摘要为补充读取文件 | 整理世界观参考时可参考剧情走向 |
| novel-character-organizer | 新增细纲摘要为补充读取文件 | 整理人物参考时可参考剧情走向 |
| novel-storyline-organizer | 新增细纲摘要为补充读取文件 | 整理故事线参考时可参考剧情走向 |

### 6.2 需要更新目录结构的 Agent

所有 Agent 的 SOUL.md 中都包含 `{{novel_dir_structure}}` 模板变量，更新 `novel_dir_structure` 系统变量后，所有 Agent 会自动获取新的目录结构。

**需要手动更新系统变量的文件**：
- `backend/packages/harness/deerflow/global_variables/db_sqlite.py`
- `backend/packages/harness/deerflow/global_variables/db_postgres.py`

### 6.3 novel-master SOUL.md 更新

主控 Agent 的模式4（规划任务）需要更新：

1. 移除"工作流自动更新世界观"的描述
2. 新增"工作流自动审核细纲"的描述
3. 更新工作流自动行为说明

---

## 七、环境变量更新详情

### 7.1 `novel_dir_structure` 更新内容

环境变量 `novel_dir_structure` 是系统级全局变量，在 `db_sqlite.py` 和 `db_postgres.py` 中硬编码定义。本次需要更新以下内容：

**新增**：
- `00-世界观/细纲摘要.md` — 细纲摘要（每章一句话剧情概述）
- `04-审稿/第N-M章-审核报告.md` — 细纲审核报告（规划阶段）
- `04-审稿/第N-M章-修改记录.md` — 细纲修改记录（规划阶段）

**修正**：
- `03-状态/当前状态卡.md` — 原目录结构遗漏此文件（修正）

### 7.2 更新步骤

1. 修改 `backend/packages/harness/deerflow/global_variables/db_sqlite.py` 中的 `_build_system_variables()` 函数
2. 修改 `backend/packages/harness/deerflow/global_variables/db_postgres.py` 中的 `_build_system_variables()` 函数（与 sqlite 保持一致）
3. 重启服务使新变量生效（系统变量在启动时加载到内存）

### 7.3 验证方法

重启服务后，通过以下方式验证环境变量是否更新成功：

1. 查看后端日志，确认服务启动时成功加载系统变量
2. 通过 API 获取 `novel_dir_structure` 变量，检查是否包含新增的文件
3. 创建新会话，验证 Agent 的 SOUL.md 中 `{{novel_dir_structure}}` 被替换为新的目录结构

---

## 八、代码变更清单

### 8.1 新增文件

| 文件 | 说明 |
|------|------|
| `backend/.deer-flow/agents/outline-auditor/SOUL.md` | 细纲审核师提示词 |
| `backend/.deer-flow/agents/outline-reviser/SOUL.md` | 细纲修改师提示词 |
| `backend/.deer-flow/agents/outline-summarizer/SOUL.md` | 细纲摘要维护师提示词 |

### 8.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `backend/packages/harness/deerflow/workflows/novel_plan.py` | 重写工作流：移除世界观更新，增加审核循环和摘要更新 |
| `backend/packages/harness/deerflow/workflows/states.py` | 新增 `outline_audit_passed`、`outline_audit_round` 状态字段 |
| `backend/packages/harness/deerflow/workflows/novel_writing.py` | 提取 `_parse_audit_result` 为公共函数 |
| `backend/packages/harness/deerflow/global_variables/db_sqlite.py` | 更新 `novel_dir_structure` 环境变量 |
| `backend/packages/harness/deerflow/global_variables/db_postgres.py` | 更新 `novel_dir_structure` 环境变量 |
| `backend/.deer-flow/agents/outline-planner/SOUL.md` | 新增细纲摘要 + 当前状态卡 |
| `backend/.deer-flow/agents/outline-auditor/SOUL.md` | 新建：细纲摘要 + 当前状态卡 |
| `backend/.deer-flow/agents/outline-reviser/SOUL.md` | 新建：细纲摘要 + 当前状态卡 |
| `backend/.deer-flow/agents/outline-summarizer/SOUL.md` | 新建：细纲摘要 |
| `backend/.deer-flow/agents/continuity-auditor/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-writer/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-reviser/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-master/SOUL.md` | 更新模式4描述 |
| `backend/.deer-flow/agents/world-updater/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-world-organizer/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-character-organizer/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `backend/.deer-flow/agents/novel-storyline-organizer/SOUL.md` | 新增细纲摘要 + 当前状态卡（之前遗漏） |
| `config.example.yaml` | 新增 3 个 Agent 的超时/轮次配置 |
| `backend/packages/harness/deerflow/tools/builtins/workflow_tool.py` | 更新 plan 工作流的文档说明 |

### 8.3 可删除的代码

| 文件 | 可删除内容 | 说明 |
|------|-----------|------|
| `novel_plan.py` | `scan_world_files` 节点函数 | 不再需要扫描世界观文件 |
| `novel_plan.py` | `update_world_files` 节点函数 | 不再需要更新世界观文件 |
| `novel_plan.py` | `_update_all_world_files_batch` 函数 | 批量更新逻辑 |
| `novel_plan.py` | `_update_single_world_file` 函数 | 单文件更新逻辑 |
| `novel_plan.py` | `update_world_files_sequential` 函数 | 串行更新逻辑 |
| `novel_plan.py` | `update_world_files_parallel` 函数 | 并行更新逻辑 |
| `novel_plan.py` | `_is_parallel_enabled` 函数 | 并行开关判断 |
| `novel_plan.py` | `_inject` 函数 | 文件注入辅助函数 |

> 注意：`world-updater` Agent 仍然保留，在 writing 工作流的后处理阶段继续使用。

---

## 九、NovelWorkflowState 状态字段变更

### 9.1 新增字段

```python
class NovelWorkflowState(TypedDict, total=False):
    # ... 现有字段 ...
    outline_audit_passed: bool      # 细纲审核是否通过
    outline_audit_round: int        # 细纲审核轮次（0起始，每轮+1）
    outline_audit_report: str       # 细纲审核报告路径
    outline_summary_updated: bool   # 细纲摘要是否已更新
```

### 9.2 可移除字段

```python
    # 以下字段可移除（plan 工作流不再使用）
    world_files: list[str]          # 世界观文件列表
    world_updated: bool             # 世界观是否已更新
```

> 注意：这两个字段仅在 plan 工作流中使用，可以安全移除。

---

## 十、调用示例

### 10.1 新建细纲（触发审核循环）

```
workflow_name: "plan"
params: {
    planner_name: "outline-planner",
    planner_mode: "new",
    chapter_group: "第1-5章",
    planner_task: "前5章的细纲"
}
```

**工作流执行过程**：
1. call_planner → outline-planner 编写细纲
2. audit_outline → outline-auditor 审核细纲
3. 如果 FAIL → revise_outline → outline-reviser 修改细纲 → audit_outline（第二轮）
4. update_outline_summary → outline-summarizer 更新细纲摘要
5. END

### 10.2 修改卷纲（不触发审核，直接更新摘要）

```
workflow_name: "plan"
params: {
    planner_name: "volume-planner",
    planner_mode: "revise",
    planner_task: "第二卷增加一个转折"
}
```

**工作流执行过程**：
1. call_planner → volume-planner 修改卷纲
2. update_outline_summary → outline-summarizer 更新细纲摘要
3. END

### 10.3 修改规则（不触发审核，不更新摘要）

```
workflow_name: "plan"
params: {
    planner_name: "book-rules-manager",
    planner_task: "增加禁用词列表"
}
```

**工作流执行过程**：
1. call_planner → book-rules-manager 修改规则
2. END

---

## 十一、config.example.yaml 变更

在 `subagents.agents` 中新增 3 个 Agent 的配置：

```yaml
subagents:
  agents:
    # ... 现有配置 ...
    world-updater:
      timeout_seconds: 600
      max_turns: 60
    # 细纲审核师（规划工作流调用，审核细纲质量）
    outline-auditor:
      timeout_seconds: 600
      max_turns: 40
    # 细纲修改师（规划工作流调用，根据审核报告修改细纲）
    outline-reviser:
      timeout_seconds: 600
      max_turns: 40
    # 细纲摘要维护师（规划工作流调用，更新细纲摘要文档）
    outline-summarizer:
      timeout_seconds: 300
      max_turns: 30
```

---

## 十二、与现有系统的兼容性

### 12.1 writing 工作流不受影响

- writing 工作流仍然使用 `continuity-auditor` 和 `novel-reviser` 进行正文审核
- writing 工作流的后处理仍然调用 `world-updater` 更新世界观
- plan 工作流移除世界观更新后，world-updater 仅在 writing 工作流中使用

### 12.2 organize 工作流不受影响

- organize 工作流的流程和节点不变

### 12.3 已有小说数据兼容

- `00-世界观/细纲摘要.md` 是新增文件，对已有小说无影响
- `04-审稿/` 下的细纲审核报告使用不同的命名规则（`第N-M章-审核报告.md` vs `第N章-审计报告.md`），不会与正文审计报告冲突

---

## 十三、测试要点

### 13.1 工作流测试

| 测试场景 | 预期结果 |
|----------|----------|
| 新建细纲，一轮审核通过 | call_planner → audit_outline(PASS) → update_outline_summary → END |
| 新建细纲，一轮审核不通过，二轮通过 | call_planner → audit_outline(FAIL) → revise_outline → audit_outline(PASS) → update_outline_summary → END |
| 新建细纲，两轮审核都不通过 | call_planner → audit_outline(FAIL) → revise_outline → audit_outline(FAIL) → update_outline_summary → END |
| 修改卷纲 | call_planner → update_outline_summary → END |
| 修改规则 | call_planner → END |
| planner 执行失败 | call_planner → END（返回错误） |

### 13.2 Agent 测试

| 测试场景 | 预期结果 |
|----------|----------|
| outline-auditor 审核通过 | 输出审核报告，末尾包含 `[AUDIT_RESULT: PASS]` |
| outline-auditor 审核不通过 | 输出审核报告，末尾包含 `[AUDIT_RESULT: FAIL]` |
| outline-reviser 修改细纲 | 使用 str_replace 修改细纲，输出修改记录 |
| outline-summarizer 新建摘要 | 创建 `细纲摘要.md`，包含各章一句话概述 |
| outline-summarizer 更新摘要 | 使用 str_replace 更新对应章节组的内容 |

### 13.3 环境变量测试

| 测试场景 | 预期结果 |
|----------|----------|
| 全局变量 novel_dir_structure | 包含 `细纲摘要.md` 和 `03-状态/当前状态卡.md` |
| Agent 读取细纲摘要 | 所有相关 Agent 的 SOUL.md 中包含细纲摘要路径 |
| Agent 读取当前状态卡 | 所有相关 Agent 的 SOUL.md 中包含当前状态卡路径 |

---

## 十四、风险与注意事项

### 14.1 审核循环可能增加延迟

- 每轮审核需要调用 outline-auditor，修改需要调用 outline-reviser
- 最坏情况下（2轮审核都不通过），plan 工作流需要调用 4 次子 Agent（planner + auditor + reviser + auditor）
- 建议 outline-auditor 和 outline-reviser 的 max_turns 设置合理值，避免无限循环

### 14.2 审核标准一致性

- outline-auditor 的审核标准需要在 SOUL.md 中明确定义
- 不同 LLM 模型对审核标准的理解可能不同，建议在审核报告中使用结构化模板

### 14.3 世界观更新移除的影响

- 移除 plan 工作流中的世界观自动更新后，世界观文件不会在细纲规划后自动更新
- 世界观更新改为在 writing 工作流的后处理阶段由 world-updater 完成
- 如果用户需要单独更新世界观，可以通过主控 Agent 手动调用 world-updater

### 14.4 细纲摘要的维护

- outline-summarizer 只在 plan 工作流中调用，不会在 writing 工作流中更新
- 如果正文写作偏离了细纲，细纲摘要可能与实际正文不一致
- 建议在 writing 工作流的 sync_outline 步骤后，也调用 outline-summarizer 更新摘要（后续优化）

### 14.5 环境变量更新的影响

- 环境变量更新后，新会话会立即生效
- 已有会话不受影响（环境变量在会话创建时注入）
- 建议在低峰期重启服务，避免影响用户体验

---

*文档创建时间：2026-05-14*
*文档更新时间：2026-05-14*
*适用版本：DeerFlow 二开项目*
