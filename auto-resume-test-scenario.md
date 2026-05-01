# 自动续传功能 - 模拟测试脚本

## 测试场景：验证自动续传是否能正确发送消息

### 前提条件
- novel_toc 已设置为 "/mnt/shared-data/novels/book/test"
- card.json 存在，内容：{ current_chapter: 2, target_chapters: 5 }
- 监控已启动

### 测试流程

```
时间线：

T0: AI 完成第 2 章写作，停止运行
    - isLoading: true -> false
    - 触发 onRunStopped()
    - 读取 card.json: current_chapter=2, target_chapters=5
    - 判断需要续传 (5 > 2)
    - 设置空闲超时定时器（假设 1 分钟）

T1: 1 分钟后，定时器触发
    - 再次读取 card.json（可能 AI 手动更新了进度）
    - 获取最新数据: latestCard
    - 检查是否仍需续传
    - 构建续传消息："请继续写第 3 章，一直写到第 5 章"
    - 调用 doSendMessage(prompt)
    - 消息被发送到对话中
    - AI 开始继续写作

T2: AI 完成第 3 章，停止运行
    - 再次触发 onRunStopped()
    - 读取 card.json: current_chapter=3, target_chapters=5
    - 继续设置定时器...

T3: AI 完成第 5 章，停止运行
    - 读取 card.json: current_chapter=5, target_chapters=5
    - 判断不需要续传 (5 <= 5)
    - 自动停止监控
```

### 核心验证点

1. **消息发送** - onRunStopped 中的 setTimeout 会触发 doSendMessage()
2. **消息内容** - 包含正确的章节信息（current_chapter + 1 到 target_chapters）
3. **实时数据** - 定时器触发时重新读取 card.json，确保使用最新进度
4. **重复检查** - 定时器触发后再次检查是否需要续传

### 代码路径

```
isLoading: true -> false
    ↓
useEffect (line 278-295)
    ↓
onRunStopped(rt, threadId) (line 284)
    ↓
检查 enabled, errorStage, novelToc (line 113-116)
    ↓
读取 card.json (line 119-124)
    ↓
判断是否需续传 (line 127)
    ↓
设置空闲超时定时器 (line 130)
    ↓
等待 timeoutMs 后
    ↓
重新读取 card.json (line 139-143)
    ↓
再次判断是否需续传 (line 146)
    ↓
构建续传消息 (line 148)
    ↓
调用 rt.doSendMessage(prompt) (line 150) ← 这就是发送到对话的方法
    ↓
消息进入对话队列，AI 开始继续写作
```

### 结论

代码逻辑确认：自动续传功能 **会** 自动发送消息给对话让对话继续。

关键代码：
- `rt.doSendMessage(prompt)` 在第 150 行被调用
- 这个方法在 page.tsx 中被初始化为：
  ```
  useCallback(async (msg: string) => {
    await sendMessage(threadId, { text: msg, files: [] });
  }, [sendMessage, threadId])
  ```
- sendMessage 会触发 AI 对话流程
