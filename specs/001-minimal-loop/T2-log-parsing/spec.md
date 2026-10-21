# T2 — 领域模型与日志解析 Spec

- **任务 ID**：T2
- **状态**：draft
- **依赖**：T1
- **下游**：T3、T4、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

最小循环的第一个事实来源是日志。v0.1 需要把一份常见的 Java 文本日志（Logback/Log4j2 风格）和其中的多行异常堆栈解析成结构化事件，供 T3 定位源码、T4 搜索日志、T6 生成证据。

**用户故事**：作为开发者，我给它一份包含异常堆栈的日志，它能告诉我：哪个事件是主异常、异常类型/消息是什么、堆栈帧有哪些、分别在第几行。

## 2. In scope

- 单个文本日志文件；UTF-8。
- 日志头格式：`YYYY-MM-DD HH:MM:SS.mmm LEVEL [thread] logger - message`。
- 多行异常堆栈合并到同一个 `LogEvent`。
- 解析 `Caused by:`、`Suppressed:`、`... N more`。
- 解析 stack frame：`at com.example.Foo.bar(Foo.java:123)`、`at java.base/...`、`Native Method`、`Unknown Source`。
- 选出 primary event（异常锚点）。
- 对无法解析的行记录 warning，不崩溃。
- 模型可序列化（Pydantic）。

## 3. Out of scope

- JSON/JSONL 日志。
- 多文件/轮转日志、跨文件时间线。
- 复杂时区/夏令时；v0.1 按日志中的本地时间解析。
- 业务 `business_trace_id`/MDC 关联。
- 日志脱敏（v0.1 只读本地 fixture；后续 T4/T7 补）。
- 自定义 log pattern 配置。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T2-01 | 解析日志头的时间、级别、线程、logger、message | must |
| FR-T2-02 | 识别异常行（`Exception`/`Error`/`Throwable` 或 `Caused by:`）并把后续缩进/`at` 行合并到同一事件 | must |
| FR-T2-03 | 提取异常类型、异常消息、stack frames | must |
| FR-T2-04 | 支持嵌套 `Caused by`；保留 cause 链 | must |
| FR-T2-05 | 选择 primary event：文件顺序中第一个带 stack frame 的异常事件；若无，则第一个 ERROR；再无则第一个 WARN | must |
| FR-T2-06 | 对未匹配的行记录 `parse_warnings`，保留行号 | must |
| FR-T2-07 | 空文件返回 0 事件 + warning，不抛异常 | must |
| FR-T2-08 | `LogEvent`/`StackFrame`/`ParsedLog` 可通过 Pydantic 序列化 | must |

## 5. 接口/数据契约

### `StackFrame`

| 字段 | 类型 | 说明 |
|---|---|---|
| `class_name` | `str` | 完全限定类名（FQN） |
| `method_name` | `str` | 方法名 |
| `file_name` | `str \| None` | `Foo.java` |
| `line_number` | `int \| None` | 行号；Native/Unknown 为空 |
| `is_native` | `bool` | `Native Method` |
| `is_reflection` | `bool` | 反射/代理帧标记（简单启发式） |
| `raw` | `str` | 原始帧文本 |

### `LogEvent`

| 字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | `str` | `evt_0001` 形式；文件内稳定 |
| `source_file` | `str` | 日志文件路径（调用方传入） |
| `line_start` / `line_end` | `int` | 事件覆盖的原始行号 |
| `timestamp` | `str \| None` | ISO 字符串；解析失败为 None + warning |
| `level` | `str \| None` | INFO/WARN/ERROR 等 |
| `thread` | `str \| None` | 线程名 |
| `logger` | `str \| None` | logger 名 |
| `message` | `str` | 日志头消息 |
| `exception_type` | `str \| None` | 最外层异常 FQN |
| `exception_message` | `str \| None` | 异常消息 |
| `stack_frames` | `list[StackFrame]` | 顶层堆栈 |
| `cause_chain` | `list[ExceptionCause]` | 嵌套 cause（类型/消息/帧） |
| `parse_warnings` | `list[str]` | 行号 + 原因 |

### `ParsedLog`

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_file` | `str` | 输入路径 |
| `events` | `list[LogEvent]` | 按出现顺序 |
| `primary_event_id` | `str \| None` | 主异常事件 |
| `warnings` | `list[str]` | 文件级警告 |

### 接口

```python
class LogParser:
    def parse(self, path: Path, source_label: str | None = None) -> ParsedLog: ...
```

- 只读文件；不修改输入。
- 不使用 LLM。
- 解析失败抛 `LogParseError` 仅用于文件不可读等致命错误；单行/单事件问题只记 warning。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T2-01 | fixture 日志解析出 3 个事件，primary event 为 ERROR 事件 | 单元测试断言事件数/ID |
| AC-T2-02 | primary event 的时间、级别、线程、logger、message 正确 | 字段断言 |
| AC-T2-03 | primary event 的 `exception_type` 为 `java.lang.IllegalStateException`，消息包含 `orderId=10086` | 字段断言 |
| AC-T2-04 | stack frames 至少 3 条；首帧为 `com.example.order.OrderService.updateStatus(OrderService.java:24)` | 字段断言 |
| AC-T2-05 | fixture 中的 `Caused by` 被解析到 `cause_chain`，其帧包含 `com.example.order.OrderMapper.updateStatus` | 单元测试 |
| AC-T2-06 | 未知格式行产生 warning，同时保留行号，不抛异常 | 单元测试 |
| AC-T2-07 | 空文件返回 0 事件 + warning | 单元测试 |
| AC-T2-08 | `ParsedLog.model_dump_json()` 可序列化 | 单元测试 |

## 7. 测试计划

### 单元

- `tests/unit/test_log_parser.py`
  - 正常 fixture：3 事件、primary ERROR、字段正确。
  - 多行堆栈：帧数与首帧正确。
  - `Caused by` / `Suppressed` / `... N more`。
  - 截断堆栈（没有后续帧）。
  - 未知行 + 行号 warning。
  - 空文件。
- `tests/unit/test_stacktrace.py`
  - 普通帧、native 帧、未知源、反射帧启发式。

### 集成

- 与 T4 `logs.search`/`logs.get_event_context` 共用同一个 fixture；T2 只验证解析结果。

### E2E

- 由 T7 的 E2E 使用 `ParsedLog`；T2 不单独做 E2E。

## 8. Fixture 设计

路径（实现时创建）：

```text
fixtures/logs/basic/incident.log
```

内容（文档约定，非最终代码）：

```text
2026-10-18 10:21:03.412 INFO  [http-nio-8080-exec-7] c.e.order.OrderController - paid callback orderId=10086
2026-10-18 10:21:03.415 WARN  [http-nio-8080-exec-7] c.e.order.OrderService - updateStatus returned rows=0, orderId=10086
2026-10-18 10:21:03.416 ERROR [http-nio-8080-exec-7] c.e.order.OrderService - failed to update order status
java.lang.IllegalStateException: update failed for orderId=10086
    at com.example.order.OrderService.updateStatus(OrderService.java:24)
    at com.example.order.OrderController.handlePaid(OrderController.java:41)
    at java.base/java.lang.Thread.run(Thread.java:840)
Caused by: org.springframework.dao.DataAccessException: mapper update failed
    at com.example.order.OrderMapper.updateStatus(OrderMapper.java:18)
    ... 2 more
```

对应 T3 fixture 中 `OrderService.updateStatus` 的 throw 行应为第 24 行。

## 9. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 日志格式差异 | v0.1 只支持一种默认 pattern | 在 spec 明确；后续增加 pattern 配置 |
| 时区/编码 | 复杂时区、GBK 不在 v0.1 | 记录限制；T8 README 说明 |
| 堆栈混排 | 日志头与 `at` 行交错 | 以“缩进/at/Caused by”规则合并；测试覆盖 |
| 异常消息多行 | 多行异常消息可能吞掉后续 | 只处理 v0.1 fixture 形态；记录开放问题 |
| 主事件选择 | 可能选错事件 | 固定规则 + fixture 断言；后续可配置 |

**开放问题**

- 是否需要支持 `[traceId]` 等 MDC 字段？v0.1 不做，T4/T6 不依赖。
- 是否需要解析 `Caused by` 的完整 cause 链还是只保留一层？v0.1 保留一层 `cause_chain`，fixture 覆盖。
- 反射帧启发式规则是否足够？先按 `java.lang.reflect`/`$$` 标记，后续扩展。

## 10. 验证命令

```bash
uv run pytest tests/unit/test_log_parser.py tests/unit/test_stacktrace.py -q
```

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T2 spec；定义日志/堆栈解析契约、fixture 和验收标准 |
