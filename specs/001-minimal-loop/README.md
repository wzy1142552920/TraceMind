# TraceMind v0.1 — 最小循环 SDD 文档

- **状态**：in progress（T1–T6 implemented；T7–T8 draft）
- **范围**：只包含 SDD 文档，不包含代码
- **父设计文档**：[TraceMind Agent 系统设计文档 v2.0](../../docs/TraceMind_Agent_System_Design_v2.md)
- **目标**：把 v0.1 walking skeleton 拆成 8 个可独立实现、可独立验收的子任务

## 1. 最小循环

```text
日志输入
  -> 解析文本日志 + Java 堆栈
  -> 单仓库 Java 源码索引
  -> 从最上层 in-project stack frame 生成种子假设
  -> Mock/DeepSeek Provider 规划工具调用
  -> ToolExecutor 执行只读工具
  -> Evidence Store 记录证据
  -> Evaluator 更新假设/确认门槛
  -> 生成 Markdown/JSON 报告 + 运行产物
```

v0.1 的 Demo 命令：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

运行产物：

```text
.tracemind/runs/<run_id>/
  run.json
  events.jsonl
  audit.jsonl
  report.md
  report.json
```

## 2. 任务索引

| ID | 任务 | 依赖 | 状态 | Spec | Task |
|---|---|---|---|---|---|
| T1 | 工程骨架 | — | implemented | [spec](./T1-project-skeleton/spec.md) | [task](./T1-project-skeleton/task.md) |
| T2 | 领域模型与日志解析 | T1 | implemented | [spec](./T2-log-parsing/spec.md) | [task](./T2-log-parsing/task.md) |
| T3 | Java 源码索引 | T1、T2 | implemented | [spec](./T3-java-index/spec.md) | [task](./T3-java-index/task.md) |
| T4 | Tool 层 | T1、T2、T3 | implemented | [spec](./T4-tools/spec.md) | [task](./T4-tools/task.md) |
| T5 | LLM Provider 与 Mock/DeepSeek | T1 | implemented | [spec](./T5-llm-provider/spec.md) | [task](./T5-llm-provider/task.md) |
| T6 | Agent Runtime、Evidence、Evaluator | T2、T3、T4、T5 | implemented | [spec](./T6-agent-runtime/spec.md) | [task](./T6-agent-runtime/task.md) |
| T7 | 报告、CLI 与运行产物 | T6 | draft | [spec](./T7-report-cli/spec.md) | [task](./T7-report-cli/task.md) |
| T8 | 文档、Demo 与最终验证 | T1–T7 | draft | [spec](./T8-docs-verification/spec.md) | [task](./T8-docs-verification/task.md) |

## 3. 依赖关系

```text
T1 工程骨架
├── T2 日志解析
│   └── T3 Java 索引
│       └── T4 Tool 层
│           └── T6 Agent Runtime
│               └── T7 报告/CLI
├── T5 LLM Provider ────────┘
└── T8 文档/验证（依赖 T1–T7）
```

推荐执行顺序：

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8
```

T5 与 T2/T3 可以并行准备；T6 必须在 T2–T5 的契约稳定后开始。

## 4. 全局契约摘要

### 4.1 模型

- `LogEvent`、`StackFrame`、`ParsedLog`（T2）
- `JavaSymbol`、`SourceMatch`、`JavaIndex`（T3）
- `ToolSpec`、`ToolRequest`、`ToolResult`、错误码（T4）
- `Message`、`ToolCall`、`LLMResponse`、`LLMProvider`（T5）
- `Evidence`、`Hypothesis`、`Budget`、`RunResult`、`StopReason`（T6）
- `Report`、`ReportSource`、`ValidationResult`（T7）

### 4.2 工具

| 工具 | 作用 |
|---|---|
| `logs.search` | 在已解析日志事件中搜索 |
| `logs.get_event_context` | 读取某个事件前后的上下文 |
| `code.find_symbol` | 按 FQN/类/方法查源码符号 |
| `code.get_source_range` | 读取指定源码行范围 |

所有工具只读、经过 ToolExecutor、受路径/输出/去重限制。

### 4.3 运行时

```text
INGESTING -> SEEDING -> PLANNING -> EXECUTING -> EVALUATING -> REPORTING
```

终态：`COMPLETED`、`INSUFFICIENT_DATA`、`STOPPED_BUDGET`、`FAILED`。

预算初值：`max_iterations=6`、`max_tool_calls=8`、`max_same_tool_same_args=1`、`per_tool_timeout_seconds=5`、`max_output_bytes=32768`。

### 4.4 报告与引用

- 报告 schema：`0.1`
- 源码引用：`repo://<relative_path>#Lx-Ly`
- 日志引用：`log://<log_file>#Lx-Ly`，或 `log://<event_id>`
- 报告状态：`confirmed` / `probable` / `insufficient_data`
- 假设状态：`candidate` / `supported` / `confirmed` / `contradicted` / `insufficient_data`

## 5. v0.1 明确不做

- SQLite/FTS5、OTel、远程 MCP/SSH/DB/Redis
- 审批/完整 Policy Engine（仅保留路径安全与只读）
- 完整 Java 知识 catalog、6 个 fixture、LLM-only ablation
- 多仓库、JSON 日志、Web UI、JDT sidecar、向量检索、多 Agent

这些属于后续迭代；v0.1 只验证“最小循环能跑通、证据/引用可复核”。

## 6. 全局验收

- T1–T8 每个任务目录都有 `spec.md` 和 `task.md`。
- Demo 命令退出码 0，生成 5 类运行产物。
- 报告包含至少一个根因候选，引用到真实源码文件/方法/行号。
- 所有引用通过校验；没有虚构源码行号。
- `events.jsonl` 和 `audit.jsonl` 能还原状态转换、工具调用和停止原因。
- 原始设计文档未被修改。
- 不写代码阶段：不创建 `src/`、`tests/`，不安装依赖。

## 7. 文档使用方式

1. 先读本 README 和 v2 设计文档的 §0–§3、§13。
2. 按任务顺序阅读对应 `spec.md`，确认 In/Out of scope、FR、AC。
3. 实现前读 `task.md`，按“spec → 测试 → 实现 → 验证”执行。
4. 每个任务完成后回填 `task.md` 的验证结果和 `spec.md` 的状态。
5. 如果发现任务之间的契约冲突，先改 spec，再改实现。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 v0.1 最小循环 SDD 文档索引与 T1–T8 任务拆分 |
