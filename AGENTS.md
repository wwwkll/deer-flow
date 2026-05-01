本项目是deerflow项目的二开。文档在二开准备，每次更新代码后需要更新文档，当然更新文档之前要跟用户确认，项目都有效跑通之后才更新。

每次做完新功能的研发工作，需要自行测试，确保功能正常。你可以使用浏览器插件进行功能测试，也可以使用命令行工具进行功能测试，可以写自动化脚本对后端接口进行测试。

所有的临时文件放在temp文件夹下。

若开发新的或修改agents/skill/tools，需要在config.example.yaml以及readme.md中添加对应的配置说明，明确这些是必须项。


写入数据必须遵循以下规则：

1. **禁止使用 REPLACE INTO**：该语句会完全替换整行记录，导致未指定字段被设置为 NULL 或默认值
2. **推荐使用 ON DUPLICATE KEY UPDATE**（MySQL 专属语法）：
   - 一条 SQL 同时处理 INSERT 和 UPDATE
   - 只更新指定字段，符合字段隔离原则
   - 性能最优，代码最简洁
   **SQLite 没有** **`ON DUPLICATE KEY UPDATE`**，但它有**功能完全等价、语法几乎一样**的专属语法：

   &#x20;

   最佳替代方案：`INSERT OR REPLACE` / `INSERT ... ON CONFLICT ... DO UPDATE`
3. **字段隔离原则**：每个功能模块只负责写入自己对应的字段列，不得覆盖其他模块的数据
4. **WHERE 条件明确**：UPDATE 语句的 WHERE 条件必须精确匹配目标记录（如主键或唯一键组合），避免误更新
5. **未经允许，不可新建新的数据库表、数据库字段或索引**
6. 在用户允许的情况下，可以使用特殊的sql语句，这种场景下需要备注说明用户以允许，防止后续其他agent看到后根据本文档修改代码。



改BUG要遵循：1 确认bug是否存在，2 确认bug的描述，3 确认bug的修复方法，编排修复计划，4 确认bug的修复结果。

每次更新agents、工作流等需要再config中注册的内容，需要更新config.example.yaml以及readme.md。


# DeerFlow 后端日志指南

## 日志文件位置

所有日志文件位于项目根目录的 `logs/` 文件夹下：

```
c:\xiangmu\deer-flow\logs\
```

## 日志文件说明

| 文件 | 说明 | 重要程度 |
|------|------|----------|
| `gateway.log` | Gateway API 后端日志（FastAPI） | ⭐⭐⭐ 最常用 |
| `langgraph.log` | LangGraph Agent 运行时日志 | ⭐⭐⭐ Agent 问题必看 |
| `frontend.log` | 前端 Next.js 日志 | ⭐⭐ 前端问题查看 |
| `nginx.log` | Nginx 反向代理主日志 | ⭐ 代理问题查看 |
| `nginx-access.log` | Nginx 访问日志 | ⭐ 查看请求记录 |
| `nginx-error.log` | Nginx 错误日志 | ⭐ 代理错误查看 |
| `error.log` | 通用错误日志 | ⭐ 全局错误 |

## 查看日志方法

### PowerShell 命令

```powershell
# 实时查看 Gateway 日志（推荐）
Get-Content c:\xiangmu\deer-flow\logs\gateway.log -Tail 50 -Wait

# 实时查看 LangGraph 日志
Get-Content c:\xiangmu\deer-flow\logs\langgraph.log -Tail 50 -Wait

# 查看全部日志
Get-Content c:\xiangmu\deer-flow\logs\gateway.log

# 搜索错误关键词
Select-String -Path c:\xiangmu\deer-flow\logs\gateway.log -Pattern "ERROR|Exception"
```

### 直接打开文件

用任意文本编辑器（VS Code、Notepad++ 等）直接打开对应的日志文件。

## 日志格式

```
2025-04-29 10:30:15 - app.gateway.app - INFO - Configuration loaded successfully
```

格式说明：`时间 - 模块名 - 日志级别 - 日志内容`

## 日志级别

日志级别通过 `config.yaml` 中的 `log_level` 字段配置，可选值：

- `debug` - 调试信息（最详细）
- `info` - 普通信息（默认）
- `warning` - 警告信息
- `error` - 错误信息

## 调试模式日志

如果使用 `debug.py` 进行调试，日志会输出到：

```
backend/debug.log
```

## 排查问题建议

1. **API 接口报错** → 先查看 `gateway.log`
2. **Agent 执行异常** → 查看 `langgraph.log`
3. **页面显示异常** → 查看 `frontend.log`
4. **请求无法到达后端** → 查看 `nginx-error.log`
