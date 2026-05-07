# master_writer 路径权限 Bug 修复记录

**日期**: 2026-05-06
**Bug ID**: MW-001
**开发者**: AI Assistant
**严重级别**: 高（导致所有移动/重命名操作被误拒绝）

---

## 一、Bug 描述

`master_writer` 工具的 `move_file` 和 `rename_file` 操作，在实际使用时会被误报 "源路径超出允许范围"，即使操作的文件完全在 `shared-data` 目录内。

### 现象

```yaml
# agent 反馈
master_writer 虽然描述说支持"移动小说项目目录下的任意文件或文件夹"，
但实际上移动操作被拒绝，报错是"源路径超出允许范围"。
```

| 操作 | 描述中说支持 | 实际结果 |
|------|-------------|----------|
| 写入 03-状态 目录文件 | ✅ | ✅ 正常工作 |
| 创建目录 | ✅ | ✅ 正常工作 |
| 移动文件 | ✅ | ❌ 报"源路径超出允许范围" |
| 重命名文件 | ✅ | ❌ 报"源路径超出允许范围" |

### 日志证据

```
13:40:43 - [master_writer] action=move_file, input_path=/mnt/shared-data/book/.../待办事项.md
13:40:46 ~ 13:42:44 - Agent 反复尝试 20+ 次不同路径格式
13:40:55 - Summarization failed (Connection error) - 多次重试导致 LLM API 超时
13:41:01 - Injecting 4 placeholder ToolMessage(s) for dangling tool calls
```

**一个简单移动文件任务耗时近 15 分钟**，因为 Agent 不断重试不同路径格式。

---

## 二、根因分析

### Bug 位置

[my_tools/master_writer.py#L61-L72](file:///c:/xiangmu/deer-flow/my_tools/master_writer.py#L61-L72)

### 问题代码

```python
def _is_within_shared_data(file_path: str) -> bool:
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    target = Path(file_path.replace("\\", "/")).resolve()
    return str(target).startswith(shared_data)
```

### 核心问题：Windows 路径分隔符不一致

1. `resolve_to_host_path()` 返回的主机路径是正斜杠：
   ```
   C:/xiangmu/deer-flow/backend/.deer-flow/shared-data
   ```

2. 但 `Path.resolve()` 在 Windows 上返回**反斜杠**：
   ```
   C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\测试\03-状态\test.md
   ```

3. `str(target)` 没有再做 `replace("\\", "/")`，导致 `startswith` 比较失败：
   ```
   "C:\xiangmu\..." 不匹配 "C:/xiangmu/..."
   ```

### 验证脚本

```python
from pathlib import Path
file_path = r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\测试\03-状态\test.md"
shared_data = "C:/xiangmu/deer-flow/backend/.deer-flow/shared-data"
target = str(Path(file_path.replace("\\", "/")).resolve())
print(f"target:      {target}")  # C:\xiangmu\...
print(f"startswith?  {target.startswith(shared_data)}")  # False ← Bug!
```

### 为什么 write_file 不受影响？

因为 `_is_allowed_path()` 只检查 `path_obj.parent.name == "03-状态"`，不涉及跨目录 `startswith` 比较。

### 其他工具排查

| 工具 | 有 Path.resolve() | 有 startswith 安全校验 | 有同类 bug |
|------|-------------------|------------------------|-----------|
| master_writer | ✅ | ✅ | ✅ 已修复 |
| novel_reader | ❌ | ❌ | - |
| card_validator | ❌ | ❌ | - |
| context_assembler | ❌ | ❌ | - |
| ai_trace_detector |  | ❌ | - |
| post_write_validator | ❌ | ❌ | - |

---

## 三、修复方案

### 修复代码

```python
def _is_within_shared_data(file_path: str) -> bool:
    """检查路径是否在 shared-data 目录内（防止路径逃逸）。

    Args:
        file_path: 已解析的主机路径

    Returns:
        是否在 shared-data 目录内
    """
    shared_data = resolve_to_host_path("/mnt/shared-data").replace("\\", "/")
    # 修复: Path.resolve() 在 Windows 上返回反斜杠，需要统一转换
    target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
    return target.startswith(shared_data)
```

### 修改内容

仅一行代码改动：

```diff
-     target = Path(file_path.replace("\\", "/")).resolve()
-     return str(target).startswith(shared_data)
+     target = str(Path(file_path.replace("\\", "/")).resolve()).replace("\\", "/")
+     return target.startswith(shared_data)
```

---

## 四、测试验证

### 测试环境

- Python 3.12 (backend/.venv)
- Windows 11
- 配置: `backend/.deer-flow/shared-data`

### 测试用例

```python
test_cases_within = [
    # 正常路径 - 应在 shared-data 内
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\测试小说\03-状态\test.md", True),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\测试小说\01-规划\card.md", True),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\03-状态\test.md", True),
    ("C:/xiangmu/deer-flow/backend/.deer-flow/shared-data/book/测试/03-状态/test.md", True),
    (r"C:\xiangmu\deer-flow\backend\.deer-flow\shared-data\book\女帅回归：从赐死到女帝\03-状态\待办事项.md", True),
    # 非法路径 - 应在 shared-data 外
    (r"C:\windows\system32\cmd.exe", False),
    (r"C:\xiangmu\deer-flow\backend\config.yaml", False),
]
```

### 测试结果

```
=== _is_within_shared_data 测试 ===
  [PASS] ... -> True (expected: True)
  [PASS] ... -> True (expected: True)
  [PASS] ... -> True (expected: True)
  [PASS] ... -> True (expected: True)
  [PASS] ... -> True (expected: True)
  [PASS] ... -> False (expected: False)
  [PASS] ... -> False (expected: False)

=== _is_allowed_path 测试 (write_file 权限) ===
  [PASS] ... -> True (expected: True)
  [PASS] ... -> False (expected: False)

全部通过!
```

---

## 五、影响范围

| 项目 | 影响 |
|------|------|
| move_file | 修复后可正常移动 shared-data 内任意文件/文件夹 |
| rename_file | 修复后可正常重命名 shared-data 内任意文件/文件夹 |
| write_file | 无影响（本来就没受影响） |
| create_dir | 无影响（本来就没受影响） |
| 其他工具 | 无影响（无同类 bug） |

---

## 六、注意事项

1. **这是一个跨平台兼容性问题**：只在 Windows 上触发，Linux/macOS 的 `Path.resolve()` 默认返回正斜杠，不会受影响。
2. **无需重启服务**：这是一个纯 Python 工具函数修复，下次 Agent 调用时即生效。
3. **Agent 无需修改**：修复后 Agent 可以继续使用 `/mnt/shared-data/...` 格式的虚拟路径。

---

## 七、经验总结

### 教训

**Windows 路径处理时，务必统一分隔符后再比较**：

```python
# ❌ 错误写法（Windows 上会失败）
target = str(Path(file_path).resolve())
return target.startswith(base_dir)

# ✅ 正确写法
target = str(Path(file_path).resolve()).replace("\\", "/")
base_dir = base_dir.replace("\\", "/")
return target.startswith(base_dir)
```

### 最佳实践

在处理跨平台路径比较时，统一使用正斜杠格式，避免依赖操作系统的默认行为。
