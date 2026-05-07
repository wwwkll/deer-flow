# Tool 开发经验总结

> 基于 DeerFlow 二开项目的实际开发经验，系统总结自定义工具（Tool）的开发、注册、调试最佳实践。
> 本文档整合了 `自定义工具开发经验`、`Agent-Skill-Tool配置指南`、`Agent读取优先级`、`工作流配置指南` 等文档的核心内容。

---

## 一、Tool 的本质与定位

### 1.1 四类扩展能力的对比

| 概念 | 本质 | 决策方式 | 调用方式 | 适用场景 |
|------|------|----------|----------|----------|
| **Tool** | Python 函数 | 无决策，按参数执行 | Agent 直接调用 | 读写文件、验证格式、移动文件等具体操作 |
| **Skill** | 提示词模板 | 无决策，自动注入上下文 | `Skill` 工具加载 | 增强 Agent 的特定能力（AI检测、反AI痕迹等） |
| **Agent** | 独立 LLM 会话 | LLM 自主决策 | `task` 工具调用 | 复杂任务（写正文、审核、架构设计等） |
| **Workflow** | 确定性编排 | 代码预定义，无 LLM 决策 | `workflow` 工具调用 | 固定流程（整理→写作→审核→后处理） |

### 1.2 何时该写 Tool？

**适合写 Tool 的场景**：
- ✅ 操作是**确定性的**（读文件、写文件、验证 JSON 格式）
- ✅ 不需要 LLM 决策
- ✅ 需要在 Agent 和宿主系统之间做**路径/权限转换**
- ✅ 需要封装**业务逻辑**（组装上下文、管理 card.json）

**不适合写 Tool 的场景**：
- ❌ 需要 LLM 理解/生成内容（应该用 Agent）
- ❌ 是固定的多步流程（应该用 Workflow）
- ❌ 是给 Agent 注入知识/规则（应该用 Skill）

---

## 二、Tool 开发全流程

### 2.1 编写 Python 函数

**标准模板**：

```python
# my_tools/my_tool.py
from langchain.tools import tool
import os
import logging
from my_tools.path_resolver import resolve_to_host_path

logger = logging.getLogger(__name__)

def _resolve_path(file_path: str) -> str:
    """解析路径：支持沙箱绝对路径、相对路径。"""
    normalized = file_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return resolve_to_host_path(normalized)
    relative = normalized.removeprefix("./")
    return resolve_to_host_path(f"/mnt/shared-data/{relative}")

@tool("my_tool_name", parse_docstring=True)
def my_tool_name(
    description: str,
    file_path: str,
    content: str = "",
) -> str:
    """工具的简短描述（Agent 会看到这段 docstring）。

    Args:
        description: 操作说明，简短描述为什么执行此操作。ALWAYS PROVIDE THIS PARAMETER FIRST.
        file_path: 目标路径（绝对路径如 /mnt/shared-data/...，或相对路径如 book/小说名）
        content: 写入内容（如适用）
    """
    host_path = _resolve_path(file_path)
    logger.info("[my_tool_name] input=%s, resolved=%s", file_path, host_path)

    try:
        # 业务逻辑...
        return f"[OK] 操作成功：{file_path}"
    except Exception as e:
        logger.error("[my_tool_name] error: %s", e)
        return f"[FAIL] 操作失败：{str(e)}"
```

**关键要点**：
- ✅ 必须使用 `@tool("名称", parse_docstring=True)` 装饰器
- ✅ 函数必须有类型注解和 docstring（Agent 通过 docstring 理解工具用途）
- ✅ 必须用 `resolve_to_host_path()` 将沙箱路径转为主机路径
- ✅ 必须支持绝对路径（`/mnt/shared-data/...`）和相对路径（`book/...`）
- ✅ 必须记录详细日志（`logger.info` / `logger.error`）
- ✅ 返回字符串作为工具输出（`[OK]` / `[FAIL]` 前缀便于 Agent 判断）

### 2.2 注册到 config.yaml

在 `config.yaml` 中分两步注册：

**步骤 1：声明工具组**
```yaml
tool_groups:
  - name: file:read      # 内置工具组
  - name: file:write     # 内置工具组
  - name: master:write   # 自定义工具组（包含 master_writer）
  - name: novel:tools    # 自定义工具组（包含 card_validator 等）
```

**步骤 2：注册具体工具**
```yaml
tools:
  - name: master_writer
    group: master:write
    use: my_tools.master_writer:master_writer

  - name: card_validator
    group: novel:tools
    use: my_tools.card_validator:card_validator
```

**字段说明**：
| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | 工具名称（Agent 调用时使用的名称） | `card_validator` |
| `group` | 所属工具组 | `novel:tools` |
| `use` | Python 模块映射：`模块路径:函数名` | `my_tools.card_validator:card_validator` |

### 2.3 在 Agent 中启用工具

在 `backend/.deer-flow/agents/{agent_name}/config.yaml` 中：

```yaml
name: novel-master
tool_groups:
  - file:read
  - master:write      # 启用 master_writer 工具
  - novel:tools       # 启用 card_validator 等工具
```

### 2.4 重启服务生效

```bash
make stop
make dev
```

---

## 三、核心经验：路径处理

### 3.1 沙箱路径 vs 主机路径

```
Agent 看到的路径：/mnt/shared-data/book/测试小说/card.json  ← 沙箱虚拟路径
实际文件位置：    c:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\测试小说\card.json  ← 主机真实路径
```

### 3.2 必须使用 path_resolver

**错误写法**（常见坑）：
```python
#  直接操作 Agent 传入的路径
os.makedirs(file_path, exist_ok=True)
```

**正确写法**：
```python
# ✅ 先解析为主机路径
from my_tools.path_resolver import resolve_to_host_path
host_path = resolve_to_host_path(file_path)
os.makedirs(host_path, exist_ok=True)
```

### 3.3 同时支持绝对路径和相对路径

Agent 可能传入两种格式：
- 绝对路径：`/mnt/shared-data/book/小说名`
- 相对路径：`book/小说名` 或 `./book/小说名`

标准处理函数（从 `master_writer.py` 提取）：

```python
def _resolve_path(file_path: str) -> str:
    """解析路径：支持沙箱绝对路径、相对路径。

    1. 如果是绝对路径（以 / 开头），通过 resolve_to_host_path 转换
    2. 如果是相对路径，基于 /mnt/shared-data 拼接为绝对路径后再转换
    """
    normalized = file_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        return resolve_to_host_path(normalized)
    # 相对路径：去除 ./ 前缀，基于 /mnt/shared-data 挂载点拼接
    relative = normalized.removeprefix("./")
    return resolve_to_host_path(f"/mnt/shared-data/{relative}")
```

### 3.4 Windows 路径分隔符的陷阱（重要 Bug 经验）

**Bug 现象**：`_is_within_shared_data` 检查路径是否在 `shared-data` 内，但所有 Windows 路径都被误报 "源路径超出允许范围"。

**根因**：
```python
# ❌ 错误代码
shared_data = "C:/xiangmu/deer-flow/backend/.deer-flow/shared-data"  # 正斜杠
target = str(Path(file_path).resolve())  # Windows 上返回反斜杠：C:\xiangmu\...
return target.startswith(shared_data)    # "C:\..." 不匹配 "C:/..." → False!
```

**修复**：
```python
# ✅ 正确代码
target = str(Path(file_path).resolve()).replace("\\", "/")  # 统一正斜杠
return target.startswith(shared_data)
```

**经验教训**：
> 在 Windows 上做路径比较时，务必统一分隔符。`Path.resolve()` 在 Windows 上返回反斜杠 `\`，而配置文件中的路径通常是正斜杠 `/`。

### 3.5 路径安全性校验

对于涉及文件移动的 Tool，必须做路径逃逸检查：

```python
def _is_within_shared_data(file_path: str) -> bool:
    """检查路径是否在 shared-data 目录内（防止路径逃逸）。"""
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)
```

### 3.6 path_resolver 的挂载原理

```yaml
# config.yaml
sandbox:
  mounts:
    - host_path: backend/.deer-flow/shared-data  # 主机真实路径
      container_path: /mnt/shared-data           # 沙箱虚拟路径
```

`resolve_to_host_path()` 读取 `sandbox.mounts` 配置，将 `/mnt/shared-data/xxx` 替换为 `backend/.deer-flow/shared-data/xxx`。

---

## 四、Tool 与 Agent/Skill/Workflow 的协作

### 4.1 Tool 在 Agent 配置中的位置

```
Agent (novel-master)
├── 使用 tool_groups → 获得一组工具
│   ├── file:read    → read_file, glob, grep
│   ├── file:write   → write_file, str_replace
│   ── novel:tools  → card_validator, context_assembler, master_writer
│
├── 使用 skills      → 加载技能提示词
│   └── novel-post-write-validator
│
└── 调用子 Agent     → 通过 task 工具委派任务
    ├── novel-writer
    └── continuity-auditor
```

### 4.2 Tool 在工作流中的调用

```
workflow_tool 被调用
    ↓
execute_workflow(params)
    ↓
工作流 StateGraph 节点执行
    ↓
节点调用 call_subagent("xxx", task, parent_model=model_name)
    ↓
子 Agent 执行时使用 tools 列表中注册的工具
```

工作流节点调用子 Agent 时，子 Agent 的 `config.yaml` 中声明的 `tool_groups` 会决定它可以使用哪些 Tool。

### 4.3 全局变量替换

子 Agent 的 `system_prompt` 中可以使用 `{{workdir}}`、`{{novel_toc}}` 等全局变量，这些变量在子 Agent 创建时会被 `GlobalVariablesMiddleware` 自动替换。

---

## 五、调试技巧

### 5.1 添加日志

```python
logger.info("[tool_name] action=%s, input_path=%s, host_path=%s", action, file_path, host_path)
logger.info("[tool_name] write_file success: %s", host_path)
logger.error("[tool_name] PermissionError: %s", e)
```

日志会输出到 `c:\xiangmu\deer-flow\logs\langgraph.log`。

### 5.2 实时查看日志

```powershell
# 实时查看 LangGraph 日志
Get-Content c:\xiangmu\deer-flow\logs\langgraph.log -Tail 50 -Wait

# 搜索工具相关日志
Get-Content c:\xiangmu\deer-flow\logs\langgraph.log -Tail 100 | Select-String "master_writer|card_validator"

# 搜索错误
Select-String -Path c:\xiangmu\deer-flow\logs\langgraph.log -Pattern "ERROR|Exception|FAIL"
```

### 5.3 验证路径解析

```python
from my_tools.path_resolver import resolve_to_host_path

test_paths = [
    "/mnt/shared-data/book/测试小说",
    "book/测试小说",
    "./book/测试小说",
]

for p in test_paths:
    print(f"{p} -> {resolve_to_host_path(p)}")
```

### 5.4 验证 Tool 是否注册成功

检查 `config.yaml` 中：
1. `tool_groups` 段是否有对应工具组声明
2. `tools` 段是否有对应工具注册（name + group + use）
3. Agent 的 `config.yaml` 中 `tool_groups` 是否包含该工具组

---

## 六、常见问题排查

### 6.1 工具调用返回成功，但文件未创建

**原因**：没有使用 `resolve_to_host_path()` 转换路径，工具在沙箱虚拟路径上操作（不存在）。

**解决**：添加路径解析。

### 6.2 工具报"源路径超出允许范围"

**原因**：路径分隔符不一致导致 `startswith` 比较失败（Windows 特有 Bug）。

**解决**：统一使用正斜杠后再比较。

### 6.3 Agent 找不到 Tool

**原因**：Tool 注册到了 `config.yaml`，但 Agent 的 `config.yaml` 中没有引用该工具组。

**解决**：在 Agent 配置中添加对应的 `tool_groups`。

### 6.4 相对路径解析到错误位置

**原因**：相对路径应该基于 `/mnt/shared-data` 拼接，而不是 agent 的 workspace。

**解决**：使用 `_resolve_path()` 中的标准逻辑。

---

## 七、完整的 Tool 示例：master_writer

这是一个生产级别的自定义 Tool 示例，展示了路径解析、权限校验、日志记录的最佳实践。

完整代码见：[my_tools/master_writer.py](file:///c:/xiangmu/deer-flow/my_tools/master_writer.py)

核心功能：
- `create_dir`：创建目录（允许在小说项目目录下任意位置创建）
- `write_file`：写入文件（只允许写入 `03-状态` 目录）
- `move_file`：移动文件/文件夹（只允许在 `shared-data` 内移动）
- `rename_file`：重命名文件/文件夹（只允许在 `shared-data` 内重命名）

---

*文档创建时间：2026-05-06*
*适用版本：DeerFlow 二开项目*
