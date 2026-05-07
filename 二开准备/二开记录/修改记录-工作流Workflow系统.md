# 工作流 (Workflow) 系统开发记录

---

## v1.1 - 文件检查优化

**日期**: 2026-05-05
**功能**: organize workflow 文件检查优化
**开发者**: AI Assistant

### 修改内容

**问题**：每次调用 organize workflow 时，都会重新执行所有4个并行 agent（世界观、人物、道具、故事线），即使某些参考文件已经生成过，造成不必要的 LLM 调用和时间浪费。

**解决方案**：在调用每个 agent 前检查对应的参考文件是否已存在，如果已存在则跳过该 agent，但最后的 `assemble_context`（合并）仍会重新执行。

### 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `backend/packages/harness/deerflow/workflows/novel_organize.py` | 添加文件存在性检查逻辑 |

### 技术实现

1. **Parallel 模式**：
   - 修改 `start_organize_parallel` 函数，返回类型改为 `list[Send] | str`
   - 检查 `_task/` 目录下4个参考文件是否存在
   - 如果所有文件都存在，返回 `"assemble_context"` 直接跳转到合并节点
   - 否则只返回需要执行的 Send 列表

2. **Sequential 模式**：
   - 新增 `_check_file_exists` 辅助函数
   - 使用 conditional_edges 实现跳过逻辑
   - 每个节点执行前检查对应文件，存在则跳转到下一个节点

### 文件检查映射

| 节点名 | 输出文件 |
|--------|----------|
| organize_world | 世界观参考.md |
| organize_characters | 人物参考.md |
| organize_items | 道具参考.md |
| organize_storyline | 故事线参考.md |

### 测试结果

- 模块导入测试 ✅
- Workflow 创建测试 ✅

---

## v1.0 - 初始版本

**日期**: 2026-04-30
**功能**: 确定性工作流引擎
**开发者**: AI Assistant

---

## 一、需求背景

novel-master 的"模式2：写作章节"流程涉及多个子 Agent 调用（整理→写作→审核→后处理），主 Agent 通过 SOUL.md 提示词控制流程顺序，但 LLM 决策存在不确定性，经常遗漏步骤。

**解决方案**：将固定流程编码为确定性工作流，使用 LangGraph StateGraph 编排，不依赖 LLM 决策，保证流程完整执行。

---

## 二、实现方案

### 2.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `backend/packages/harness/deerflow/workflows/__init__.py` | 工作流模块入口 |
| `backend/packages/harness/deerflow/workflows/states.py` | 工作流状态类型定义 |
| `backend/packages/harness/deerflow/workflows/registry.py` | 工作流注册表 |
| `backend/packages/harness/deerflow/workflows/executor.py` | 工作流执行引擎 |
| `backend/packages/harness/deerflow/workflows/helpers.py` | 辅助函数（调用子Agent） |
| `backend/packages/harness/deerflow/workflows/novel_organize.py` | 整理工作流 |
| `backend/packages/harness/deerflow/workflows/novel_writing.py` | 写作工作流 |
| `backend/packages/harness/deerflow/tools/builtins/workflow_tool.py` | workflow 工具 |

### 2.2 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `backend/packages/harness/deerflow/tools/builtins/__init__.py` | 导入 workflow_tool |
| `backend/packages/harness/deerflow/tools/tools.py` | 注册 workflow_tool 到 SUBAGENT_TOOLS |
| `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` | 子Agent中间件链加入 GlobalVariablesMiddleware |
| `config.example.yaml` | 添加工作流配置说明 |
| `README.md` | 添加工作流文档 |
| `二开准备/二开需求文档/agent配置/agents/00-整体规划方案.md` | 更新架构图，添加工作流说明 |
| `二开准备/二开经验/工作流Workflow配置指南.md` | 新增开发经验文档 |

### 2.3 架构设计

```
novel-master (主 Agent)
    ↓ 调用 workflow 工具
    ├── workflow_name: "organize" → 整理工作流
    │   └── confirm_chapter → create_task_folder → organize_world ──┐
    │                                     → organize_characters ─┼→ assemble_context
    │                                     → organize_items ─────┘
    │
    └── workflow_name: "writing" → 写作工作流
        └── write_chapter → audit → [AUDIT_RESULT: PASS] → post_process → sync_outline
                                      → [AUDIT_RESULT: FAIL] → revise → audit (最多2次)
```

---

## 三、关键技术点

### 3.1 审核判断机制

**问题**：关键词匹配 `"通过" in result` 很脆弱，"审核不通过"也包含"通过"。

**解决方案**：要求 continuity-auditor 在报告末尾输出结构化标记：
- `[AUDIT_RESULT: PASS]` - 审核通过
- `[AUDIT_RESULT: FAIL]` - 审核不通过

脚本用正则 `_AUDIT_RESULT_PATTERN` 解析标记，找不到标记时默认为 FAIL。

### 3.2 全局变量替换

**问题**：子 Agent 的中间件链 `build_subagent_runtime_middlewares()` 不包含 `GlobalVariablesMiddleware`，导致 `system_prompt` 中的 `{{xxx}}` 不被替换。

**解决方案**：在 `build_subagent_runtime_middlewares()` 中加入 `GlobalVariablesMiddleware`。

### 3.3 工作流与 Agent 的区别

| 概念 | 本质 | 决策方式 |
|------|------|----------|
| Agent | 独立 LLM 会话 | LLM 自主决策 |
| Skill | 提示词模板 | 无决策，自动注入上下文 |
| Workflow | 确定性编排 | 代码预定义，无 LLM 决策 |

---

## 四、测试结果

### 4.1 模块导入测试

- NovelWorkflowState 导入 ✅
- registry 导入 ✅
- executor 导入 ✅
- helpers 导入 ✅
- 工作流注册 (organize, writing) ✅
- 工作流图创建 ✅
- Workflow 工具导入 ✅
- WorkflowExecutor 创建 ✅

### 4.2 工作流执行测试

| 测试项 | 结果 |
|--------|------|
| 整理工作流执行 | ✅ PASS |
| 写作工作流（审核通过） | ✅ PASS |
| 写作工作流（审核不通过→修改→通过） | ✅ PASS |

### 4.3 修复验证

| 测试项 | 结果 |
|--------|------|
| 审核结果标记解析 | ✅ PASS |
| GlobalVariablesMiddleware 在子Agent链中 | ✅ PASS |
| 结构化审核工作流 | ✅ PASS |

---

## 五、使用方式

主 Agent 在 SOUL.md 中调用工作流：

```
调用 workflow 工具：
- workflow_name: "organize"
- params: {"novel_name": "都市逍遥仙", "chapter_num": 6, "chapter_group": "06-10"}
- description: "整理第6章参考信息"
```

---

## 六、相关文档

- [工作流Workflow配置指南](../二开经验/工作流Workflow配置指南.md)
- [Agent-Skill-Tool配置指南](../二开经验/Agent-Skill-Tool配置指南.md)
- [整体规划方案](../二开需求文档/agent配置/agents/00-整体规划方案.md)
