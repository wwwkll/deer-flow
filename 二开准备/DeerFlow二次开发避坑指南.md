# DeerFlow 二次开发 - 配置问题避坑指南

## 一、.gitignore 忽略的文件（环境安装后仍无法启动）

### 1.1 Agent 配置文件（16 个 config.yaml）

**现象**：启动后调用 novel-master Agent 时报错 `Agent config not found`

**原因**：`.gitignore` 第 27 行 `config.yaml` 是全局规则，匹配所有同名文件，导致 Agent 配置无法上传到 git。

**位置**：`backend/.deer-flow/agents/<agent-name>/config.yaml`

**说明**：所有 config.yaml 仅本地使用，不上传。部署新项目时需手动创建。

| Agent | 特殊配置 |
|-------|---------|
| novel-master | `tool_groups` 含 bash、novel；`subagent_enabled: true`；含 skills |
| 其他 15 个 | 仅 file:read、file:write；`subagent_enabled: false` |

**novel-master 配置示例**：
```yaml
name: novel-master
description: |
  小说创作系统主控Agent，负责协调所有子Agent完成小说创作任务。
model: null
tool_groups:
  - file:read
  - file:write
  - bash
  - novel
skills:
  - novel-post-write-validator
  - novel-anti-ai-detector
  - novel-plan-compliance
subagent_enabled: true
max_concurrent_subagents: 3
```

其他 15 个 Agent 配置基本相同，只有 `name`、`description` 不同，`subagent_enabled: false`。

### 1.2 共享数据目录

**重要变更**：共享目录已迁移至项目外部，避免触发服务自动重启。

**旧路径**（已废弃）：
```
backend/.deer-flow/shared-data/
```

**新路径**：
```
E:\xiangmu\deer-flow-data\shared-data\
```

**原因**：
- 原目录位于项目目录内（`backend/.deer-flow/shared-data`）
- 开发模式下 uvicorn 启用 `--reload`，监控整个 `backend` 目录的文件变化
- Agent 在共享目录中创建/修改文件时，会触发 uvicorn 检测到文件变化，导致服务自动重启
- 重启过程中 LangGraph 异步任务清理失败，出现 `CancelledError`、`Event loop is closed` 等错误，导致服务连不上

**解决方案**：
- 将 `host_path` 配置为项目外部的绝对路径（如 `E:\xiangmu\deer-flow-data\shared-data`）
- Agent 对该目录的读写不会触发 uvicorn reload
- 不影响 Agent 的读写权限（Agent 运行在同一 Python 进程中，使用当前用户权限）

**配置位置**：`config.yaml` 中的 `sandbox.mounts` 字段

```yaml
sandbox:
  mounts:
    - host_path: E:\xiangmu\deer-flow-data\shared-data    # 必须在项目目录外
      container_path: /mnt/shared-data
      read_only: false
```

**目录结构**：
```
E:\xiangmu\deer-flow-data\
└── shared-data\
    └── book\
        ├── 小说A\
        ├── 小说B\
        └── 测试小说\
            ├── 00-世界观\
            ├── 01-规划\
            ├── 02-正文\
            └── 03-状态\
```

---

### 1.3 SQLite 数据库

```
backend/.deer-flow/checkpoints.db
```
被 `.gitignore` 忽略（本地运行时数据），**不需要手动创建**，服务启动时自动初始化。

---

## 二、根 config.yaml 必须配置的内容

### 2.1 模型配置

项目没有默认模型，必须在 `config.yaml` 中配置至少一个模型：

```yaml
models:
  - name: mimo-v2-omni
    display_name: mimo-v2-omni
    use: langchain_openai:ChatOpenAI
    model: mimo-v2-omni
    api_key: your-api-key
    base_url: https://your-api-endpoint/v1
    request_timeout: 60000.0
    max_retries: 4
    max_tokens: 80000
    temperature: 1
    supports_thinking: false
    supports_vision: false
```

**注意**：部分模型不支持 thinking mode，设置 `supports_thinking: false` 即可。

### 2.2 自定义工具注册

**自定义工具（`my_tools/` 目录）必须在 config.yaml 中注册**，不会被自动发现：

```yaml
tool_groups:
  - name: novel

tools:
  - name: context_assembler
    group: novel
    use: my_tools.context_assembler:context_assembler
  - name: post_write_validator
    group: novel
    use: my_tools.post_write_validator:post_write_validator
  - name: ai_trace_detector
    group: novel
    use: my_tools.ai_trace_detector:ai_trace_detector
  - name: card_validator
    group: novel
    use: my_tools.card_validator:card_validator
```

**注册规则**：
- ✅ **工具（Tools）**：必须在 config.yaml 中注册
- ❌ **工作流（Workflows）**：不需要注册，代码级自动注册（通过 `__init__.py` 中的 `register_workflow()`）
- ❌ **Agent（子Agent）**：不需要在根 config.yaml 注册，各自在 `agents/<name>/config.yaml` 中配置

### 2.3 子 Agent 模型继承

子 Agent **不单独配置 model** 时，会继承主 Agent 的模型配置。

在 agent 的 `config.yaml` 中设置 `model: null` 即表示继承父模型。

---

## 三、运行时配置问题

### 3.1 my_tools 模块导入失败

**错误**：`ModuleNotFoundError: No module named 'my_tools'`

**原因**：`my_tools` 目录在项目根目录，langgraph 从 `backend/` 目录运行，Python 找不到该模块。

**解决**：创建 `backend/.env`，写入：
```
PYTHONPATH=..;.
```

### 3.2 Windows BlockingError

**错误**：`blockbuster.blockbuster.BlockingError: Blocking call to os.getcwd`

**原因**：LangGraph 的 blockbuster 库在 Windows 上将 `Path.resolve()` 检测为阻塞调用。

**解决**（需同时设置）：
1. 根目录 `.env` 添加：
   ```
   LANGGRAPH_ALLOW_BLOCKING=1
   BG_JOB_ISOLATED_LOOPS=true
   ```
2. `scripts/serve.sh` 中 LangGraph 和 Gateway 启动命令添加 `BG_JOB_ISOLATED_LOOPS=true` 环境变量

### 3.3 前端 TanStack Query undefined 错误

**错误**：`Query data cannot be undefined`

**原因**：TanStack Query v5 不允许查询函数返回 `undefined`。

**修复位置**：`frontend/src/core/novel-tags/hooks.ts`

```typescript
// 修改前
return novelToc?.value

// 修改后
return novelToc?.value ?? null
```

---

## 四、快速检查清单

新项目部署时按顺序检查：

- [ ] 根目录 `config.yaml` 配置了模型、工具注册、工具组
- [ ] 16 个 Agent 的 `config.yaml` 全部创建
- [ ] `E:\xiangmu\deer-flow-data\shared-data\` 目录已创建（或你选择的其他项目外路径）
- [ ] `config.yaml` 中 `sandbox.mounts.host_path` 配置为项目外的绝对路径
- [ ] `backend/.env` 包含 `PYTHONPATH=..;.`
- [ ] 根 `.env` 包含 `LANGGRAPH_ALLOW_BLOCKING=1` 和 `BG_JOB_ISOLATED_LOOPS=true`
- [ ] `scripts/serve.sh` 已添加 `BG_JOB_ISOLATED_LOOPS=true` 环境变量
- [ ] `frontend/src/core/novel-tags/hooks.ts` 修复了 undefined 返回
