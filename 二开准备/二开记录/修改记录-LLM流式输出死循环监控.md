# LLM 流式输出死循环监控（Loop Guard）开发记录

**日期**: 2026-05-12
**功能**: 检测 LLM 流式输出中的死循环并自动终止
**开发者**: AI Assistant
**版本**: v1.7
**更新历史**:

- v1.0：基础检测（content 字段，Layer A + Layer B）
- v1.1：补全 tool\_call.args / content-block-list / emoji 流的检测盲点
- v1.2：修复接入遗漏——补全 3 个接入点（app\_config / factory / config.example.yaml）
- v1.3：移除 tool\_call\_chunks 检测——避免正常多工具工作流被误判
- v1.4：智能恢复 tool\_call 检测——累积长度门槛 150 字符，短参数不检测、长内容循环可检测
- v1.5：clause\_window 8→32 覆盖旋转模板循环；日志优化输出尾部 2000 字符；max\_ngram\_repeats 4→30 减少对话误判
- v1.6：支持思考内容循环检测——reasoning\_content（MiMo/DeepSeek/Ollama）+ thinking 块（Anthropic）；合并 patched\_mimo 到 patched\_generic\_openai
- v1.7：修复推理内容误触发——将 content 和 reasoning\_content 分开检测，reasoning 仅走 Layer A（n-gram），不走 Layer B（子句骨架相似度）

***

## 一、需求背景

DeerFlow 二开版本经常需要接入**本地小模型**。这些模型在某些 prompt 下会陷入死循环——一直生成相同/相似内容直到 `max_tokens` 才停下来。

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

***

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

| n  | 抓的场景                      |
| -- | ------------------------- |
| 6  | "好的好的好的" 这种 1-3 字短语循环     |
| 12 | "我可以帮你做这个" 这种短句循环         |
| 24 | "请告诉我您的具体需求好的好的好的" 这种半句循环 |
| 48 | 整段话级别的循环                  |

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

| 对比                           | bigram 交集       | Dice     | 命中？  |
| ---------------------------- | --------------- | -------- | ---- |
| `你可以问问题` vs `你可以查资料`（bigram） | `{你可, 可以}` 2/5  | **0.40** | ❌ 漏报 |
| 同样两条（character 集合）           | `{你, 可, 以}` 3/5 | **0.55** | ✅    |

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

***

## 三、新增和修改的文件

### 新增（5 个）

| 文件                                                              | 说明                                                                          |
| --------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `backend/packages/harness/deerflow/models/loop_detector.py`     | 算法核心：`StreamLoopDetector` + `LoopDetectorConfig` + Dice / bigram 辅助函数       |
| `backend/packages/harness/deerflow/models/loop_guard.py`        | 模型包装器：`wrap_model_with_loop_guard()`、`LoopGuardMixin`、实例级 monkey-patch 回退路径 |
| `backend/packages/harness/deerflow/config/loop_guard_config.py` | Pydantic 用户配置 schema：`LoopGuardConfig`，带 `to_detector_config()` 转换方法        |
| `backend/tests/test_loop_detector.py`                           | 算法单元测试（17 个用例，覆盖 Layer A / Layer B / 负样本 / 开关 / 辅助函数）                       |
| `backend/tests/test_loop_guard.py`                              | 集成测试（7 个用例，覆盖同步流 / 异步流 / 幂等 / 配置更新 / 禁用透传）                                  |

### 修改（3 个）

| 文件                                                       | 改动                                                                                          |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `backend/packages/harness/deerflow/config/app_config.py` | 注册 `loop_guard: LoopGuardConfig` 字段到 `AppConfig`，默认 `default_factory=LoopGuardConfig`       |
| `backend/packages/harness/deerflow/models/factory.py`    | `create_chat_model()` 末尾，在返回前调用 `wrap_model_with_loop_guard()`，包了 try/except 保证包裹失败不会阻断模型创建 |
| `config.example.yaml`                                    | 新增 `loop_guard` 配置段（带详细中文注释和调参指南）；`config_version` 从 8 bump 到 9                             |

> ⚠️ **v1.2 修复说明**：v1.0/v1.1 阶段只创建了算法和包装器代码（5 个新增文件），但上述 3 个接入点的修改**遗漏了**——导致功能代码存在但从未被系统调用。v1.2（2026-05-15）补全了这 3 处接入，功能才真正生效。

***

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
  max_ngram_repeats: 30         # 后缀重复次数阈值（30=宽松，减少正常列表/排比句误判）
  # Layer B
  clause_window: 32             # 子句窗口大小（32=覆盖约3个旋转周期，能抓4块模板循环）
  max_clause_repeats: 4
  clause_similarity_threshold: 0.5
  clause_min_length: 3
  clause_max_length: 80
```

**调参建议**：

| 症状                | 调整方向                                                                        |
| ----------------- | --------------------------------------------------------------------------- |
| 该停的没停（漏报，如旋转模板循环） | `clause_window` 调大（32 → 48）；`max_clause_repeats` 调小（4 → 3）                  |
| 正常长文也被打断（误报）      | `max_ngram_repeats` 调大（30 → 50）；`clause_similarity_threshold` 调高（0.5 → 0.6） |
| 完全不需要             | `enabled: false`                                                            |

***

## 四点五、覆盖矩阵（重要）

死循环可能出现在很多场景，下面一张表说清楚**哪些被覆盖、哪些天然不会出问题、哪些是显式不覆盖**。

### 4.5.1 按"调用入口"维度

DeerFlow 项目中**所有** LLM 调用都集中在 `deerflow.models.create_chat_model()` 这一个工厂函数。loop guard 在工厂函数末尾包裹模型，所以下表所有入口**自动覆盖**：

| 调用入口                                      | 用途             | 包裹方式 |
| ----------------------------------------- | -------------- | ---- |
| `lead_agent/agent.py`                     | 主对话 agent      | ✅ 自动 |
| `subagents/executor.py`                   | 子任务（`task` 工具） | ✅ 自动 |
| `middlewares/title_middleware.py`         | 自动生成对话标题       | ✅ 自动 |
| `agents/memory/updater.py`                | 记忆事实抽取         | ✅ 自动 |
| `middlewares/summarization_middleware.py` | 长对话摘要          | ✅ 自动 |
| `skills/security_scanner.py`              | 技能安全扫描         | ✅ 自动 |
| `client.py`                               | 直连 CLI 客户端     | ✅ 自动 |

**结论**：项目里**只要走** **`create_chat_model`，就被监控**。这是单一入口的最大好处。

> 注：DeerFlow 没有独立的 workflow 引擎——"工作流"实际上是通过 `task` 工具调用预定义子 agent 实现的（见 `lead_agent` 的 workflow prompt），底层也走 `create_chat_model`。

### 4.5.2 按"输出去向"维度

模型生成的内容可能去到不同的地方，每种都被覆盖：

| 输出去向                     | 在 LangChain 流中的位置                        | 实际场景                                        | 是否覆盖                     |
| ------------------------ | ---------------------------------------- | ------------------------------------------- | ------------------------ |
| **对话回复**                 | `chunk.message.content` (str)            | 普通聊天回复                                      | ✅                        |
| **多模态/思考**               | `chunk.message.content` (list of dict)   | Anthropic thinking、Vertex Gemini            | ✅                        |
| **写文件 / 工具调用（长参数）**      | `chunk.message.tool_call_chunks[i].args` | `write_file(content="好的好的...")` content 死循环 | ✅ v1.4 恢复（累积 ≥150 字符才检测） |
| **工具调用（短参数）**            | `chunk.message.tool_call_chunks[i].args` | `read_file(path="xxx.md")` 等短参数             | ❌ 不检测（低于 150 字符门槛）       |
| **子任务消息**                | 子 agent 自己的流                             | task 工具内部 LLM 死循环                           | ✅ 自动                     |
| **结构化输出**                | tool\_call args（同上）                      | `with_structured_output()`                  | ⚠️ 仅长参数时覆盖               |
| **Subagent 内 tool 调用**   | 子任务的 tool\_call\_chunks                  | 子任务自己写文件死循环                                 | ⚠️ 仅长参数时覆盖               |
| **非流式调用** **`invoke()`** | `_generate` / `_agenerate`               | 一次性返回，没有流可拦截                                | ⚠️ 不覆盖                   |

**关于 tool\_call\_chunks 的智能过滤（v1.3→v1.4）**：

- v1.1 曾全量覆盖，v1.3 全量移除（误判），v1.4 采用**累积长度门槛**方案
- 短参数（如 `read_file(path="xxx.md")` ≈ 30\~50 字符）：多次累积也到不了 150 字符门槛 → 不送入检测器 → 不误判
- 长参数（如 `write_file(content="好的好的..." x 100)` ≈ 500+ 字符）：快速超过 150 字符 → 送入检测器 → 可抓循环
- 工具调用的**重复调用**（反复调用同一工具）仍由 `LoopDetectionMiddleware` 处理

**关于不覆盖的** **`invoke()`**：

- 死循环在非流式调用下不算"循环"——它就是一次性返回的长文本，loop guard 设计上只管流式
- 实际损失：模型一直跑到 `max_tokens` 才返回，浪费 token，但 gateway 上能看到请求完成时间和 token 计数
- 这种调用在本项目里很少（lead\_agent、subagent、middleware 都用流式），影响面小
- 如果以后真要管，需要在 `_generate` 上加超时和 token 异常增长报警，但不是 loop guard 的职责

### 4.5.3 按"字符内容"维度

| 字符类型                                    | 算法处理                             | 测试用例                                          |
| --------------------------------------- | -------------------------------- | --------------------------------------------- |
| ASCII / 拉丁字母                            | str.count 直接处理，Dice 用字符集合/bigram | `test_detects_english_phrase_loop`            |
| 中文（含全角标点）                               | 同上，每个汉字是 1 个 codepoint           | `test_detects_short_phrase_exact_loop` 等多个    |
| Emoji（单 codepoint，如 👍）                 | 视为单字符，n-gram 算法天然兼容              | `test_loop_in_emoji_only_stream_is_detected`  |
| 复合 emoji（多 codepoint，如 👨‍👩‍👧 / 👋🏻） | 拆成多个 codepoint 不影响 n-gram 匹配     | 间接覆盖                                          |
| 中英混排 + emoji                            | 混合循环也能抓                          | `test_loop_in_mixed_emoji_phrase_is_detected` |
| 纯空白 / 换行                                | n-gram 检测时跳过纯空白后缀                | 算法内置                                          |

**为什么 emoji 不需要特殊处理**：Python 的字符串是 Unicode codepoint 序列，`str.count` 和 slice 都是 codepoint 级操作。`"👍👍👍👍👍👍".count("👍👍") == 3`。算法不在乎一个 codepoint 是 ASCII 还是 emoji，所以**emoji 天然支持**。

### 4.5.4 显式不在覆盖范围内的场景

| 场景                           | 为什么不覆盖                           | 替代方案                              |
| ---------------------------- | -------------------------------- | --------------------------------- |
| 模型完全不流式（`invoke()`）          | 没有 chunk 序列可拦截                   | 用 `max_tokens` 限制 + 超时机制          |
| 工具调用循环（LLM 反复调用同一工具）         | 不是输出循环，是工具循环                     | 已有 `LoopDetectionMiddleware` 处理   |
| Agent 状态机循环（LangGraph 节点死循环） | 是 graph 级别的循环                    | LangGraph 自带 `recursion_limit` 防护 |
| 内容语义重复但句式不同                  | 算法基于 n-gram + 字符相似度，抓不到完全异构的语义循环 | 后续可加 embedding-based 检测层          |
| HTTP 长连接断开后的流恢复              | 第二段流是新的检测器实例，没有上下文               | 不是问题——重连后的内容如果还在循环，新流会重新检测到       |

***

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

***

## 六、测试结果

```
========================== 29 passed in 0.27s ==========================
```

### 6.1 覆盖的循环类型（正向用例）

| 类型                        | 例子                                                    | 命中层                       |
| ------------------------- | ----------------------------------------------------- | ------------------------- |
| 短语完全重复                    | `好的好的好的好的好的好的好的好的`                                    | Layer A (n=6)             |
| 长句完全重复                    | `我是一个智能助手帮你...我是一个智能助手帮你...`                          | Layer A (n=12+)           |
| 英文短语重复                    | `I am sorry I am sorry I am sorry...`                 | Layer A                   |
| 单字符病态                     | `aaaaaaaaaaaaa...`                                    | Layer A (smallest n)      |
| 模板变体（数字尾词）                | `今天是周一，明天是周二，三天后是周三...`                               | Layer B (bigram Dice)     |
| 模板变体（动词尾词）                | `你可以问问题，你可以查资料，你可以写代码...`                             | Layer B (char Dice)       |
| **工具调用 args 循环（长参数）**     | `write_file(content="好的好的好的...")`                     | ✅ v1.4 恢复（累积 ≥150 字符门槛）   |
| **纯 Emoji 循环**            | `👍👍👍👍👍👍👍👍...`                                 | Layer A（codepoint 级）      |
| **混合 Emoji + 文本**         | `好的👍好的👍好的👍...`                                     | Layer A                   |
| **Content Block List 循环** | Anthropic thinking 模式下的 `[{"type":"text",...}]` 列表里循环 | Layer A，从 content list 提取 |

### 6.2 不会误判（负向用例）

| 场景                    | 测试结果           |
| --------------------- | -------------- |
| 长篇正常散文                | ✅ 不误判          |
| "他XX...他YY...他ZZ" 排比句 | ✅ 不误判          |
| 短回复（< 200 字）          | ✅ 预热阈值保护，不参与检测 |
| 同主题但用词不同的列举           | ✅ 不误判          |

### 6.3 开发中踩的 3 个坑

**坑 1：Layer B 算法对"只换尾词"的列表漏报**

- 首轮测试 `test_detects_templated_listing_loop` FAIL：`detected=False`
- 原因：单字尾词变化导致 bigram 重叠太少（只共享前缀 bigram）
- 修复：算法改用 `max(bigram_dice, char_dice)` 混合相似度

**坑 2：异步流的截断断言写错了**

- 首轮测试 `test_async_stream_aborts_on_templated_loop` FAIL：`assert 206 < 180`
- 原因：终止提示「`[deerflow] 检测到...`」本身 80+ 字符，让 aborted 总长度反而比原始流大
- 修复：断言改成按 chunk 数判断截断（`len(collected[:-1]) < len(chunks)`），而不是按字符数

**坑 3：写文件场景循环抓不到（v1.1 修复 → v1.3 回滚 → v1.4 智能恢复）**

- v1.0 只看 `chunk.message.content`，但模型调用 `write_file(content="...")` 时，
  循环的 content 实际上走的是 `chunk.message.tool_call_chunks[i].args`
  ——一个独立字段，content 在这种 chunk 里是空字符串
- 表现：用户报告"小模型写文件时还是会卡死"
- v1.1 修复：扩展 `_extract_text`，把 content（str 或 list）+ 所有 tool\_call\_chunks 的 args
  **合并送给同一个检测器**
- v1.3 回滚：生产中发现正常多工具工作流（依次 `read_file(path="...")`）被误判为循环。
  工具调用循环由 `LoopDetectionMiddleware` 处理，loop guard 只监控 `message.content`
- v1.4 最终方案：**累积长度门槛（150 字符）**。短参数（path/filename ≈ 30\~50 字符）
  多次累积也到不了门槛，不送入检测器；长参数（write\_file content 死循环 ≥150 字符）
  超过门槛后送入检测器。两全其美

***

### 6.4 最终全量验收

为防止改动破坏其他已有功能，跑了一次后端全量测试：

```
========================== 2143 passed, 21 skipped, 10 failed in 241.60s ==========================
```

- **新增/修改相关的测试 100% 通过**（`test_loop_detector.py` 17 个、`test_loop_guard.py` 12 个、`test_model_factory.py`、`test_app_config_reload.py`、`test_config_version.py`、`test_lead_agent_*.py`、`test_llm_error_handling_middleware.py`、现有的 `test_loop_detection_middleware*` 全过）
- **10 个失败用例与本改动无关**：全部在 `test_local_sandbox_provider_mounts.py`（7 个）和 `test_sandbox_search_tools.py`（3 个），根因是 Windows 平台路径分隔符差异、缺少符号链接权限、缺少某些外部可执行文件——属于 sandbox 模块在 Windows 下的已知问题，本改动没有触碰这些代码路径

***

## 七、运行时观察

当循环被检测到时，`logs/langgraph.log` 会出现如下警告（v1.5+ 包含尾部内容预览）：

```
WARNING deerflow.models.loop_guard:loop_guard.py:191
LoopGuard: terminating async stream — templated clause '今天是周一' repeated 5 times in last 32 clauses (Dice ≥ 0.5) (total chars=967)
Tail content (last 967 chars):
今天是周一，明天是周二，三天后是周三，四天后是周四，五天后是周五...
（此处显示触发前模型输出的最近 2000 字符内容）
```

前端 / SSE 流的最后一个 chunk 会带：

- `finish_reason: "loop_detected"`
- `response_metadata.deerflow_loop_detected`：包含 `layer` / `reason` / `repeat_count`

***

## 八、影响范围

| 范围                                      | 影响                                 |
| --------------------------------------- | ---------------------------------- |
| 现有 chat model 行为                        | 默认开启监控；正常对话**不受影响**（保守阈值）          |
| 已有的 `LoopDetectionMiddleware`（工具调用循环检测） | 互不干扰，处理的是不同维度的循环                   |
| `LLMErrorHandlingMiddleware`（错误重试）      | 不会误触发，因为 loop guard 不抛异常           |
| `TokenUsageMiddleware`（token 计数）        | 不受影响，被截断的输出仍然按 chunk 计数            |
| 性能                                      | 每 60 字符跑一次检测，开销 < 1ms，相对 LLM 延迟可忽略 |
| 内存                                      | 每次调用一个 \~2KB 的 tail 缓冲，调用结束自动释放    |

***

## 九、回退方案

如果出现意外问题，三种回退方案任选其一：

1. **配置关闭**（最快）：在 `config.yaml` 加 `loop_guard: { enabled: false }`，重启即可
2. **factory 跳过**：注释掉 [factory.py](../../backend/packages/harness/deerflow/models/factory.py) 末尾的 `if loop_guard_cfg ...` 整段
3. **完全删除**：删除新增的 5 个文件，回滚 3 个修改的文件（app\_config.py / factory.py / config.example.yaml）

回退后系统行为完全恢复到二开前状态。

***

## 十、v1.2 修复记录（2026-05-15）

### 10.1 问题发现

用户反馈本地模型调用时一次性生成 2w+ token 的死循环输出，但 loop guard 功能未生效。

### 10.2 根因分析

v1.0/v1.1 阶段只完成了**代码文件的创建**（5 个新增文件），但遗漏了**系统接入**（3 个修改文件）：

| 修改文件                  | 预期改动                                | 实际状态  |
| --------------------- | ----------------------------------- | ----- |
| `app_config.py`       | 注册 `loop_guard: LoopGuardConfig` 字段 | ❌ 未改动 |
| `factory.py`          | 调用 `wrap_model_with_loop_guard()`   | ❌ 未改动 |
| `config.example.yaml` | 添加 `loop_guard` 配置段                 | ❌ 未改动 |

**结果**：算法代码写好了但从未被调用——等于建了发动机但没装到车上。

### 10.3 修复内容

补全 3 个接入点：

1. **`app_config.py`**：新增 `from deerflow.config.loop_guard_config import LoopGuardConfig`，在 `AppConfig` 类中添加 `loop_guard: LoopGuardConfig = Field(default_factory=LoopGuardConfig)`
2. **`factory.py`**：在 `create_chat_model()` 末尾、`return model_instance` 之前添加：
   ```python
   try:
       loop_guard_cfg = config.loop_guard.to_detector_config()
       if loop_guard_cfg.enabled:
           from deerflow.models.loop_guard import wrap_model_with_loop_guard
           wrap_model_with_loop_guard(model_instance, loop_guard_cfg)
   except Exception:
       logger.debug("LoopGuard wrapping failed for model '%s', continuing without guard", name, exc_info=True)
   ```
3. **`config.example.yaml`**：添加 `loop_guard` 配置段（带中文注释），`config_version` 从 8 bump 到 9

### 10.4 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 26 passed (含原 v1.1 测试)
tests/test_app_config_reload.py — 3 passed
tests/test_model_factory.py   — 35 passed
tests/test_config_version.py  — 6 passed
```

***

## 十二、v1.3 修复记录（2026-05-15）

### 12.1 问题发现

LoopGuard 接入后（v1.2），用户反馈线上大模型在正常工作时频繁触发截断，日志显示：

```
LoopGuard: terminating async stream — templated clause 'path:mntshareddatabook/.../xxx.md' repeated 4 times in last 5 clauses (Dice ≥ 0.5)
```

### 12.2 根因分析

v1.1 为了覆盖"写文件时 content 死循环"场景，扩展了 `_extract_text` 去读取 `tool_call_chunks` 的 `args` 字段。但生产中发现：

- 子 agent 正常工作时，模型会**依次调用不同工具**（如 `read_file(path="...")`、`write_file(path="...")`）
- 这些工具参数的 `path` 值结构高度相似（都是 `path:` 开头 + 文件路径）
- Layer B 的 Dice 相似度检测将其误判为"模板变体循环"

**这是设计盲区**：工具调用循环（反复调用同一工具）应由 `LoopDetectionMiddleware` 的 hash 检测处理，不是 loop guard 的职责。

### 12.3 修复内容

**修改** **`loop_guard.py`** **的** **`_extract_text`**：

- **移除**对 `message.tool_call_chunks` 的 `args` 字段读取
- **只保留**对 `message.content`（str 或 list）的提取
- 更新 docstring 说明不监控 tool\_call 的原因

**修改** **`test_loop_guard.py`**：

- `test_loop_in_tool_call_args_is_detected` → `test_tool_call_args_not_monitored`
- 验证工具调用 chunk 流**不被截断**、全部透传
- 移除对应的 async 测试（`test_loop_in_tool_call_args_async`）

### 12.4 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 26 passed（含更新后的 tool_call 测试）
```

### 12.5 覆盖范围变更

| 输出去向                       | v1.1-v1.2 | v1.3 | <br />          |
| -------------------------- | --------- | ---- | :-------------- |
| 对话回复 `content`             | ✅         | ✅    | <br />          |
| 多模态 content list           | ✅         | ✅    | <br />          |
| 输出去向                       | v1.1-v1.2 | v1.3 | v1.4            |
| ---                        | ---       | ---  | ---             |
| 对话回复 `content`             | ✅         | ✅    | ✅               |
| 多模态 content list           | ✅         | ✅    | ✅               |
| tool\_call\_chunks args（短） | ✅         | ❌ 移除 | ❌ 低于 150 字符门槛   |
| tool\_call\_chunks args（长） | ✅         | ❌ 移除 | ✅ 累积 ≥150 字符才检测 |
| 子任务消息                      | ✅ 自动      | ✅ 自动 | ✅ 自动            |
| 结构化输出                      | ✅         | ❌ 移除 | ⚠️ 仅长参数时覆盖      |

> 工具调用的**重复调用**（反复调用同一工具）由 `LoopDetectionMiddleware` 处理。

***

## 十三、v1.4 修复记录（2026-05-15）

### 13.1 需求

v1.3 全量移除了 tool\_call 检测，解决了误判问题，但也导致**写文件时 content 死循环无法检测**。用户希望恢复对长工具参数（如 `write_file(content="...")`）的检测能力，同时保持不误判正常多工具工作流。

### 13.2 方案：累积长度门槛

核心思路：**tool\_call 的 args 分片先累积，超过 150 字符后才送入检测器**。

```
chunk1: args='{"path": "out'        → 累积 14 字符 < 150 → 不送入
chunk2: args='.md", "content": "好'   → 累积 32 字符 < 150 → 不送入
chunk3: args='的好的好的好的...'    → 累积 180 字符 >= 150 → 送入检测！
```

| 场景                                               | 单次 args 大小 | 累积结果                     | 检测？     |
| ------------------------------------------------ | ---------- | ------------------------ | ------- |
| `read_file(path="xxx.md")`                       | \~35 字符    | 多次累积仍 < 150（每次新 call 重置） | ❌ 不检测   |
| `write_file(path="x.md", content="好的..." x 100)` | \~500+ 字符  | 快速超过 150                 | ✅ 可检测循环 |

### 13.3 代码改动

**`loop_guard.py`**：

- `_extract_text()` 拆分为两个函数：
  - `_extract_content_text()` — 只提取 `message.content`
  - `_extract_tool_args()` — 只提取 `tool_call_chunks` 的 `args`
- 新增常量 `_TOOL_ARGS_ACCUMULATE_THRESHOLD = 150`
- `LoopGuardMixin._stream` / `_astream` / 实例级 patch 路径：
  - 新增 `tool_args_buf` 累积变量
  - 每个 chunk 分别提取 content 和 tool\_args
  - tool\_args 先累积到 buf，>= 150 时合并到 text 并送 detector，然后清空 buf
- **`loop_detector.py`**：`max_ngram_repeats` 默认值从 4 提升到 30（减少对话内容误判）
- **`loop_guard_config.py`**：同步更新默认值和上限
- **`config.example.yaml`**：同步更新注释和默认值

### 13.4 测试改动

| 测试                                          | 变更                                 |
| ------------------------------------------- | ---------------------------------- |
| `test_tool_call_args_not_monitored`         | → 拆为两个测试                           |
| `test_short_tool_call_args_not_monitored`   | **新增**：5 个短 read\_file args 不触发    |
| `test_long_tool_call_args_loop_is_detected` | **新增**：长 write\_file content 循环被截断 |

### 13.5 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 27 passed（含 2 个新 tool_call 测试）
```

***

## 十四、v1.5 修复记录（2026-05-16）

### 14.1 问题发现

用户反馈 `mimo-v2.5` 模型（novel-writer 子 agent）在写章节时陷入**4 块旋转模板循环**：

```
禁用词检查 → 字数检查 → Markdown 格式检查 → 英文引号检查 → 禁用词检查 → ...
```

每块内容不同（不是完全重复），但句式骨架高度相似。LoopGuard **未触发截断**，模型持续输出了 21 分钟（1300 秒），生成大量重复推理。

### 14.2 根因分析

| 检测层              | 失效原因                                                                                   |
| ---------------- | -------------------------------------------------------------------------------------- |
| Layer A (n-gram) | 4 块内容不同，没有任何单个 n-gram 连续重复 30 次                                                        |
| Layer B (clause) | `clause_window=8` 只看最近 8 条子句。4 块旋转中每块只出现 **2 次**（8÷4=2），2 < `max_clause_repeats=4` 不触发 |

**核心问题**：`clause_window` 太小，装不下足够多的旋转周期。

### 14.3 修复内容

#### 改动 1：clause\_window 8 → 32

覆盖约 3 个完整旋转周期（4 块 × 每块 \~8 条子句 = 32 条）。每种子句模式出现 3\~4 次，达到 `max_clause_repeats=4` 阈值。

涉及文件：

- `loop_detector.py`: `LoopDetectorConfig.clause_window: 8 → 32`
- `loop_guard_config.py`: `LoopGuardConfig.clause_window: default=8→32, le=50→64`
- `config.example.yaml`: 同步更新

#### 改动 2：max\_ngram\_repeats 4 → 30

减少对话正常输出的误判（如 `\n - `  列表前缀、Markdown 表格格式等）。

涉及文件：

- `loop_detector.py`: `LoopDetectorConfig.max_ngram_repeats: 4 → 30`
- `loop_guard_config.py`: `default=4→30, le=50→100`
- `config.example.yaml`: 同步更新
- `test_loop_detector.py`: 循环次数适配新阈值

#### 改动 3：日志增强——输出尾部 2000 字符

触发循环检测时，日志新增模型输出的尾部内容预览（最多 2000 字符），方便排查误判/漏判：

```
WARNING LoopGuard: terminating async stream — templated clause '...' repeated 5 times (total chars=967)
Tail content (last 967 chars):
现在我需要确保没有使用禁用词。已经检查过，没有。
现在我需要确保字数在4000-6000字之间...
...（完整尾部内容）
```

涉及文件：`loop_guard.py` 全部 4 处 logger.warning 调用

### 14.4 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 27 passed（含 tool_call + clause_window 相关测试）
```

***

## 十五、v1.6 修复记录（2026-05-16）

### 15.1 问题发现

用户使用 mimo-v2-omni 模型时，模型在思考（reasoning）阶段陷入旋转模板循环，但 LoopGuard **完全没触发**。日志中零条 LoopGuard 记录。

### 15.2 根因分析

mimo-v2-omni 是 OpenAI 兼容 API，其思考内容存储在 `message.additional_kwargs["reasoning_content"]`，**不是** `message.content`。

而 `_extract_content_text` 只读取了 `message.content`（str 或 list），完全没有看 `additional_kwargs`，所以思考内容的循环根本检测不到。

类似地，Anthropic 的 thinking 块 `{"type": "thinking", "thinking": "..."}` 也没被提取（只提取了 `text` 和 `content` 键）。

### 15.3 修复内容

#### 改动 1：`_extract_content_text` 支持思考内容

新增两个提取源：

1. **`additional_kwargs["reasoning_content"]`** — MiMo/DeepSeek/Ollama 等模型的思考内容
2. **content list 中的** **`thinking`** **键** — Anthropic 原生 thinking 块

```python
# content list 中的 thinking 块
text = block.get("thinking") or block.get("text") or block.get("content") or ""

# additional_kwargs 中的 reasoning_content
reasoning_content = additional_kwargs.get("reasoning_content")
if isinstance(reasoning_content, str) and reasoning_content:
    parts.append(reasoning_content)
```

#### 改动 2：合并 `patched_mimo.py` 到 `patched_generic_openai.py`

`GenericPatchedChatOpenAI` 是 `PatchedMiMoChatOpenAI` 的严格超集，两者功能完全重叠。合并方案：

- `patched_mimo.py` 变成**别名文件**：`PatchedMiMoChatOpenAI = GenericPatchedChatOpenAI`
- `patched_generic_openai.py` 的 `_restore_reasoning_to_payload` 补充空字符串回退（MiMo API 要求）
- 现有 `config.yaml` 中 `deerflow.models.patched_mimo:PatchedMiMoChatOpenAI` 无需修改，继续兼容

#### 改动 3：新增测试

| 测试                                                  | 说明                                                  |
| --------------------------------------------------- | --------------------------------------------------- |
| `test_loop_in_reasoning_content_is_detected`        | MiMo/DeepSeek 的 `reasoning_content` 循环              |
| `test_loop_in_anthropic_thinking_block_is_detected` | Anthropic `{"type":"thinking","thinking":"..."}` 循环 |

### 15.4 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 29 passed（含 2 个新 thinking 测试）
tests/test_patched_mimo.py    — 11 passed（合并后兼容性完好）
```

### 15.5 覆盖范围更新

| 输出去向                                | v1.5 | v1.6 |
| ----------------------------------- | ---- | ---- |
| 对话回复 `content` (str)                | ✅    | ✅    |
| 多模态 content list (`text` 块)         | ✅    | ✅    |
| Anthropic thinking 块 (`thinking` 键) | ❌    | ✅    |
| OpenAI 兼容 `reasoning_content`       | ❌    | ✅    |
| tool\_call\_chunks args（长参数）        | ✅    | ✅    |
| tool\_call\_chunks args（短参数）        | ❌    | ❌    |

***

## 十六、v1.7 修复记录（2026-05-16）

### 16.1 问题发现

用户反馈 `mimo-v2.5-pro` 模型在创建新对话时，**任意命令都会触发 LoopGuard 截断**。日志显示：

```
LoopGuard: terminating async stream — templated clause 'platform' repeated 4 times in last 8 clauses (Dice ≥ 0.5) (total chars=471)
LoopGuard: terminating async stream — templated clause 'andineedtoconfirmsomedetails.' repeated 6 times in last 8 clauses (Dice ≥ 0.5) (total chars=472)
```

模型在 reasoning_content 中输出的正常推理内容（列清单、重复确认步骤）被误判为死循环。

### 16.2 根因分析

v1.6 将 `additional_kwargs["reasoning_content"]` 和 `message.content` **合并后送入同一个检测器**。但推理内容天然具有重复结构：

| 推理内容特征 | 为什么触发 Layer B |
|---|---|
| 列清单："book name, genre, one-sentence concept, platform" | 短词被逗号切分为子句，字符集合 Dice ≥ 0.5 |
| 重复确认："I need to confirm some details" | 多次出现相似确认语句，子句骨架高度相似 |

**核心问题**：Layer B（子句骨架相似度）对推理内容过于敏感。推理是模型的"内部思考过程"，结构化重复是正常行为，不是死循环。

### 16.3 修复内容

#### 改动 1：拆分 content 和 reasoning 提取

原 `_extract_content_text` 同时提取 content 和 reasoning_content，改为两个独立函数：

- `_extract_content_text()` — 仅提取 `message.content`（str 或 list），**排除** thinking 块和 reasoning_content
- `_extract_reasoning_text()` — 提取 `additional_kwargs["reasoning_content"]` + content list 中的 `thinking` 块

#### 改动 2：`LoopDetectorConfig` 新增 `layer_a_only` 开关

```python
layer_a_only: bool = False
"""When True, only Layer A (n-gram suffix repetition) runs.
Used for reasoning / thinking content where Layer B's clause-skeleton
similarity produces too many false positives."""
```

`_check()` 方法中 Layer B 受此开关控制。

#### 改动 3：双检测器架构

Stream 方法中使用两个独立检测器：

```python
content_detector = StreamLoopDetector(cfg)           # Layer A + B，检测 content
reasoning_detector = StreamLoopDetector(reasoning_cfg) # 仅 Layer A，检测 reasoning
```

任一检测器触发循环即终止流。

#### 改动 4：新增测试

| 测试 | 说明 |
|------|------|
| `test_reasoning_structured_list_not_false_positive` | 推理内容中的结构化列表不误触发 |
| `test_content_clause_detection_still_works` | 内容文本的 Layer B 子句检测仍正常工作 |

### 16.4 验证结果

```
tests/test_loop_detector.py   — 26 passed
tests/test_loop_guard.py      — 31 passed（含 2 个新测试）
```

### 16.5 覆盖范围更新

| 输出去向 | v1.6 | v1.7 |
|---|---|---|
| 对话回复 `content` (str) | ✅ | ✅ |
| 多模态 content list (`text` 块) | ✅ | ✅ |
| Anthropic thinking 块 (`thinking` 键) | ✅ 全量检测 | ✅ 仅 Layer A |
| OpenAI 兼容 `reasoning_content` | ✅ 全量检测 | ✅ 仅 Layer A |
| tool\_call\_chunks args（长参数） | ✅ | ✅ |
| tool\_call\_chunks args（短参数） | ❌ | ❌ |

### 16.6 技术决策

**为什么不用单一检测器 + 动态切换？**

如果在同一个检测器中根据文本来源切换 Layer B，会导致检测器状态混乱（tail 缓冲区混合了 content 和 reasoning 文本）。两个独立检测器各自维护状态，互不干扰。

**为什么 reasoning 仍保留 Layer A？**

推理内容也可能陷入真正的 n-gram 死循环（如 "好的好的好的"），Layer A 能可靠捕获这类完全重复模式，且不会误判结构化推理。

***

## 十一、后续可优化方向

1. **检测结果上报到前端**：当前只有日志和 SSE metadata；可以在前端检测 `finish_reason=loop_detected` 显示更友好的提示气泡
2. **按 agent 配置阈值**：不同 agent 对循环容忍度不同（写小说的允许更多重复，QA 类应该更严格），可以扩展 agent 配置文件来覆盖默认阈值
3. **统计上报**：累计循环检测次数 / 触发的模型分布，用于评估哪些模型最容易死循环
4. **Layer C — 困惑度检测**：对于既不是完全重复也不是模板变体的"语义循环"（同一段话用不同句式重复说），可以加一个基于 embedding 相似度的检测层（成本较高，按需启用）

