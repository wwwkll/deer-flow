# 小说创作系统

基于 DeerFlow 2.0 二次开发的**长篇网文自动化创作系统**。

DeerFlow 是一个开源的 super agent harness，本项目在其基础上二开了一套完整的小说写作系统，包含 1 个主控 Agent + 14 个子 Agent，支持从新建小说、规划细纲/卷纲、写作章节、修改章节、审核连续性等全流程自动化。

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

## 目录

- [快速开始](#快速开始)
  - [配置](#配置)
  - [运行](#运行)
- [小说写作系统](#小说写作系统)
  - [Agent 架构](#agent-架构)
  - [自定义工具](#自定义工具)
  - [自定义技能](#自定义技能)
  - [工作目录结构](#工作目录结构)
  - [使用示例](#使用示例)
- [文档](#文档)
- [安全使用](#安全使用)
- [许可证](#许可证)

## 快速开始

### 配置

1. **克隆项目**

   ```bash
   git clone <>
   cd deer-flow
   ```

2. **生成配置文件**

   ```bash
   make config
   ```

3. **配置模型和 API Key**

   编辑 `config.yaml`：

   ```yaml
   models:
     - name: qwen-3-6-online
       display_name: Qwen 3.6 Online
       use: langchain_openai:ChatOpenAI
       model: qwen-3-6-online
       api_key: $OPENAI_API_KEY
       base_url: https://your-api-endpoint/v1
       max_tokens: 80000
       temperature: 0.7
   ```

   编辑 `.env`：

   ```bash
   LANGGRAPH_ALLOW_BLOCKING=1
   OPENAI_API_KEY=your-api-key
   ```

4. **启动服务**

   ```bash
   make dev           # 本地开发
   # 或
   make docker-start  # Docker 开发
   ```

   访问：http://localhost:2026

## 小说写作系统

### Agent 架构

系统包含 1 个主控 Agent 和 14 个子 Agent：

| 类别 | Agent | 功能 |
|------|-------|------|
| 主控 | novel-master | 协调所有子 Agent，接收用户指令 |
| 规划类 | novel-architect | 新建小说时生成完整基础设定 |
| | volume-planner | 编写/修改全书卷纲 |
| | outline-planner | 编写/修改章节细纲（每 5 章一组） |
| | book-rules-manager | 管理 本书规则.json 写作规则 |
| 整理类 | novel-world-organizer | 整理当前章节需要的世界观设定 |
| | novel-character-organizer | 整理当前章节出场的人物信息 |
| | novel-item-organizer | 整理当前章节出场的道具和技能 |
| 写作类 | novel-writer | 根据写作任务汇总撰写正文 |
| | continuity-auditor | 多维度审核章节一致性 |
| | novel-reviser | 根据审计报告修改正文 |
| 状态管理类 | state-settler | 更新状态文件（位置、伏笔、摘要等） |
| | chapter-summarizer | 生成章节摘要 |
| | card-manager | 更新小说名片（card.json） |
| | hook-manager | 管理伏笔池状态 |

### 自定义工具

| 工具 | 功能 | 代码 |
|------|------|------|
| context_assembler | 写作上下文汇总，合并细纲、世界观、人物、道具等参考信息 | [my_tools/context_assembler.py](my_tools/context_assembler.py) |
| post_write_validator | 写作后格式验证，检查正文格式是否符合规范 | [my_tools/post_write_validator.py](my_tools/post_write_validator.py) |
| ai_trace_detector | AI 痕迹检测，检测并分析正文中的 AI 写作特征 | [my_tools/ai_trace_detector.py](my_tools/ai_trace_detector.py) |
| card_validator | card.json 格式验证，验证并规范化小说名片格式 | [my_tools/card_validator.py](my_tools/card_validator.py) |
| master_writer | 小说主控专用写入工具（受限白名单），只允许创建目录和写入 03-状态 目录下的文件 | [my_tools/master_writer.py](my_tools/master_writer.py) |
| novel_reader | 小说写手专用读取工具（受限白名单），只允许读取 _task/、05-参考/、02-正文/ 目录下的文件 | [my_tools/novel_reader.py](my_tools/novel_reader.py) |

### 自定义技能

| 技能 | 功能 | 目录 |
|------|------|------|
| novel-post-write-validator | 写作后格式验证技能 | [skills/custom/novel-post-write-validator/](skills/custom/novel-post-write-validator/) |
| novel-anti-ai-detector | AI 痕迹检测与消除技能 | [skills/custom/novel-anti-ai-detector/](skills/custom/novel-anti-ai-detector/) |
| novel-plan-compliance | 规划合规检查技能 | [skills/custom/novel-plan-compliance/](skills/custom/novel-plan-compliance/) |

### 工作流 (Workflow)

工作流是确定性的任务编排，不依赖 LLM 决策，保证流程完整执行。与 Agent/Skill 的区别：

| 概念 | 本质 | 执行方式 |
|------|------|----------|
| Agent | 独立 LLM 会话 | LLM 自主决策 |
| Skill | 提示词模板 | 自动注入上下文 |
| Workflow | 确定性编排 | 代码预定义，无 LLM 决策 |

| 工作流 | 功能 | 说明 |
|--------|------|------|
| organize | 整理工作流 | 步骤1-4：确认章节→创建文件夹→并行整理(世界观/人物/道具)→汇总 |
| writing | 写作工作流 | 检查任务汇总→写作→审核→(通过/修改2次后)→同步细纲 |
| post_process | 后处理工作流 | 摘要+状态+伏笔+名片+同步细纲，可独立调用 |

主 Agent 通过 `workflow` 工具调用工作流：

```
调用 workflow 工具：
- workflow_name: "organize"
- params: {"novel_name": "都市逍遥仙", "chapter_num": 6, "chapter_group": "06-10"}
- description: "整理第6章参考信息"
```

审核判断使用结构化标记 `[AUDIT_RESULT: PASS/FAIL]`，脚本解析标记而非关键词匹配。

工作流文件位置：`backend/packages/harness/deerflow/workflows/`

### 工作目录结构

```
工作目录/book/[小说名称]/
├── card.json                    # 小说名片（JSON 格式）
├── 00-世界观/
│   ├── 故事圣经.md           # 故事圣经（世界观、力量体系、核心冲突）
│   ├── 角色矩阵.md      # 角色矩阵（角色档案、关系网）
│   ├── subplot-board.md         # 支线板（多条故事线跟踪）
│   └── emotional-arcs.md        # 情感弧线（角色情感发展）
├── 01-规划/
│   ├── 卷纲.md        # 卷纲（分卷概览 + 章节分组规划）
│   ├── 本书规则.json          # 本书规则（JSON 格式）
│   ├── 创作计划.md             # 创作计划
│   └── chapters/                # 章节细纲（每 5 章一组）
├── 02-正文/
│   └── 第N-M章/
│       ├── _task/               # 临时任务目录
│       └── 第N章.md             # 章节正文
├── 03-状态/
│   ├── 当前状态卡.md         # 当前状态卡
│   ├── 待办事项.md         # 伏笔池
│   └── 章节摘要汇总.md     # 章节摘要汇总
├── 04-审稿/
│   ├── 第01章-审计报告.md
│   └── 第01章-修改记录.md
├── 05-参考/
└── 06-归档/
```

### 使用示例

在 Web 界面选择 `novel-master` Agent，发送指令：

```
我要写一部都市小说，书名《都市逍遥仙》，类型都市修仙，一句话概念：一个普通外卖员意外获得修仙传承，在都市中逍遥闯荡的故事。平台：起点。
```

```
写第1章
```

```
修改第1章，加强主角和反派的冲突，增加一些对话
```

```
现在写到哪了？当前状态是什么？
```

## 文档

- [Agent/Skill/Tool 配置指南](二开准备/二开经验/Agent-Skill-Tool配置指南.md)
- [测试用例](二开准备/二开需求文档/agent配置/测试用例.md)
- [DeerFlow 配置指南](backend/docs/CONFIGURATION.md)
- [DeerFlow 后端架构](backend/README.md)

## 安全使用

本系统具备**系统指令执行、文件读写、业务逻辑调用**等关键能力，默认设计为**部署在本地可信环境**。若部署至公网或不可信网络环境，必须采取严格的安全防护措施：

- **设置 IP 白名单**：使用防火墙或带 ACL 功能的网络设备
- **前置身份验证**：配置反向代理（nginx 等），开启身份验证
- **网络隔离**：将系统部署到专用 VLAN

## 许可证

本项目采用 [MIT License](./LICENSE) 开源发布。
