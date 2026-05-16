# 修改记录 - 自动续传 v3（目标章节来源改为全局变量）

> 日期：2026-05-15
> 状态：已完成
> 相关人员：用户、AI助手

---

## 一、需求背景

自动续传功能（v2）从 card.json 读取目标章节，存在以下问题：
- card.json 可能不存在或数据不准确
- 目标章节应该由用户在启动监控时手动设定，而非依赖 card.json
- 用户停止对话时，监控不会自动停止
- 系统重启后，残留的监控状态变量可能导致异常

---

## 二、变更内容

### 2.1 目标章节来源变更

**变更前**：
- 从 `{novel_toc}/card.json` 读取 `target_chapters` 字段
- 依赖 card.json 文件存在且数据正确

**变更后**：
- 目标章节由用户在启动监控时手动输入
- 存储为对话级全局变量 `_monitor_target_chapters`
- 不再依赖 card.json 文件

### 2.2 新增对话级全局变量 `_monitor_target_chapters`

| 属性 | 值 |
|------|------|
| 变量名 | `_monitor_target_chapters` |
| 作用域 | 对话级（thread） |
| 类型 | 数字字符串（如 "50"） |
| llm_editable | false |
| 生命周期 | 启动监控时创建，停止监控/目标完成/系统重启时清除 |

**生命周期管理**：
- **创建时机**：用户启动监控时，将输入的目标章节号写入该变量
- **清除时机**：
  1. 侦测到目标完成（目标章节附近 5 个章节文件已存在）
  2. 用户手动停止监控
  3. 用户点击对话框停止按钮（同步停止监控）
  4. 系统重启时，后端自动清除所有对话的 `_monitor_enabled` 和 `_monitor_target_chapters`

### 2.3 监控配置弹窗新增目标写作章节输入框

**变更前**：
```
┌─────────────────────────────────────────┐
│  监控配置                               │
├─────────────────────────────────────────┤
│  空闲超时时间：                          │
│  [____] 分钟                            │
│                                         │
│  续传消息：...                           │
│  监控条件：...                           │
│                                         │
│  [取消]  [开始监控]                     │
└─────────────────────────────────────────┘
```

**变更后**：
```
┌─────────────────────────────────────────┐
│  监控配置                               │
├─────────────────────────────────────────┤
│  空闲超时时间：                          │
│  [____] 分钟                            │
│                                         │
│  目标写作章节：                          │
│  [____] （例如：50）                     │
│  写作完成的目标章节号，系统将监控到       │
│  该章节完成为止                          │
│                                         │
│  续传消息：...                           │
│  监控条件：...                           │
│                                         │
│  [取消]  [开始监控]                     │
└─────────────────────────────────────────┘
```

**开始监控按钮**：需要同时满足 `novel_toc` 已设置 且 `targetChapters > 0` 才可点击。

### 2.4 监控中实时状态显示变更

**变更前**：显示 card.json 路径
**变更后**：显示小说路径（novel_toc 去掉 /mnt 前缀）

```
┌─────────────────────────────────────────┐
│  监控状态                               │
├─────────────────────────────────────────┤
│  实时状态                               │
│  小说路径：/shared-data/novels/book/... │
│  目标章节：50                           │
│  最近五章识别：46 47 48 49 50           │
│  已完成：3 / 5                          │
│                                         │
│  [关闭]  [停止监控]                     │
└─────────────────────────────────────────┘
```

### 2.5 停止按钮同步停止监控

**变更前**：用户点击对话框中的停止按钮，只停止当前对话，监控继续运行
**变更后**：用户点击停止按钮时，同步停止监控

---

## 三、技术实现

### 3.1 前端核心变更

**文件**：`frontend/src/hooks/use-auto-resume-monitor.ts`

**主要变更**：
1. `MonitorConfig` 新增 `targetChapters` 字段
2. `MonitorState` 中 `cardPath` → `novelPath`，移除 `cardJsonExists`、`currentChapter`
3. `onRunStopped` 不再调用 `getNovelCard`，改为从 `rt.config.targetChapters` 读取
4. `startMonitor` 保存 `_monitor_target_chapters` 全局变量
5. `stopMonitor` 删除 `_monitor_target_chapters` 全局变量
6. 目标完成时删除 `_monitor_target_chapters`
7. 恢复监控时同时读取 `_monitor_target_chapters`
8. 章节刷新循环改为扫描文件 + 读取全局变量，不再读取 card.json
9. 移除 `getNovelCard` 导入

**新增常量**：
```typescript
const VAR_MONITOR_ENABLED = "_monitor_enabled";
const VAR_MONITOR_TARGET_CHAPTERS = "_monitor_target_chapters";
```

### 3.2 前端 UI 变更

**文件**：`frontend/src/components/workspace/input-box.tsx`

**主要变更**：
1. 监控配置弹窗新增"目标写作章节"输入框
2. 实时状态中 `card.json` → `小说路径`，使用 `monitorState.novelPath`
3. 开始监控按钮禁用条件：`!novelTocSet || !targetChapters || targetChapters <= 0`

### 3.3 页面组件变更

**文件**：
- `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`

**主要变更**：
- `handleStop` 中增加：如果监控启用，同步调用 `stopMonitor()`
- `handleStop` 移到 monitor hook 之后声明（避免变量前向引用）

### 3.4 后端变更

**文件**：`backend/packages/harness/deerflow/global_variables/db_base.py`

新增抽象方法：
```python
def delete_by_key_across_threads(self, key: str) -> int:
    """Delete a variable by key across all threads. Returns number of deleted rows."""
```

**文件**：`backend/packages/harness/deerflow/global_variables/db_sqlite.py`

新增实现：
```python
def delete_by_key_across_threads(self, key: str) -> int:
    # DELETE FROM global_variables WHERE key = ? AND thread_id IS NOT NULL
```

**文件**：`backend/packages/harness/deerflow/global_variables/db_postgres.py`

新增实现：
```python
def delete_by_key_across_threads(self, key: str) -> int:
    # DELETE FROM global_variables WHERE key = %s AND thread_id IS NOT NULL
```

**文件**：`backend/packages/harness/deerflow/global_variables/storage.py`

新增门面方法：
```python
def delete_by_key_across_threads(self, key: str) -> int:
    return self._db.delete_by_key_across_threads(key)
```

**文件**：`backend/app/gateway/app.py`

在 lifespan 启动时添加清理逻辑：
```python
storage = get_storage()
n1 = storage.delete_by_key_across_threads("_monitor_enabled")
n2 = storage.delete_by_key_across_threads("_monitor_target_chapters")
```

### 3.5 类型定义变更

**文件**：`frontend/src/core/api/sessions.ts`

- `NovelCardData` 类型从 `use-auto-resume-monitor.ts` 移至 `sessions.ts` 本地定义
- `getNovelCard` 函数保留（其他功能可能使用），但监控功能不再依赖

### 3.6 变更文件清单

| 文件 | 变更内容 |
|------|---------|
| `frontend/src/hooks/use-auto-resume-monitor.ts` | 目标章节来源改为全局变量，新增 `_monitor_target_chapters` 管理 |
| `frontend/src/components/workspace/input-box.tsx` | 新增目标写作章节输入框，更新实时状态显示 |
| `frontend/src/app/workspace/chats/[thread_id]/page.tsx` | 停止按钮同步停止监控 |
| `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` | 停止按钮同步停止监控 |
| `frontend/src/core/api/sessions.ts` | `NovelCardData` 类型本地化 |
| `frontend/tests/unit/hooks/auto-resume-monitor.test.ts` | 更新断言匹配当前 prompt 文本 |
| `backend/packages/harness/deerflow/global_variables/db_base.py` | 新增 `delete_by_key_across_threads` 抽象方法 |
| `backend/packages/harness/deerflow/global_variables/db_sqlite.py` | 新增 `delete_by_key_across_threads` SQLite 实现 |
| `backend/packages/harness/deerflow/global_variables/db_postgres.py` | 新增 `delete_by_key_across_threads` PostgreSQL 实现 |
| `backend/packages/harness/deerflow/global_variables/storage.py` | 新增 `delete_by_key_across_threads` 门面方法 |
| `backend/app/gateway/app.py` | 启动时清理监控相关全局变量 |

---

## 四、全局变量依赖

### _monitor_enabled（已有）

```json
{
  "key": "_monitor_enabled",
  "value": "true",
  "description": "Auto-resume monitor enabled state",
  "llm_editable": false
}
```

### _monitor_target_chapters（新增）

```json
{
  "key": "_monitor_target_chapters",
  "value": "50",
  "description": "监控目标章节",
  "llm_editable": false
}
```

**前提条件**：
- 用户在创建对话时已通过小说标签选择器选择了小说
- novel_toc 全局变量已正确存储

---

## 五、风险与限制

1. **novel_toc 为空时**：如果对话未绑定小说标签，无法获取 novel_toc，监控无法启动
2. **目标章节未设置时**：开始监控按钮禁用，必须输入目标章节
3. **系统重启**：所有 `_monitor_enabled` 和 `_monitor_target_chapters` 变量会被清除，监控不会自动恢复
4. **card.json 不再依赖**：监控功能不再读取 card.json，但 `getNovelCard` 函数保留供其他功能使用

---

## 六、测试验证

### 前端测试

```
✅ 24 passed (auto-resume-monitor.test.ts)
```

| 测试项 | 说明 | 状态 |
|--------|------|------|
| buildResumePrompt | 生成正确的续传提示词 | ✅ |
| hasRequiredChapters | 判断目标章节是否完成 | ✅ |
| shouldResume | 判断是否需要续传 | ✅ |
| detectErrorPattern | 反卡死错误模式检测 | ✅ |
| constants | 常量值验证 | ✅ |

### 后端测试

```
✅ 12 passed (test_global_variables_storage.py)
```

### 集成测试

| 测试项 | 说明 | 状态 |
|--------|------|------|
| delete_by_key_across_threads | 跨对话删除变量，保留其他变量 | ✅ |
| TypeScript 编译 | 无类型错误 | ✅ |
| ESLint 检查 | 无 lint 错误 | ✅ |

---

## 七、变更记录

| 日期 | 变更内容 | 操作人 |
|------|----------|--------|
| 2026-04-27 | 创建文档（v2） | AI助手 |
| 2026-04-27 | 基于 novel_toc 改造 card.json 读取 | AI助手 |
| 2026-04-27 | 监控面板新增路径和章节信息显示 | AI助手 |
| 2026-05-15 | v3：目标章节来源改为全局变量 | AI助手 |
| 2026-05-15 | 新增 `_monitor_target_chapters` 全局变量及生命周期管理 | AI助手 |
| 2026-05-15 | 监控弹窗新增目标写作章节输入框 | AI助手 |
| 2026-05-15 | 停止按钮同步停止监控 | AI助手 |
| 2026-05-15 | 后端启动时清理监控变量 | AI助手 |
