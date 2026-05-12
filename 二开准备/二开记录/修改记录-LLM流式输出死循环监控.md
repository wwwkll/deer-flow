# LLM 流式输出死循环监控（Loop Guard）开发记录

**日期**: 2026-05-12
**功能**: 检测 LLM 流式输出中的死循环并自动终止
**开发者**: AI Assistant
**版本**: v1.1
**更新历史**:
- v1.0：基础检测（content 字段，Layer A + Layer B）
- v1.1：补全 tool_call.args / content-block-list / emoji 流的检测盲点

---

## 一、需求背景

DeerFlow 二开版本经常需要接入**本地小模型**（Qwen-1.8B/4B、Yi-Lite、MiniCPM、vLLM/Ollama 部署的 7B 等）。这些模型在某些 prompt 下会陷入死循环——一直生成相同/相似内容直到 `max_tokens` 才停下来。

实际生产中遇到两种典型的死循环形态：

**形态 A — 完全重复**：
```
好的好的好的好的好的好的好的好的好的好的好的好的好的……
```
模型反复输出相同的几个字。

**形态 B — 模板变体**：
```
今天是周一，明天是周二，三天后是周三，四天后是周四，五天后是周五……
你可以问问题，你可以查资料，你可以写代码，你可以做翻译……
```
文字内容不同，但句式骨架完全一样，永远停不下来。

两种形态都会让用户等待几分钟、消耗大量 token，且无法被现有的 `LoopDetectionMiddleware`（只检测工具调用循环）捕获。

### 目标

1. **自动检测**：流式输出过程中实时监控，不依赖人工干预
2. **优雅终止**：检测到循环后立即结束流，但**保留已生成的部分**
3. **两种形态都能抓**：既要抓 A 类完全重复，也要抓 B 类模板变体
4. **不误判正常长文**：散文、列表、排比句不能被错误打断
5. **默认开启**：用户无需修改配置就能用

---

## 二、实现方案

### 2.1 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│  deerflow.models.factory.create_chat_model()                          │
│  ├─ 创建模型实例（如 ChatOpenAI / VllmChatModel / PatchedChatDeepSeek）  │
│  ├─ 附加 tracing callbacks                                            │
│  └─ wrap_model_with_loop_guard()  ← 自动包裹                          │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  动态子类化（model.__class__ = FooWithLoopGuard）                       │
│  ├─ LoopGuardMixin 覆盖 _stream / _astream                            │
│  └─ 失败时回退到实例级 monkey-patch                                    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  StreamLoopDetector（每次调用独立实例，状态不跨调用）                    │
│  ├─ Layer A：n-gram 后缀重复（抓"好的好的..."）                          │
│  └─ Layer B：子句骨架相似度（抓"今天周一明天周二..."）                    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ 命中循环
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  优雅终止                                                              │
│  ├─ yield 当前 chunk（保留已输出内容）                                  │
│  ├─ yield 终止提示 chunk（finish_reason=loop_detected）                │
│  └─ return（生成器结束，下游收到完整的 SSE 流）                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 检测算法详解

#### Layer A — 后缀 n-gram 重复检测

**思路**：模型陷入死循环时，"最近输出的若干字符"必然就是循环体的一部分。所以取尾部 N 个字符作为"嫌疑模式"，数它在最近缓冲区里出现几次，超过阈值就判定循环。

**具体步骤**（伪代码）：

```python
for n in [6, 12, 24, 48]:          # 同时检查多个长度
    if len(tail) < n * max_repeats:
        continue                    # 缓冲区还不够大
    suffix = tail[-n:]              # 最近 n 个字符
    count = tail.count(suffix)      # 非重叠出现次数
    if count >= max_ngram_repeats:  # 默认 4 次
        return "loop detected"
```

**为什么用多个 n**：
| n | 抓的场景 |
|---|---|
| 6 | "好的好的好的" 这种 1-3 字短语循环 |
| 12 | "我可以帮你做这个" 这种短句循环 |
| 24 | "请告诉我您的具体需求好的好的好的" 这种半句循环 |
| 48 | 整段话级别的循环 |

**特殊处理**：纯单字符病态情况（"aaaaa..."）只允许最小 n 命中，避免重复打分。

#### Layer B — 子句骨架相似度检测

**思路**：模板变体循环（"今天周一/明天周二"）每条文字都不同，但**结构相似**。我们把缓冲区按标点切成子句，看最近 K 条之间的相似度，相似条数过多就判定循环。

**具体步骤**：

```python
# 1. 切分子句（按 。！？，；,;.!?\n）
clauses = split_by_punctuation(tail)
window = clauses[-8:]               # 最近 8 条子句

# 2. 拿最新子句和窗口内每条比较
latest = window[-1]
similar = 1                          # 自己算一条
for prev in window[:-1]:
    # 混合相似度：取字符 bigram Dice 和字符集合 Dice 的最大值
    sim_bigram = dice(bigrams(latest), bigrams(prev))
    sim_char = dice(set(latest), set(prev))
    if max(sim_bigram, sim_char) >= 0.5:
        similar += 1

if similar >= max_clause_repeats:    # 默认 4 条
    return "loop detected"
```

**为什么用混合相似度**：

这是开发过程中**踩过的关键坑**。原始方案只用 bigram Dice，但发现这类场景漏报：

```
你可以问问题，你可以查资料，你可以写代码，你可以做翻译
```

| 对比 | bigram 交集 | Dice | 命中？ |
|---|---|---|---|
| `你可以问问题` vs `你可以查资料`（bigram） | `{你可, 可以}` 2/5 | **0.40** | ❌ 漏报 |
| 同样两条（character 集合） | `{你, 可, 以}` 3/5 | **0.55** | ✅ |

只换尾词的列表型循环，bigram 重叠很少（只有"你可"、"可以"），但字符重叠很高。**取两种相似度的较大值**就能同时抓住：
- "今天是周一" vs "明天是周二"：bigram Dice 0.5，char Dice 0.6 → 命中
- "你可以问问题" vs "你可以查资料"：bigram Dice 0.4，char Dice 0.55 → 命中

而长篇散文（每句话词汇都不一样）两种相似度都很低，不会误判。

### 2.3 优雅终止设计

检测到循环后，我们**不**抛异常（会被 `LLMErrorHandlingMiddleware` 误判为 provider 错误），而是：

```python
# In LoopGuardMixin._astream
async for chunk in super()._astream(...):
    if detected:
        yield chunk                                 # ① 保留触发循环的最后一个 chunk
        yield _build_loop_break_chunk(result)       # ② 追加终止提示
        return                                      # ③ 生成器干净结束
    yield chunk
```

终止提示 chunk 的样子：

```python
AIMessageChunk(
    content="\n\n[deerflow] 检测到模型输出循环（clause），已自动终止：templated clause '今天是周一' repeated 5 times in last 8 clauses",
    response_metadata={
        "finish_reason": "loop_detected",
        "deerflow_loop_detected": {
            "layer": "clause",
            "reason": "...",
            "repeat_count": 5,
        }
    }
)
```

下游（gateway / 前端）正常拿到完整的 SSE 流，用户能看到模型停下的原因。

---

## 三、新增和修改的文件

### 新增（5 个）

| 文件 | 说明 |
|---|---|
| `backend/packages/harness/deerflow/models/loop_detector.py` | 算法核心：`StreamLoopDetector` + `LoopDetectorConfig` + Dice / bigram 辅助函数 |
| `backend/packages/harness/deerflow/models/loop_guard.py` | 模型包装器：`wrap_model_with_loop_guard()`、`LoopGuardMixin`、实例级 monkey-patch 回退路径 |
| `backend/packages/harness/deerflow/config/loop_guard_config.py` | Pydantic 用户配置 schema：`LoopGuardConfig`，带 `to_detector_config()` 转换方法 |
| `backend/tests/test_loop_detector.py` | 算法单元测试（17 个用例，覆盖 Layer A / Layer B / 负样本 / 开关 / 辅助函数） |
| `backend/tests/test_loop_guard.py` | 集成测试（7 个用例，覆盖同步流 / 异步流 / 幂等 / 配置更新 / 禁用透传） |

### 修改（3 个）

| 文件 | 改动 |
|---|---|
| `backend/packages/harness/deerflow/config/app_config.py` | 注册 `loop_guard: LoopGuardConfig` 字段到 `AppConfig`，默认 `default_factory=LoopGuardConfig` |
| `backend/packages/harness/deerflow/models/factory.py` | `create_chat_model()` 末尾，在返回前调用 `wrap_model_with_loop_guard()`，包了 try/except 保证包裹失败不会阻断模型创建 |
| `config.example.yaml` | 新增 `loop_guard` 配置段（带详细中文注释和调参指南）；`config_version` 从 8 bump 到 9 |

---

## 四、配置使用

### 4.1 默认即启用

`AppConfig.loop_guard` 字段的默认值是 `LoopGuardConfig()`，其中 `enabled=True`。所以 **重启项目就生效**，无需任何配置修改。

### 4.2 关闭功能

如果某些场景下需要关闭（比如调试模型本身的输出问题），在 `config.yaml` 加：

```yaml
loop_guard:
  enabled: false
```

### 4.3 调参

完整可调参数（默认值）：

```yaml
loop_guard:
  enabled: true
  # 缓冲与节流
  max_tail_chars: 2000          # 滚动窗口字符数
  check_interval_chars: 60      # 每 60 个新字符跑一次检测
  min_content_length: 200       # 累计 200 字之前不检测（避免短回复误判）
  # Layer A
  ngram_sizes: [6, 12, 24, 48]
  max_ngram_repeats: 4
  # Layer B
  clause_window: 8
  max_clause_repeats: 4
  clause_similarity_threshold: 0.5
  clause_min_length: 3
  clause_max_length: 80
```

**调参建议**：

| 症状 | 调整方向 |
|---|---|
| 该停的没停（漏报） | `max_ngram_repeats` / `max_clause_repeats` 调小（4 → 3）；`min_content_length` 调小（200 → 100） |
| 正常长文也被打断（误报） | 上述两个调大（4 → 6）；`clause_similarity_threshold` 调高（0.5 → 0.6） |
| 完全不需要 | `enabled: false` |

---

## 四点五、覆盖矩阵（重要）

死循环可能出现在很多场景，下面一张表说清楚**哪些被覆盖、哪些天然不会出问题、哪些是显式不覆盖**。

### 4.5.1 按"调用入口"维度

DeerFlow 项目中**所有** LLM 调用都集中在 `deerflow.models.create_chat_model()` 这一个工厂函数。loop guard 在工厂函数末尾包裹模型，所以下表所有入口**自动覆盖**：

| 调用入口 | 用途 | 包裹方式 |
|---|---|---|
| `lead_agent/agent.py` | 主对话 agent | ✅ 自动 |
| `subagents/executor.py` | 子任务（`task` 工具） | ✅ 自动 |
| `middlewares/title_middleware.py` | 自动生成对话标题 | ✅ 自动 |
| `agents/memory/updater.py` | 记忆事实抽取 | ✅ 自动 |
| `middlewares/summarization_middleware.py` | 长对话摘要 | ✅ 自动 |
| `skills/security_scanner.py` | 技能安全扫描 | ✅ 自动 |
| `client.py` | 直连 CLI 客户端 | ✅ 自动 |

**结论**：项目里**只要走 `create_chat_model`，就被监控**。这是单一入口的最大好处。

> 注：DeerFlow 没有独立的 workflow 引擎——"工作流"实际上是通过 `task` 工具调用预定义子 agent 实现的（见 `lead_agent` 的 workflow prompt），底层也走 `create_chat_model`。

### 4.5.2 按"输出去向"维度

模型生成的内容可能去到不同的地方，每种都被覆盖：

| 输出去向 | 在 LangChain 流中的位置 | 实际场景 | 是否覆盖 |
|---|---|---|---|
| **对话回复** | `chunk.message.content` (str) | 普通聊天回复 | ✅ |
| **多模态/思考** | `chunk.message.content` (list of dict) | Anthropic thinking、Vertex Gemini | ✅ |
| **写文件 / 工具调用** | `chunk.message.tool_call_chunks[i].args` | `write_file(content="...")` 的 content 卡死 | ✅ |
| **子任务消息** | 子 agent 自己的流 | task 工具内部 LLM 死循环 | ✅ 自动 |
| **结构化输出** | tool_call args（同上） | `with_structured_output()` | ✅ |
| **Subagent 内 tool 调用** | 子任务的 tool_call_chunks | 子任务自己写文件死循环 | ✅ |
| **非流式调用 `invoke()`** | `_generate` / `_agenerate` | 一次性返回，没有流可拦截 | ⚠️ 不覆盖（见下方说明） |

**关于不覆盖的 `invoke()`**：
- 死循环在非流式调用下不算"循环"——它就是一次性返回的长文本，loop guard 设计上只管流式
- 实际损失：模型一直跑到 `max_tokens` 才返回，浪费 token，但 gateway 上能看到请求完成时间和 token 计数
- 这种调用在本项目里很少（lead_agent、subagent、middleware 都用流式），影响面小
- 如果以后真要管，需要在 `_generate` 上加超时和 token 异常增长报警，但不是 loop guard 的职责

### 4.5.3 按"字符内容"维度

| 字符类型 | 算法处理 | 测试用例 |
|---|---|---|
| ASCII / 拉丁字母 | str.count 直接处理，Dice 用字符集合/bigram | `test_detects_english_phrase_loop` |
| 中文（含全角标点） | 同上，每个汉字是 1 个 codepoint | `test_detects_short_phrase_exact_loop` 等多个 |
| Emoji（单 codepoint，如 👍） | 视为单字符，n-gram 算法天然兼容 | `test_loop_in_emoji_only_stream_is_detected` |
| 复合 emoji（多 codepoint，如 👨‍👩‍👧 / 👋🏻） | 拆成多个 codepoint 不影响 n-gram 匹配 | 间接覆盖 |
| 中英混排 + emoji | 混合循环也能抓 | `test_loop_in_mixed_emoji_phrase_is_detected` |
| 纯空白 / 换行 | n-gram 检测时跳过纯空白后缀 | 算法内置 |

**为什么 emoji 不需要特殊处理**：Python 的字符串是 Unicode codepoint 序列，`str.count` 和 slice 都是 codepoint 级操作。`"👍👍👍👍👍👍".count("👍👍") == 3`。算法不在乎一个 codepoint 是 ASCII 还是 emoji，所以**emoji 天然支持**。

### 4.5.4 显式不在覆盖范围内的场景

| 场景 | 为什么不覆盖 | 替代方案 |
|---|---|---|
| 模型完全不流式（`invoke()`） | 没有 chunk 序列可拦截 | 用 `max_tokens` 限制 + 超时机制 |
| 工具调用循环（LLM 反复调用同一工具） | 不是输出循环，是工具循环 | 已有 `LoopDetectionMiddleware` 处理 |
| Agent 状态机循环（LangGraph 节点死循环） | 是 graph 级别的循环 | LangGraph 自带 `recursion_limit` 防护 |
| 内容语义重复但句式不同 | 算法基于 n-gram + 字符相似度，抓不到完全异构的语义循环 | 后续可加 embedding-based 检测层 |
| HTTP 长连接断开后的流恢复 | 第二段流是新的检测器实例，没有上下文 | 不是问题——重连后的内容如果还在循环，新流会重新检测到 |

---

## 五、技术决策

### 5.1 为什么用动态子类化而不是回调？

LangChain 的 `BaseCallbackHandler.on_llm_new_token` 看起来是天然的接入点，但**回调异常默认会被吞掉**（除非 `raise_error=True`），无法可靠地停止流。

而 `model._stream` / `_astream` 是流的生成器入口，直接覆盖它能保证：
1. 异常 / 提前 return 都能可靠生效
2. 可以**保留已输出的 chunk**（callback 介入时 chunk 已发出）
3. 不依赖 LangChain 的回调内部实现

### 5.2 为什么用动态子类化而不是包装类？

如果我们写一个 `LoopGuardChatModel(BaseChatModel)` 包装类持有内部模型，会遇到：
- 所有 `bind_tools`、`with_structured_output`、`with_retry` 等方法都得手动转发
- `isinstance(model, ChatOpenAI)` 这类判断会失效
- pydantic v2 字段都得重新声明

**动态子类化**`type("FooWithLoopGuard", (LoopGuardMixin, Foo), {})` 让 MRO 解决所有问题：原类的所有字段、方法、`isinstance` 全部保留，只多了 mixin 覆盖的 `_stream` / `_astream`。

### 5.3 为什么相似度用 `max(bigram_dice, char_dice)`？

这是测试驱动出来的（首轮测试 `test_detects_templated_listing_loop` 失败）。详见 2.2 节"为什么用混合相似度"。

**单 bigram**：抓有序结构（"今天是周一" vs "明天是周二"），但漏掉只换尾词的场景。
**单 char**：抓字符共享（"你可以X题"系列），但可能误判常用字共现（"我的猫" vs "我的车" → 0.33，安全）。
**取最大**：双重保险，互补抓得更全，且不会显著增加误判（因为正常散文两种相似度都低）。

### 5.4 为什么避免循环导入？

最初 `loop_guard_config.py` 直接 `from deerflow.models.loop_detector import LoopDetectorConfig`。但启动时：

```
deerflow.config.app_config
  → loop_guard_config
    → deerflow.models.loop_detector
      → deerflow.models.__init__
        → factory.py
          → deerflow.config.get_app_config  ← 此时 config 模块还没完成初始化
```

会触发 `ImportError: cannot import name 'get_app_config' from partially initialized module`。

**解决**：`loop_guard_config.py` 用 `TYPE_CHECKING` 守卫顶层 import，在 `to_detector_config()` 方法内部做延迟 import。运行时才触发，那时模块都已加载完毕。

### 5.5 为什么动态生成的类要缓存？

每次 `wrap_model_with_loop_guard` 都 `type(...)` 生成新类会泄露内存。用 `_GUARDED_CLASS_CACHE: dict[type, type]` 按 base class 缓存，同一个原始类只生成一次 mixin 子类。

---

## 六、测试结果

```
========================== 29 passed in 0.27s ==========================
```

### 6.1 覆盖的循环类型（正向用例）

| 类型 | 例子 | 命中层 |
|---|---|---|
| 短语完全重复 | `好的好的好的好的好的好的好的好的` | Layer A (n=6) |
| 长句完全重复 | `我是一个智能助手帮你...我是一个智能助手帮你...` | Layer A (n=12+) |
| 英文短语重复 | `I am sorry I am sorry I am sorry...` | Layer A |
| 单字符病态 | `aaaaaaaaaaaaa...` | Layer A (smallest n) |
| 模板变体（数字尾词） | `今天是周一，明天是周二，三天后是周三...` | Layer B (bigram Dice) |
| 模板变体（动词尾词） | `你可以问问题，你可以查资料，你可以写代码...` | Layer B (char Dice) |
| **工具调用 args 循环** | `write_file(content="好的好的好的...")` | Layer A，从 tool_call_chunks 提取 |
| **纯 Emoji 循环** | `👍👍👍👍👍👍👍👍...` | Layer A（codepoint 级） |
| **混合 Emoji + 文本** | `好的👍好的👍好的👍...` | Layer A |
| **Content Block List 循环** | Anthropic thinking 模式下的 `[{"type":"text",...}]` 列表里循环 | Layer A，从 content list 提取 |

### 6.2 不会误判（负向用例）

| 场景 | 测试结果 |
|---|---|
| 长篇正常散文 | ✅ 不误判 |
| "他XX...他YY...他ZZ" 排比句 | ✅ 不误判 |
| 短回复（< 200 字） | ✅ 预热阈值保护，不参与检测 |
| 同主题但用词不同的列举 | ✅ 不误判 |

### 6.3 开发中踩的 3 个坑

**坑 1：Layer B 算法对"只换尾词"的列表漏报**
- 首轮测试 `test_detects_templated_listing_loop` FAIL：`detected=False`
- 原因：单字尾词变化导致 bigram 重叠太少（只共享前缀 bigram）
- 修复：算法改用 `max(bigram_dice, char_dice)` 混合相似度

**坑 2：异步流的截断断言写错了**
- 首轮测试 `test_async_stream_aborts_on_templated_loop` FAIL：`assert 206 < 180`
- 原因：终止提示「`[deerflow] 检测到...`」本身 80+ 字符，让 aborted 总长度反而比原始流大
- 修复：断言改成按 chunk 数判断截断（`len(collected[:-1]) < len(chunks)`），而不是按字符数

**坑 3：写文件场景循环抓不到（v1.1 修复）**
- v1.0 只看 `chunk.message.content`，但模型调用 `write_file(content="...")` 时，
  循环的 content 实际上走的是 `chunk.message.tool_call_chunks[i].args`
  ——一个独立字段，content 在这种 chunk 里是空字符串
- 表现：用户报告"小模型写文件时还是会卡死"
- 修复：扩展 `_extract_text`，把 content（str 或 list）+ 所有 tool_call_chunks 的 args
  **合并送给同一个检测器**。理由：一次 LLM 调用里模型要么在说话要么在写参数，
  二者合流不会冲突，且共用 buffer 能保证跨字段的循环（极端情况）也能抓到

---

### 6.4 最终全量验收

为防止改动破坏其他已有功能，跑了一次后端全量测试：

```
========================== 2143 passed, 21 skipped, 10 failed in 241.60s ==========================
```

- **新增/修改相关的测试 100% 通过**（`test_loop_detector.py` 17 个、`test_loop_guard.py` 12 个、`test_model_factory.py`、`test_app_config_reload.py`、`test_config_version.py`、`test_lead_agent_*.py`、`test_llm_error_handling_middleware.py`、现有的 `test_loop_detection_middleware*` 全过）
- **10 个失败用例与本改动无关**：全部在 `test_local_sandbox_provider_mounts.py`（7 个）和 `test_sandbox_search_tools.py`（3 个），根因是 Windows 平台路径分隔符差异、缺少符号链接权限、缺少某些外部可执行文件——属于 sandbox 模块在 Windows 下的已知问题，本改动没有触碰这些代码路径

---

## 七、运行时观察

当循环被检测到时，`logs/langgraph.log` 会出现如下警告：

```
WARNING deerflow.models.loop_guard:loop_guard.py:183
LoopGuard: terminating async stream — templated clause '今天是周一' repeated 5 times in last 8 clauses (Dice ≥ 0.5) (total chars=96)
```

前端 / SSE 流的最后一个 chunk 会带：
- `finish_reason: "loop_detected"`
- `response_metadata.deerflow_loop_detected`：包含 `layer` / `reason` / `repeat_count`

---

## 八、影响范围

| 范围 | 影响 |
|---|---|
| 现有 chat model 行为 | 默认开启监控；正常对话**不受影响**（保守阈值） |
| 已有的 `LoopDetectionMiddleware`（工具调用循环检测） | 互不干扰，处理的是不同维度的循环 |
| `LLMErrorHandlingMiddleware`（错误重试） | 不会误触发，因为 loop guard 不抛异常 |
| `TokenUsageMiddleware`（token 计数） | 不受影响，被截断的输出仍然按 chunk 计数 |
| 性能 | 每 60 字符跑一次检测，开销 < 1ms，相对 LLM 延迟可忽略 |
| 内存 | 每次调用一个 ~2KB 的 tail 缓冲，调用结束自动释放 |

---

## 九、回退方案

如果出现意外问题，三种回退方案任选其一：

1. **配置关闭**（最快）：在 `config.yaml` 加 `loop_guard: { enabled: false }`，重启即可
2. **factory 跳过**：注释掉 [factory.py](../../backend/packages/harness/deerflow/models/factory.py) 末尾的 `if loop_guard_cfg ...` 整段
3. **完全删除**：删除新增的 5 个文件，回滚 3 个修改的文件（app_config.py / factory.py / config.example.yaml）

回退后系统行为完全恢复到二开前状态。

---

## 十、后续可优化方向

1. **检测结果上报到前端**：当前只有日志和 SSE metadata；可以在前端检测 `finish_reason=loop_detected` 显示更友好的提示气泡
2. **按 agent 配置阈值**：不同 agent 对循环容忍度不同（写小说的允许更多重复，QA 类应该更严格），可以扩展 agent 配置文件来覆盖默认阈值
3. **统计上报**：累计循环检测次数 / 触发的模型分布，用于评估哪些模型最容易死循环
4. **Layer C — 困惑度检测**：对于既不是完全重复也不是模板变体的"语义循环"（同一段话用不同句式重复说），可以加一个基于 embedding 相似度的检测层（成本较高，按需启用）
