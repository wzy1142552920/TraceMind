# T4 — Tool 层 Spec

- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T1、T2、T3
- **下游**：T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

Agent 不能直接读文件或执行任意命令。它只能通过注册过的只读工具获取证据。T4 建立统一的 ToolSpec、参数校验、路径安全、输出限制、去重和审计，使 T6 的运行时只能走受控执行链。

**用户故事**：作为运行时，我可以把 LLM 返回的 tool call 交给 ToolExecutor；它要么返回结构化结果，要么返回明确错误码，并且每次调用都有审计记录。

## 2. In scope

- `ToolSpec`/`ToolRequest`/`ToolResult` 契约和错误码。
- Tool Registry：注册、查找、列出工具。
- ToolExecutor：Pydantic 参数校验、路径/目标校验、去重、输出截断、审计事件。
- 四个本地只读工具：`logs.search`、`logs.get_event_context`、`code.find_symbol`、`code.get_source_range`。
- 路径根：repo root、log root；拒绝越界/符号链接逃逸。
- 结果中的 `source_ref`（`repo://`/`log://`）。
- 运行内去重：同一工具 + 相同 canonical 参数最多执行 1 次；第二次返回 `DUPLICATE_CALL`，不执行。

## 3. Out of scope

- 远程 MCP/SSH/DB/Redis。
- 审批/Policy Engine（v0.1 只做路径安全和只读）。
- 并发执行、超时取消的线程级实现（保留字段，同步执行）。
- 日志/源码脱敏（v0.1 本地 fixture；后续 T7 报告限制）。
- `EXPLAIN`、SQL、Redis 命令。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T4-01 | Registry 支持注册/查找/列出工具；工具名唯一 | must |
| FR-T4-02 | 每次调用按 ToolSpec 的 Pydantic 模型校验参数 | must |
| FR-T4-03 | 路径参数规范化/解析真实路径，拒绝越界和符号链接逃逸 | must |
| FR-T4-04 | 结果经过输出上限裁剪，设置 `truncated=True` | must |
| FR-T4-05 | 同一工具+相同参数第二次调用返回 `DUPLICATE_CALL`，不执行 | must |
| FR-T4-06 | 每次调用写一条审计事件（允许/拒绝/错误/耗时） | must |
| FR-T4-07 | 未知工具/非法参数/目标拒绝使用稳定错误码 | must |
| FR-T4-08 | 所有工具 `read_only=True`，不写文件、不执行命令 | must |
| FR-T4-09 | 结果带 `source_ref`，可被 T7 引用校验 | must |
| FR-T4-10 | 工具执行不依赖 LLM/网络 | must |

## 5. 接口/数据契约

### `ToolSpec`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | 工具名 |
| `description` | `str` | 静态描述（不含用户数据） |
| `input_model` | `type[BaseModel]` | Pydantic 参数模型 |
| `read_only` | `bool` | v0.1 恒为 True |
| `max_output_bytes` | `int` | 默认 32768 |
| `requires_approval` | `bool` | v0.1 恒为 False |

### `ToolRequest`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_call_id` | `str` | LLM/运行时提供 |
| `tool_name` | `str` | 注册名 |
| `arguments` | `dict` | 原始参数 |
| `run_id` | `str` | 运行 ID |

### `ToolResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 成功/失败 |
| `tool_name` | `str` | 工具名 |
| `data` | `Any` | 已裁剪的结果 |
| `error_code` | `str \| None` | 稳定错误码 |
| `error_message` | `str \| None` | 脱敏错误信息 |
| `source_ref` | `str \| None` | 主要来源 |
| `duration_ms` | `int` | 耗时 |
| `truncated` | `bool` | 是否裁剪 |

### 错误码

`TOOL_NOT_FOUND`、`INVALID_ARGUMENTS`、`TARGET_DENIED`、`OUTPUT_LIMIT`、`DUPLICATE_CALL`、`TOOL_ERROR`。

### 工具定义

#### `logs.search`

```json
{
  "query": "string, required",
  "limit": "integer, 1..50, default 10"
}
```

返回：`{items: [{event_id, timestamp, level, thread, logger, message, line_start, line_end}], total_matched, truncated}`；`source_ref` 为匹配事件所在日志文件。

#### `logs.get_event_context`

```json
{
  "event_id": "string, required",
  "before": "integer, 0..20, default 2",
  "after": "integer, 0..20, default 2"
}
```

返回：`{items: [event summaries], truncated}`；`source_ref` 指向日志行范围。

#### `code.find_symbol`

```json
{
  "query": "string, required",
  "limit": "integer, 1..20, default 10"
}
```

返回：`{items: [SourceMatch-like], truncated}`；`source_ref` 为 `repo://<path>#Lx-Ly`。

#### `code.get_source_range`

```json
{
  "file_path": "string, relative to repo root, required",
  "start_line": "integer >= 1, required",
  "end_line": "integer >= start_line, required",
  "max_lines": "integer, 1..200, default 80"
}
```

返回：`{file_path, start_line, end_line, text, truncated}`；`source_ref` 为 `repo://<path>#Lx-Ly`。

### 路径安全

- repo root / log root 在构造 ToolExecutor 时传入并解析为真实路径。
- 参数只允许相对路径；解析后必须位于对应 root 内。
- 拒绝 `..` 越界、绝对路径、符号链接逃逸。
- `logs.*` 通过 event_id/source label 访问已解析事件，不接受任意日志路径。

### 去重

- canonical JSON（排序 key、去空格）后 hash。
- 同 run 内 `(tool_name, args_hash)` 第二次调用直接返回 `DUPLICATE_CALL`。
- 去重记录写入审计事件。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T4-01 | `logs.search("rows=0")` 命中 T2 fixture 的 WARN 事件 | 单元测试 |
| AC-T4-02 | `logs.get_event_context` 返回目标事件前后各 2 条 | 单元测试 |
| AC-T4-03 | `code.find_symbol("OrderService.updateStatus")` 返回 T3 的源码位置 | 单元测试 |
| AC-T4-04 | `code.get_source_range` 返回包含第 24 行 throw 的片段 | 单元测试 |
| AC-T4-05 | `code.get_source_range("../../etc/passwd", ...)` 返回 `TARGET_DENIED` | 安全测试 |
| AC-T4-06 | 未知工具返回 `TOOL_NOT_FOUND` | 安全测试 |
| AC-T4-07 | 非法参数返回 `INVALID_ARGUMENTS`，不执行工具 | 安全测试 |
| AC-T4-08 | 同一工具+相同参数第二次返回 `DUPLICATE_CALL`，底层不执行 | 单元测试 |
| AC-T4-09 | 超过 `max_output_bytes` 的结果被裁剪，`truncated=True` | 单元测试 |
| AC-T4-10 | 每次调用产生一条审计记录，包含结果/错误码/耗时 | 单元测试 |
| AC-T4-11 | 所有工具不写文件、不执行命令 | 代码审查/测试 |

## 7. 测试计划

### 单元

- `tests/unit/test_tool_executor.py`
  - 正常调用四个工具。
  - 路径穿越、绝对路径、符号链接逃逸。
  - 未知工具/非法参数。
  - 重复调用。
  - 输出裁剪。
  - 审计记录。
- `tests/unit/test_tool_registry.py`
  - 注册/查找/重复注册/列出。

### 集成

- 用 T2 的 `ParsedLog` + T3 的 `JavaIndex` 构造工具上下文，执行四个工具。
- 由 T6 的集成测试覆盖。

### 安全

- `tests/security/test_tool_paths.py`（可并入 unit）：
  - `../`、绝对路径、`~`、符号链接。
  - 参数类型错误、额外字段。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 符号链接逃逸 | `Path.resolve()` 后仍需检查 root | 统一 `is_relative_to(root)`；测试覆盖 |
| 日志事件定位 | event_id 由 T2 生成；工具需要事件索引 | ToolExecutor 接收 `ParsedLog` 上下文 |
| 去重策略 | 过严会阻止合理重试 | v0.1 同参数上限 1；不同参数不受限 |
| 输出裁剪 | 截断 JSON 可能破坏结构 | 裁剪 `text` 字段并标记；不返回半截 JSON |
| 审计写入失败 | 无持久化后端 | v0.1 写入内存/JSONL；失败记录错误，不阻塞只读工具 |
| 脱敏 | 本地 fixture 可能含敏感信息 | v0.1 不做；README 说明 |

**开放问题**

- `logs.search` 是字面量还是正则？v0.1 建议字面量（case-insensitive），正则后续。
- `code.get_source_range` 的 `max_lines` 上限是否放在 ToolSpec 还是参数？v0.1 参数和 ToolSpec 双重限制。
- 审计写入位置：T4 只产生事件对象，T7 负责写入 `audit.jsonl`；T4 测试用内存收集器。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_tool_executor.py tests/unit/test_tool_registry.py -q
```

## 10. 实现验证结果

| 日期 | 命令 | 结果 |
|---|---|---|
| 2026-10-21 | `uv run pytest tests/unit/test_tool_executor.py tests/unit/test_tool_registry.py -q` | 17 passed |
| 2026-10-21 | `uv run pytest -q` | 65 passed |
| 2026-10-21 | `uv run ruff check .` | All checks passed |
| 2026-10-21 | `uv run mypy src` | Success: no issues found in 22 source files |
| 2026-10-21 | 安全用例 | 路径穿越、绝对路径、符号链接逃逸均返回 `TARGET_DENIED` |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T4 spec；定义工具契约、路径安全、去重、审计和验收标准 |
| 2026-10-21 | T4 实现完成；四个本地工具、Registry/Executor、去重/输出限制/审计/路径安全测试通过 |
