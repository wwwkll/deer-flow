# 修改记录 - 自动续传 v2（基于 novel_toc）

> 日期：2026-04-27
> 状态：开发中
> 相关人员：用户、AI助手

---

## 一、需求背景

自动续传功能（v1）已实现基本的事件驱动监控和防卡死机制，但存在一个问题：
- card.json 的读取路径是通过 `ls /book` 动态查找的，不够精确
- 项目中已有 `novel_toc` 全局变量记录了当前对话绑定的小说路径
- 应该直接使用 `novel_toc` 变量定位 card.json，更加精准可靠

---

## 二、变更内容

### 2.1 业务需求变更

**变更前**：
- 监控时通过 `ls /book` 找到第一个小说目录，读取其 card.json
- 如果目录下有多本书，可能读取错误的 card.json

**变更后**：
- 使用 `novel_toc` 全局变量（存储如 `/mnt/shared-data/novels/book/暗巷守护者`）
- 直接读取 `{novel_toc}/card.json`
- 监控面板显示当前监控的 card.json 路径（相对路径）
- 监控面板实时显示当前章节和目标章节数值

### 2.2 监控面板 UI 变更

新增显示内容：

```
┌─────────────────────────────────────────┐
│  监控配置                               │
├─────────────────────────────────────────┤
│  空闲超时时间：                          │
│  [____] 分钟                            │
│                                         │
│  续传消息：                             │
│  "请继续写第 N 章，一直写到第 M 章"       │
│                                         │
│  监控条件：                             │
│  target_chapters > current_chapter       │
│                                         │
│  ───────────────────────────────────── │
│  监控状态（实时）：                      │
│  card.json：/shared-data/novels/book/...│
│  当前章节：2                            │
│  目标章节：5                            │
│                                         │
│  [开始监控]  [取消]                     │
└─────────────────────────────────────────┘
```

### 2.3 监控中状态实时更新

当监控启用后，配置面板关闭，但在输入框区域显示实时状态：

```
┌──────────────────────────────────────┐
│  📡 监控中                            │
│  card.json：/shared-data/.../card.json│
│  进度：第 2/5 章                     │
└──────────────────────────────────────┘
```

---

## 三、技术实现

### 3.1 核心变更

**文件**：`frontend/src/core/api/sessions.ts`

**变更**：`getNovelCard()` 不再通过 `ls /book` 查找，而是：
1. 读取当前 thread 的 `novel_toc` 全局变量
2. 直接读取 `{novel_toc}/card.json`

**API 调用**：
```
GET /api/global-variables/thread/{thread_id}?key=novel_toc
→ 返回 novel_toc 值，如 "/mnt/shared-data/novels/book/暗巷守护者"

GET /api/threads/{thread_id}/fs/read?path={novel_toc}/card.json
→ 返回 card.json 内容
```

### 3.2 路径显示处理

监控面板显示相对路径，去掉 `/mnt/` 前缀：
- 原始路径：`/mnt/shared-data/novels/book/暗巷守护者`
- 显示路径：`/shared-data/novels/book/暗巷守护者`

### 3.3 实时状态获取

监控启用后，每 30 秒刷新一次 card.json，更新：
- 当前章节（current_chapter）
- 目标章节（target_chapters）
- card.json 路径

### 3.4 变更文件清单

| 文件 | 变更内容 |
|------|---------|
| `frontend/src/core/api/sessions.ts` | getNovelCard 改为使用 novel_toc |
| `frontend/src/hooks/use-auto-resume-monitor.ts` | 新增 card.json 状态追踪 |
| `frontend/src/components/workspace/input-box.tsx` | 监控面板新增路径和章节信息 |
| `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` | 传递 novel_toc 相关状态 |
| `frontend/src/app/workspace/chats/[thread_id]/page.tsx` | 传递 novel_toc 相关状态 |

---

## 四、全局变量依赖

**novel_toc** 存储格式：
```json
{
  "thread_id": "{thread_id}",
  "key": "novel_toc",
  "value": "/mnt/shared-data/novels/book/暗巷守护者"
}
```

**前提条件**：
- 用户在创建对话时已通过小说标签选择器选择了小说
- novel_toc 全局变量已正确存储
- card.json 存在于 novel_toc 目录下

---

## 五、风险与限制

1. **novel_toc 为空时**：如果对话未绑定小说标签，无法获取 novel_toc，监控无法启动
2. **card.json 不存在时**：读取失败，不中断监控，继续下次检查
3. **多小说场景**：一个对话只绑定一个 novel_toc，不存在多小说冲突

---

## 六、后续计划

1. 完整功能测试
2. 更新自动续传需求文档
3. 考虑增加手动切换监控的 card.json 路径功能（二期）

---

## 七、变更记录

| 日期 | 变更内容 | 操作人 |
|------|----------|--------|
| 2026-04-27 | 创建文档 | AI助手 |
| 2026-04-27 | 基于 novel_toc 改造 card.json 读取 | AI助手 |
| 2026-04-27 | 监控面板新增路径和章节信息显示 | AI助手 |
