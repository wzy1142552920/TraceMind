# TraceMind Agent 系统设计文档

- **文档版本**：1.0
- **文档状态**：原型阶段总体设计，供 Vibe Coding 按阶段实施
- **目标系统**：TraceMind Agent——面向 Java 系统故障辅助定位的本地 CLI Agent
- **主要技术栈**：Python 3.12+、Typer、Pydantic、SQLite、OpenTelemetry、MCP
- **核心原则**：证据驱动、默认只读、权限可控、操作可追踪、结论可复核

---

## 1. 项目概述

### 1.1 项目背景

TraceMind Agent 是一个面向 Java 应用和微服务的故障辅助定位 Agent。它读取用户指定的业务日志、索引本地 Java 源码，按需在经过授权的情况下查询 SSH、数据库、Redis 等诊断信息，并根据可复核的证据形成根因候选和诊断报告。

系统不是简单的聊天机器人，也不是直接执行任意命令的自动化脚本。LLM 主要负责规划调查方向、提出和更新假设、解释证据；确定性代码负责数据解析、权限控制、工具执行、预算限制、审计、引用校验和停止条件。

### 1.2 目标

1. 分析业务异常、数据库/Redis 中间件问题和性能问题。
2. 从异常堆栈、日志模板、SQL、traceId 等线索定位到本地 Java 源码。
3. 支持多模块 Maven/Gradle 项目和多个微服务仓库。
4. 在显式授权后，通过只读工具获取远程系统证据。
5. 建立可控的诊断循环，避免无穷调用、重复调查和无依据结论。
6. 生成带有证据 ID、源码行号、日志位置和限制说明的 Markdown/JSON 报告。
7. 对 Agent 的规划、LLM 请求、工具调用、权限决策、证据变化和停止原因提供 Trace、结构化日志和审计。

### 1.3 非目标

第一版不实现：

- 自动修复源码或配置。
- 生产环境写操作。
- 任意 Shell、任意 SQL 或任意 Redis 命令执行。
- 自动重启、发布、扩缩容或修改生产数据。
- 未经授权的任意网络探测。
- 以向量检索代替基础索引和精确检索。
- 将 LLM 自报的置信度直接当作统计概率。
- 无证据地声称根因已确认。

### 1.4 目标用户和运行方式

- 主要用户：开发人员、值班工程师、SRE、技术支持人员。
- 第一版运行方式：本地 CLI。
- 源码位置：用户本地工作区。
- 日志输入：用户指定本地文件或目录。
- 远程取证：默认关闭，显式启用并受目标白名单、只读权限和审批控制。
- 环境选择：必须显式指定或由可信配置明确解析；不能在未指定时默认生产环境。

---

## 2. 典型使用场景

### 2.1 业务异常

输入异常日志和服务名，Agent 合并多行堆栈、识别异常类和方法，定位源码，检查参数校验、业务分支、事务和调用关系，输出根因候选及证据。

### 2.2 数据库问题

输入 SQL 超时、连接池耗尽或锁等待日志。Agent 先分析本地日志和源码；如果仍缺证据，在授权后调用只读数据库工具获取慢查询、活跃会话、锁等待和连接池相关信息。

### 2.3 Redis 问题

分析连接超时、缓存击穿线索、慢命令、内存压力和 key 访问路径；必要时调用受限的 Redis 只读工具。禁止默认执行 `KEYS *`、无限扫描、`MONITOR` 或任何写命令。

### 2.4 性能问题

针对接口耗时、CPU、内存或线程阻塞问题，结合日志时间线、源码调用路径和授权的系统指标进行分析。线程转储等可能有额外影响的操作需要审批。

### 2.5 多仓库微服务

允许多个仓库注册到同一工作区；索引记录仓库 ID、服务名、Git commit、文件 hash 和索引时间，避免同名类混淆，并明确源码与实际部署版本可能不一致。

---

## 3. 总体架构

```text
CLI / 用户
   |
   v
Workspace & Incident Context
   |-- 仓库、环境、日志路径、traceId、时间范围
   |
   v
Diagnosis Runtime（受控诊断循环）
   |-- 日志解析引擎
   |-- Java 代码索引与搜索
   |-- Planner / LLM Client
   |-- Hypothesis Evaluator
   |-- Tool Registry / ToolExecutor
   |      |-- Policy Engine
   |      |-- Approval Gate
   |      |-- 本地工具
   |      `-- MCP Client
   |             |-- SSH 只读诊断
   |             |-- Database 只读诊断
   |             `-- Redis 只读诊断
   |-- Evidence Store
   |-- Stop / Budget Controller
   `-- Report Generator
           |
           v
Storage
   |-- SQLite 索引和元数据
   |-- Evidence / Incident 数据
   `-- Markdown / JSON 报告

横切基础设施：
  Observability：Trace、结构化日志、指标、审计
  Security：权限、脱敏、审批、目标白名单
  Configuration：模型、工作区、MCP、预算、安全策略
```

### 3.1 架构分层

1. **CLI 层**：参数解析、交互、输出、退出码。
2. **应用层**：用例编排，如索引仓库、解析日志、诊断故障、导出报告。
3. **领域层**：Incident、LogEvent、JavaSymbol、Evidence、Hypothesis、DiagnosisResult 等模型和规则。
4. **诊断运行时**：循环状态机、计划生成、工具调度、证据评估、停止控制。
5. **工具层**：工具契约、注册表、参数校验、执行器、本地工具、MCP 适配器。
6. **基础设施层**：SQLite、文件存储、LLM 提供商、MCP 客户端、日志、Trace、审计。
7. **安全层**：访问策略、目标白名单、审批、脱敏、审计与风险控制。安全层横切所有执行路径。

### 3.2 设计原则

- **证据优先**：根因结论必须绑定证据，不得用语言流畅度代替证据。
- **确定性安全边界**：LLM 不直接决定最终权限，不可绕过执行器。
- **默认拒绝**：未配置、未授权或无法验证的操作默认拒绝。
- **本地优先**：先分析本地日志和源码，只有证据不足且获准时才访问远程系统。
- **工具最小权限**：只开放具体、受限、可审计的操作，不开放通用命令执行。
- **可复核**：源码和日志引用必须能定位到真实文件、行号、版本或时间。
- **有界运行**：迭代、工具调用、耗时、输出、并发和上下文都有预算。
- **可测试**：LLM 和 MCP 均可替换为 Mock，固定案例可重复运行。
- **可观测**：每个关键决策和外部操作都能关联到 Trace、事件和证据。

---

## 4. 推荐技术栈

| 能力 | 推荐方案 | 说明 |
|---|---|---|
| Python | Python 3.12+ | 锁定依赖版本 |
| CLI | Typer + Rich | 命令行、表格、进度和报告摘要 |
| 数据模型 | Pydantic | 输入、配置、工具契约和报告 Schema 校验 |
| 本地数据库 | SQLite | 元数据、索引、事件查询和诊断记录 |
| 全文检索 | SQLite FTS5 | 源码、日志模板和文本线索的精确检索 |
| Trace | OpenTelemetry API/SDK | 标准 Span、父子关系、可选 OTLP |
| 结构化日志 | structlog 或标准 logging JSON Formatter | JSONL 事件 |
| MCP | 官方 Python MCP SDK | 与受控 MCP Server 通信 |
| 测试 | pytest、pytest-cov | 单元、集成、安全和端到端测试 |
| 配置 | YAML + Pydantic Settings | 配置校验和环境变量注入 |
| Java 索引 | 首版轻量解析；后续可接 Tree-sitter/JDT | 不把正则推断的调用关系冒充完整调用图 |

不要在原型第一阶段引入过多基础设施。先用 SQLite FTS5 和精确搜索解决主要问题，再根据评估数据决定是否引入向量检索或外部服务。

---

## 5. 代码目录设计

```text
TraceMind/
├── pyproject.toml
├── README.md
├── configs/
│   ├── app.yaml
│   ├── workspace.yaml
│   ├── mcp_servers.yaml
│   ├── security_policy.yaml
│   └── observability.yaml
├── src/TraceMind/
│   ├── __init__.py
│   ├── cli/
│   │   ├── main.py
│   │   ├── commands.py
│   │   └── render.py
│   ├── core/
│   │   ├── models.py
│   │   ├── errors.py
│   │   ├── ids.py
│   │   └── clock.py
│   ├── workspace/
│   │   ├── manager.py
│   │   ├── repository.py
│   │   ├── version.py
│   │   └── access_policy.py
│   ├── indexing/
│   │   ├── coordinator.py
│   │   ├── java_symbols.py
│   │   ├── source_map.py
│   │   ├── dependency_parser.py
│   │   ├── call_graph.py
│   │   ├── search.py
│   │   └── sqlite_store.py
│   ├── log_analysis/
│   │   ├── reader.py
│   │   ├── classifier.py
│   │   ├── text_parser.py
│   │   ├── json_parser.py
│   │   ├── stacktrace.py
│   │   ├── context.py
│   │   ├── correlation.py
│   │   └── redaction.py
│   ├── diagnosis/
│   │   ├── runtime.py
│   │   ├── planner.py
│   │   ├── hypothesis.py
│   │   ├── evidence_store.py
│   │   ├── evaluator.py
│   │   ├── stopping.py
│   │   └── report.py
│   ├── tools/
│   │   ├── registry.py
│   │   ├── executor.py
│   │   ├── contracts.py
│   │   └── builtin/
│   │       ├── log_tools.py
│   │       └── code_tools.py
│   ├── mcp/
│   │   ├── client.py
│   │   ├── manager.py
│   │   └── adapters/
│   │       ├── ssh.py
│   │       ├── database.py
│   │       └── redis.py
│   ├── security/
│   │   ├── policy.py
│   │   ├── approval.py
│   │   ├── targets.py
│   │   ├── redaction.py
│   │   └── audit.py
│   ├── observability/
│   │   ├── context.py
│   │   ├── tracing.py
│   │   ├── logging.py
│   │   ├── events.py
│   │   ├── metrics.py
│   │   ├── exporters.py
│   │   ├── retention.py
│   │   └── queries.py
│   ├── storage/
│   │   ├── database.py
│   │   ├── incident_repository.py
│   │   ├── artifact_store.py
│   │   └── observability_repository.py
│   └── llm/
│       ├── client.py
│       ├── prompts.py
│       └── schemas.py
├── mcp_servers/
│   ├── ssh_server/
│   ├── database_server/
│   └── redis_server/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── e2e/
│   └── fixtures/
│       ├── repos/
│       ├── logs/
│       └── expected/
├── evals/
│   ├── incident_cases.yaml
│   ├── runner.py
│   └── metrics.py
└── docs/
    ├── architecture.md
    ├── tool-contracts.md
    ├── security-model.md
    ├── observability.md
    └── acceptance.md
```

目录可随实际仓库调整，但领域模型、诊断循环、工具执行、安全、可观测性和存储必须保持清晰边界。

---

## 6. 核心领域模型

### 6.1 Incident

表示一次故障事件，可以有多次诊断运行。

建议字段：

- `incident_id`
- `title`
- `service`
- `environment`
- `started_at`
- `time_range`
- `trace_ids`（业务链路 Trace ID，不同于 Agent 自身的 `trace_id`）
- `log_sources`
- `repository_ids`
- `status`
- `created_at`

特别注意：业务系统日志中的 `traceId` 是被调查系统的链路标识；TraceMind 自己的 `trace_id` 是 Agent 执行链标识。两者必须用不同字段名存储，不能混淆。

### 6.2 LogEvent

统一日志事件模型：

- `event_id`
- `source_file`
- `line_start`
- `line_end`
- `timestamp`
- `level`
- `service`
- `thread`
- `logger`
- `message`
- `exception_type`
- `stack_frames`
- `business_trace_id`
- `span_id`
- `request_id`
- `fields`
- `parser_type`
- `parse_warnings`

### 6.3 JavaSymbol

- `symbol_id`
- `repo_id`
- `file_path`
- `qualified_name`
- `symbol_type`
- `signature`
- `start_line`
- `end_line`
- `commit_hash`
- `file_hash`
- `language`

同名类必须按 `repo_id`、文件路径和版本区分。

### 6.4 Evidence

- `evidence_id`
- `kind`
- `claim`
- `source_ref`
- `observed_at`
- `supports`
- `contradicts`
- `hypothesis_ids`
- `tool_call_id`（如来自工具）
- `trace_id`
- `run_id`
- `content_hash`（可选）
- `redaction_status`

### 6.5 Hypothesis

- `hypothesis_id`
- `statement`
- `status`：`candidate`、`supported`、`contradicted`、`unresolved`
- `evidence_ids`
- `counter_evidence_ids`
- `missing_evidence`
- `score`
- `score_type`

评分是候选排序依据，不直接解释为概率。

### 6.6 DiagnosisResult

- `incident_id`
- `run_id`
- `trace_id`
- `status`
- `summary`
- `root_causes`
- `evidence_ids`
- `tool_calls`
- `recommended_actions`
- `limitations`
- `started_at`
- `completed_at`

---

## 7. 工作区和 Java 源码索引

### 7.1 工作区管理

支持注册多个仓库，每个仓库必须有稳定的 `repo_id`。记录：

- 仓库根目录真实路径。
- 服务名和可选模块名。
- Maven/Gradle 类型。
- 当前 Git commit（如果可用）。
- 允许访问的目录。
- 索引状态、最近索引时间和错误信息。

所有路径必须先规范化并解析真实路径；禁止通过 `..`、符号链接或路径别名越过授权根目录。

### 7.2 索引策略

第一版四层索引：

1. **仓库与版本层**：仓库 ID、服务名、Git commit、文件 hash。
2. **Java 符号层**：包、类、接口、方法、签名和行号。
3. **依赖与调用候选层**：Maven/Gradle 依赖、Controller/Service/Repository 候选关系。
4. **业务线索层**：日志模板、SQL、Redis key 前缀、HTTP/RPC 路径、配置引用。

使用 SQLite FTS5 支持全文搜索。优先精确搜索、符号搜索和日志模板检索；根据评估结果再决定是否加入 AST 或向量检索。

### 7.3 建议 SQLite 表

- `repositories`
- `source_files`
- `java_symbols`
- `symbol_edges`
- `code_artifacts`
- `index_runs`

要求：

- 支持增量索引和删除文件后的索引清理。
- 通过 hash 判断文件是否变化。
- 每个源码引用包含仓库、路径、行号和 commit/hash。
- 正则或启发式推断的调用边必须标记为候选，不得冒充完整运行时调用图。
- 如果源码版本与线上部署版本无法确认一致，报告必须声明版本限制。

### 7.4 CodeIndex 接口

```python
from pathlib import Path
from typing import Protocol

class CodeIndex(Protocol):
    def index_repository(self, root: Path, repo_id: str) -> str: ...
    def search_symbols(
        self, query: str, repo_ids: list[str] | None = None
    ) -> list["JavaSymbol"]: ...
    def find_log_statement(
        self, text: str, repo_ids: list[str] | None = None
    ) -> list["SourceLocation"]: ...
    def find_sql(
        self, sql_fragment: str, repo_ids: list[str] | None = None
    ) -> list["SourceLocation"]: ...
    def get_callers(self, qualified_name: str) -> list["JavaSymbol"]: ...
    def get_callees(self, qualified_name: str) -> list["JavaSymbol"]: ...
```

---

## 8. 日志解析引擎

### 8.1 解析流水线

1. 流式读取文件并保留原始行号。
2. 判断文本日志、JSON 日志或未知格式。
3. 识别并合并多行异常堆栈。
4. 提取时间、级别、线程、服务、logger、业务 traceId、requestId。
5. 关联同一业务 Trace、时间窗和服务的日志事件。
6. 生成结构化 LogEvent、解析警告和原始位置引用。
7. 在发送到 LLM 前进行敏感字段脱敏和长度限制。

### 8.2 异常堆栈

必须处理：

- `Caused by`
- `Suppressed`
- `... N more`
- Java 常见异常和嵌套异常
- 日志头和堆栈混排
- 不完整或被截断的堆栈
- 同一文件内多个事件相邻出现

### 8.3 边界情况

- 日志轮转和多文件输入。
- 缺失或格式异常的时间戳。
- 时区和时间范围。
- 错误 JSON。
- 超长行和超大文件。
- 不同服务的字段命名差异。
- traceId 跨文件关联。
- 敏感字段识别与脱敏。
- 恶意日志内容或 Prompt Injection。

日志内容是不可信数据，不能作为 Agent 的系统指令。解析器必须有最大行长、最大事件大小和总输入预算。

### 8.4 日志到源码的定位优先级

1. 堆栈中的完全限定类、方法和行号。
2. 异常类型、方法名和包名。
3. 唯一日志模板。
4. SQL、表名、Redis key 前缀、HTTP/RPC 路径。
5. 业务 traceId、时间线和上下游服务关系。

每个匹配结果应返回置信依据和来源引用；匹配不唯一时应保留多个候选，而不是强行选定一个。

---

## 9. 诊断运行时与自主循环

### 9.1 状态机

```text
CREATED
  -> LOCAL_ANALYSIS
  -> HYPOTHESIS
  -> INVESTIGATING
  -> EVALUATING
  -> COMPLETED
  -> INSUFFICIENT_DATA
  -> AWAITING_APPROVAL
  -> BUDGET_EXHAUSTED
```

终态应按实际状态机实现，不应让多个终态同时成立。必要时定义 `FAILED` 和 `CANCELLED`，并明确每个状态允许的转换。

### 9.2 诊断流程

1. 校验输入、工作区、环境和路径权限。
2. 创建 `incident_id`、`run_id`、Agent `trace_id`。
3. 解析日志并提取关键异常、业务 Trace 和时间线。
4. 搜索源码、日志模板、SQL 和相关配置。
5. 初始化根因假设及所需证据。
6. 评估当前证据和反证。
7. 判断本地证据是否足够；足够则生成报告，不调用远程工具。
8. 如证据不足，Planner 提出下一步调查计划。
9. ToolExecutor 校验工具 Schema、目标、策略、预算和审批。
10. 执行工具并对结果脱敏、截断、记录 Trace/日志/审计。
11. 将结果转为证据，关联假设并更新评分。
12. 检查是否有新证据、是否重复调用、是否达到预算或停止条件。
13. 生成报告并校验所有证据和源码引用。
14. 保存结果、事件和最终状态。

### 9.3 预算初值

这些是原型起始值，需根据测试调整：

```yaml
diagnosis:
  max_iterations: 12
  max_tool_calls: 20
  max_same_tool_same_args: 2
  total_timeout_seconds: 300
  per_tool_timeout_seconds: 20
  max_evidence_items: 200
  max_context_chars: 60000
  max_output_bytes_per_tool: 32768
  max_parallel_tools: 4
```

预算必须由确定性代码强制执行，而不是只写进 Prompt。对同一工具和相同参数重复调用应有去重和限次机制。无进展、超时、取消、等待审批或预算耗尽时，应给出明确停止原因。

### 9.4 假设评分

可使用候选排序分数：

`S(h) = Σ(w_i × support_i) - Σ(v_j × contradiction_j) - λ × uncertainty(h)`

要求：

- 这是排序分数，不是经过校准的概率。
- 同源日志副本或重复证据不能被重复计权。
- 记录评分变化及触发变化的证据 ID。
- LLM 自报 confidence 不可直接作为评分。
- `confirmed` 必须满足明确、严格且可测试的证据门槛。
- 证据不足时使用 `insufficient_data` 或 `investigating`。

### 9.5 停止条件

- 证据达到明确的结论门槛。
- 所有可用调查方向已完成。
- 无新证据或连续无进展。
- 迭代、工具、时间、输出或上下文预算耗尽。
- 需要审批但尚未获批。
- 用户取消。
- 安全策略拒绝进一步调查。

停止事件必须记录具体原因、预算使用量和未解决的问题。

---

## 10. Tool 系统与契约

### 10.1 统一数据结构

`ToolSpec`：

- `name`
- `description`
- `risk`
- `timeout`
- `max_output_bytes`
- `requires_approval`
- `read_only`
- `input_schema`
- `target_type`

`ToolRequest`：

- `incident_id`
- `run_id`
- `trace_id`
- `tool_call_id`
- `tool_name`
- `arguments`
- `actor`
- `target_id`

`ToolResult`：

- `ok`
- `tool_name`
- `data`
- `error_code`
- `error_message`（脱敏）
- `source`
- `observed_at`
- `duration_ms`
- `truncated`

稳定错误码包括：

- `TARGET_DENIED`
- `TIMEOUT`
- `OUTPUT_LIMIT`
- `APPROVAL_REQUIRED`
- `INVALID_ARGUMENTS`
- `TOOL_NOT_FOUND`
- `POLICY_DENIED`
- `REMOTE_UNAVAILABLE`
- `AUDIT_UNAVAILABLE`

### 10.2 执行链

```text
Agent Planner
  -> Tool Registry
  -> Schema Validation
  -> Target Validation
  -> Policy Engine
  -> Approval Gate（如需要）
  -> ToolExecutor
  -> MCP Client / Local Tool
  -> MCP Server 二次校验（远程工具）
  -> Result Sanitizer
  -> Evidence Store
  -> Trace + Structured Logs + Audit
```

模型不得直接执行任意 Shell、任意 SQL、任意 Redis 命令，也不得直接指定任意 IP、端口、主机名、数据库实例或远程路径。目标必须由管理员配置的 ID 白名单解析。

### 10.3 本地工具

建议：

- `logs.search`
- `logs.read_range`
- `logs.get_event_context`
- `code.search_symbols`
- `code.find_log_statement`
- `code.find_sql`
- `code.get_callers`
- `code.get_callees`
- `workspace.list_repositories`
- `index.get_status`

本地工具仍必须检查路径、文件大小、输出上限和授权目录。

---

## 11. MCP 远程诊断工具

远程功能默认关闭；第一版只提供经过白名单配置的只读操作。MCP Server 必须进行独立的目标和参数校验，不能只信任客户端。

### 11.1 SSH

建议工具：

- `ssh.list_hosts`
- `ssh.search_logs`
- `ssh.read_log_range`
- `ssh.get_process_info`
- `ssh.get_system_metrics`
- `ssh.get_thread_dump`
- `ssh.check_service`

约束：

- 禁止 `ssh.execute(command)` 形式的任意命令。
- 主机 ID 和路径必须在管理员配置的白名单内。
- 使用只读或受限账户。
- `get_thread_dump` 等可能影响性能或包含敏感信息的操作应要求审批。
- 禁止模型构造任意目标 IP、端口和命令字符串。

### 11.2 Database

建议工具：

- `db.list_instances`
- `db.test_connection`
- `db.get_slow_queries`
- `db.get_active_sessions`
- `db.get_lock_waits`
- `db.get_connection_stats`
- `db.explain_query`
- `db.execute_readonly_query`

约束：

- 默认使用只读账号。
- 优先固定查询模板和参数化查询。
- 对 SQL 进行解析/白名单校验；禁止 DDL、DML 和多语句绕过。
- 限制执行时间、返回行数、扫描规模和输出字节数。
- `EXPLAIN ANALYZE` 可能实际执行查询，不默认开放。
- 只读查询也可能带来性能影响，需要超时和资源限制。

### 11.3 Redis

建议工具：

- `redis.list_instances`
- `redis.test_connection`
- `redis.get_server_info`
- `redis.get_client_stats`
- `redis.get_slowlog`
- `redis.get_memory_stats`
- `redis.check_key`
- `redis.get_key_sample`

约束：

- 禁止写命令。
- 禁止默认开放 `KEYS *`、无限 `SCAN` 和 `MONITOR`。
- 对 key 采样设定数量、时间和输出上限。
- 对敏感 key/value 做脱敏，不默认导出完整数据。

### 11.4 MCP 安全要求

- MCP 客户端与服务端双重校验。
- 目标通过管理员配置的 ID 白名单映射。
- 凭据通过安全配置或环境注入，不进入 Prompt、报告、普通日志和审计明文。
- 工具返回内容视为不可信输入。
- 远程调用具有连接/读取/总超时、取消、输出限制和并发限制。
- 所有调用记录 `tool_call_id`，并关联 Trace、审计和证据。

---

## 12. 安全与权限模型

### 12.1 默认策略

- `default_action: deny`
- 本地只读只允许已授权工作区。
- 远程目标必须预先登记。
- 生产写操作、任意 Shell、DDL/UPDATE/DELETE、Redis 写、自动重启和发布均禁止。
- 未指定环境时不默认为生产，也不允许模糊选择目标。
- 远程调查必须显式启用。

### 12.2 路径安全

- 规范化并解析真实路径。
- 拒绝目录穿越、未授权符号链接和越界路径。
- 限制文件大小、行长度、读取范围和总读取量。
- 对文件读取和索引结果记录仓库 ID、文件 hash 和行号。

### 12.3 人工审批

审批内容必须明确显示：

- 操作名称和工具。
- 真实目标 ID 和环境。
- 参数摘要。
- 风险级别与潜在影响。
- 是否只读、预估耗时和输出范围。
- 审批过期时间。

审批绑定具体请求。获批后再次执行完整权限校验；不得因审批而扩大工具权限。

### 12.4 脱敏

- LLM 调用前脱敏日志、源码片段和工具结果。
- 普通日志只记录脱敏摘要，不保存密钥或敏感原文。
- 报告对个人信息、凭据和敏感 SQL 参数进行脱敏。
- 证据原文与普通日志分离存储，按最小权限访问。
- 脱敏规则本身需要测试，不能仅依赖 LLM 自觉隐藏数据。

---

## 13. Trace、结构化日志、审计与指标

### 13.1 四类数据职责

| 类型 | 主要用途 | 示例 |
|---|---|---|
| Trace / Span | 还原一次运行的调用链 | LLM → ToolExecutor → MCP → Evidence |
| 结构化日志 | 记录运行事件和错误 | 工具超时、状态变化、计划摘要 |
| 审计日志 | 记录授权、审批与操作事实 | 目标获准或被拒绝 |
| Evidence Store | 保存诊断事实和来源 | 源码行号、日志区间、慢查询记录 |
| Metrics | 统计耗时、失败率和预算 | 工具调用耗时、Token、停止次数 |

### 13.2 ID

- `trace_id`：一次 Agent 诊断执行。
- `span_id`：一次操作。
- `parent_span_id`：父操作。
- `incident_id`：一个故障事件。
- `run_id`：一次实际运行。
- `tool_call_id`：一次工具调用。
- `evidence_id`：一条诊断证据。

业务日志里的 Trace ID 必须命名为 `business_trace_id` 或类似字段，避免和 Agent 自身 `trace_id` 混淆。

### 13.3 必须记录的事件

- `diagnosis.started/completed/failed`
- `agent.state.changed`
- `agent.plan.created`
- `llm.request/response/error`
- `tool.execution.started/completed/failed`
- `security.policy.allowed/denied`
- `approval.requested/approved/rejected`
- `evidence.created/linked/contradicted`
- `hypothesis.created/updated/rejected`
- `agent.stop_triggered`
- `report.generated/validation_failed`
- `observability.write_failed/export_failed`

### 13.4 Trace 结构示例

```text
diagnosis.run
├── logs.parse
├── code.search
├── agent.iteration
│   ├── llm.call
│   ├── agent.plan
│   ├── tool.execute
│   │   ├── security.policy.check
│   │   ├── approval.wait
│   │   ├── mcp.request
│   │   └── result.sanitize
│   └── evidence.update
├── hypothesis.evaluate
└── report.generate
```

### 13.5 本地存储建议

```text
.TraceMind/
├── observability/
│   ├── traces/YYYY-MM-DD.jsonl
│   ├── logs/YYYY-MM-DD.jsonl
│   ├── audit/YYYY-MM-DD.jsonl
│   └── observability.db
└── incidents/<incident_id>/
    ├── evidence.jsonl
    ├── report.md
    └── report.json
```

原型使用 JSONL + SQLite + OpenTelemetry SDK；OTLP 导出可选且默认关闭。普通日志、Trace、审计和证据应有各自的保留策略。审计写入失败时，受保护工具默认 fail closed。

### 13.6 建议 CLI

```bash
TraceMind trace list --limit 20
TraceMind trace show <trace_id>
TraceMind trace span <span_id>
TraceMind trace tools --trace-id <trace_id>
TraceMind trace summary <trace_id>

TraceMind logs query --incident-id <incident_id>
TraceMind logs query --level ERROR --since 1h
TraceMind audit list --incident-id <incident_id>
```

至少支持按 `trace_id`、`incident_id`、`run_id`、`tool_call_id`、工具名、事件名、级别、状态、起止时间筛选，并限制最大输出。

### 13.7 指标

- `TraceMind.diagnosis.total`
- `TraceMind.diagnosis.duration`
- `TraceMind.diagnosis.failures`
- `TraceMind.agent.iterations`
- `TraceMind.tool.calls`
- `TraceMind.tool.duration`
- `TraceMind.tool.timeouts`
- `TraceMind.tool.denied`
- `TraceMind.llm.calls`
- `TraceMind.llm.duration`
- `TraceMind.llm.tokens.input`
- `TraceMind.llm.tokens.output`
- `TraceMind.evidence.count`
- `TraceMind.observability.write_failures`

指标标签不得包含 `trace_id`、完整 URL、SQL、任意路径、用户输入或异常原文，以免高基数和敏感信息泄露。

---

## 14. Evidence Store 与报告

### 14.1 证据原则

证据必须可复核，不能只保存 LLM 的自然语言总结。每条证据至少包含来源、观察时间、关联假设和原始引用。

引用示例：

- `repo://order-service/src/main/java/com/example/OrderService.java#L120-L134`
- `log://inc_0001/app.log#L540-L558`
- `mcp://staging-db-01/slow-query/query-0007`

远程数据应记录目标 ID、采集时间、工具名和必要的脱敏摘要。

### 14.2 报告格式

支持 Markdown 和 JSON。JSON 建议字段：

```json
{
  "schema_version": "1.0",
  "incident_id": "inc_0001",
  "run_id": "run_0001",
  "trace_id": "trace_abc123",
  "status": "probable",
  "summary": "基于现有证据的简要总结",
  "root_causes": [
    {
      "hypothesis_id": "hyp_001",
      "statement": "根因候选",
      "score": 4.2,
      "score_type": "ranking_score",
      "evidence_ids": ["ev_001"],
      "counter_evidence_ids": [],
      "missing_evidence": []
    }
  ],
  "sources": [],
  "tool_calls": [],
  "recommended_actions": [],
  "limitations": []
}
```

以上仅为 Schema 示例，实际报告不得使用示例中的虚构结论作为固定答案。

### 14.3 报告要求

- 区分事实、推断、假设和建议。
- 每条根因候选引用支持证据和反证。
- `confirmed` 必须通过严格证据门槛；否则使用 `probable`、`investigating` 或 `insufficient_data`。
- 所有源码行号、证据 ID 和工具调用引用必须存在且可复核。
- 记录源码 commit/hash，提示线上版本不确定的限制。
- 说明未执行的远程调查、被拒绝的工具、缺失证据和预算停止原因。
- 不在报告中输出凭据或未脱敏的敏感数据。

---

## 15. 配置设计

建议将配置分为应用、工作区、MCP、安全策略和可观测性五类。

### 15.1 应用配置示例

```yaml
app:
  name: TraceMind
  mode: local_cli
  log_level: INFO

diagnosis:
  max_iterations: 12
  max_tool_calls: 20
  max_same_tool_same_args: 2
  total_timeout_seconds: 300
  per_tool_timeout_seconds: 20
  max_evidence_items: 200
  max_context_chars: 60000
  max_output_bytes_per_tool: 32768
  max_parallel_tools: 4

remote:
  enabled: false
  require_explicit_environment: true
```

### 15.2 安全策略示例

```yaml
security:
  default_action: deny
  allow_local_read: true
  allow_remote_tools: false
  allow_production_write: false
  allow_arbitrary_shell: false
  allow_arbitrary_sql: false
  allow_redis_write: false
  require_approval_for:
    - ssh.get_thread_dump
  protected_tools_fail_closed_on_audit_error: true
```

### 15.3 可观测性配置示例

```yaml
observability:
  enabled: true
  tracing:
    enabled: true
    exporter: local
    otlp_enabled: false
  logging:
    format: jsonl
    level: INFO
    max_file_mb: 50
    max_total_mb: 500
    retention_days: 14
  audit:
    enabled: true
    retention_days: 180
  redaction:
    enabled: true
    max_attribute_chars: 2048
    max_event_bytes: 32768
    store_full_llm_content: false
    store_full_tool_output: false
```

配置数值为原型初值，需根据数据敏感性、磁盘预算和实际负载调整。秘密必须通过环境变量或安全凭据管理注入，不得提交到版本库。

---

## 16. CLI 命令规划

第一版建议实现：

```bash
# 初始化本地配置
TraceMind init

# 管理仓库
TraceMind workspace add
TraceMind workspace list

# 索引管理
TraceMind index build
TraceMind index status

# 日志分析
TraceMind logs inspect ./incident.log

# 诊断
TraceMind diagnose --log ./incident.log --service order-service --environment staging --no-remote

# 工具与 MCP
TraceMind tools list
TraceMind mcp status

# 事件与报告
TraceMind incident show <incident_id>
TraceMind report export <incident_id>

# 评估
TraceMind eval run

# 源码检索
TraceMind code search "OrderService"

# Trace / 日志 / 审计
TraceMind trace list --limit 20
TraceMind trace show <trace_id>
TraceMind logs query --incident-id <incident_id>
TraceMind audit list --incident-id <incident_id>
```

支持 `--repo`、`--trace-id`（业务链路 ID 应使用明确命名）、`--since`、`--until`、`--no-remote`、`--dry-run`、`--resume INCIDENT_ID`。恢复运行时必须重新校验当前权限、目标白名单和审批状态。

---

## 17. 测试策略与验收标准

### 17.1 测试分层

- `tests/unit`：解析器、模型、评分、策略、脱敏、预算和存储。
- `tests/integration`：SQLite、索引、ToolExecutor、MCP Mock、Trace 和审计。
- `tests/security`：路径穿越、越权目标、危险 SQL、Prompt Injection、输出上限、审计失败。
- `tests/e2e`：固定故障场景从输入到报告的完整流程。
- `evals`：诊断质量、引用准确率、工具使用效率和安全行为的回归评估。

### 17.2 必测日志场景

- 混合文本和 JSON。
- 多行异常、`Caused by`、`Suppressed`、`... N more`。
- 坏 JSON、缺时间戳、时区差异。
- 超大日志、超长行、轮转文件。
- traceId 跨文件和跨服务关联。
- 脱敏与 Prompt Injection 防护。

### 17.3 必测索引场景

- 两个仓库存在同名类，索引不能混淆。
- 文件更新、删除后索引同步。
- 源码引用行号真实存在。
- 多模块 Maven/Gradle 项目。
- 索引中断后可恢复。
- 源码版本不确定时报告必须声明。

### 17.4 必测安全场景

- 未授权主机和路径穿越。
- 未知工具和非法参数。
- 危险 SQL、任意 Shell 和 Redis 写命令。
- 审批拒绝、审批过期和审批后参数变化。
- 超时、取消、超大输出和重复调用。
- 恶意工具返回值和 Prompt Injection。
- 密钥不会出现在普通日志、Trace、报告和导出中。
- 审计不可用时受保护工具拒绝执行。

### 17.5 六个固定 E2E 故障案例

1. 业务异常：参数或业务分支导致异常。
2. 数据库超时：慢查询或连接池耗尽线索。
3. Redis 超时：连接或命令耗时问题。
4. 接口性能：请求耗时异常。
5. CPU 高：线程或热点路径线索。
6. 内存问题：分配压力或内存相关异常线索。

测试使用固定日志、最小 Java fixture 仓库、Mock LLM 和 Mock MCP，不依赖真实生产系统。测试断言应验证证据引用、状态和工具行为，不要硬编码唯一自然语言答案。

### 17.6 原型质量门槛

- Fixture 关键日志字段解析正确率 ≥95%。
- 有可定位堆栈的样本，源码文件 Top-1 命中率 ≥90%。
- 报告中的源码引用均真实可复核。
- 未授权工具成功执行次数为 0。
- 安全负向测试全部通过。
- 所有固定 E2E 案例通过结构化断言。
- 超时、预算耗尽和无证据场景能够安全停止并输出明确状态。
- Trace 可还原完整关键调用链，工具调用、审计和证据可通过 ID 关联。

这些门槛只用于原型质量控制，不代表已经证明达到竞品水平；需要增加独立测试集和基线对比才能评估真实能力。

---

## 18. 实施路线图

### 阶段 1：工程骨架

- 初始化 Python 项目、依赖锁定、配置和 CLI。
- 定义核心领域模型和统一错误码。
- 建立 SQLite 基础设施和测试框架。

**完成标准**：可安装、CLI 可运行、基础测试通过。

### 阶段 2：工作区与源码索引

- 实现仓库注册、多仓库元数据、增量索引。
- 实现 Java 符号和 FTS5 搜索。
- 实现源码引用与版本标记。

**完成标准**：多仓库同名类不混淆，行号可验证，更新/删除能同步。

### 阶段 3：日志解析

- 实现文本/JSON 分类、堆栈合并、字段提取、traceId 关联和脱敏。
- 加入大文件、错误输入和资源预算处理。

**完成标准**：日志 fixture 通过解析测试和准确率门槛。

### 阶段 4：本地诊断循环

- 实现状态机、Planner、Hypothesis、Evidence Store、Evaluator 和停止条件。
- 先接 Mock LLM，再接实际 LLM Provider。
- 实现 Markdown/JSON 报告及引用校验。

**完成标准**：本地日志与源码可形成可追溯的诊断报告。

### 阶段 5：安全与可观测性

- 实现 Policy Engine、审批、脱敏和审计。
- 实现统一 Trace、JSONL 日志、指标和 SQLite 查询。
- ToolExecutor 统一埋点，验证异常路径和审计失败策略。

**完成标准**：所有关键步骤可追踪，越权测试全部拒绝。

### 阶段 6：MCP SSH 只读工具

- 固定主机 ID、路径白名单和只读工具。
- 加入超时、输出限制、审计和 Mock Server 测试。

**完成标准**：无任意命令执行入口，授权和拒绝路径均可审计。

### 阶段 7：数据库只读工具

- 固定查询模板、参数化、超时和行数限制。
- 验证 SQL 白名单和危险查询拒绝。

**完成标准**：只读查询受限、危险语句不能执行。

### 阶段 8：Redis 只读工具

- 实现安全信息、慢日志、内存统计和受限 key 采样。
- 禁止默认开放危险或无限操作。

**完成标准**：无写操作、扫描和输出有界。

### 阶段 9：E2E 与评估

- 完成六类故障 fixture。
- 建立评估 Runner、指标和回归基线。
- 输出测试报告、已知缺陷和下一步计划。

**完成标准**：固定 E2E、质量门槛和安全测试全部通过。

每阶段都必须先运行测试并交付实际测试结果。不得通过删除断言、硬编码预期根因、吞掉异常或跳过安全校验来让测试通过。

---

## 19. Vibe Coding 总体实施指令

请将本文作为 TraceMind Agent 的系统级设计依据，按阶段实现，不要一次性生成大量未经验证的代码。

1. 先检查现有仓库、依赖、CLI、数据模型、LLM Client、ToolExecutor、MCP 和存储实现。
2. 输出现有实现与本设计的差距清单，标注可复用代码和需要调整的接口。
3. 先搭建核心模型、配置、错误码和测试框架。
4. 按实施路线图逐阶段完成，每阶段独立提交可运行代码和测试。
5. 安全、权限、预算、审计和停止条件必须由确定性代码强制执行，不依赖 Prompt。
6. 所有外部工具必须通过 ToolExecutor；不允许绕过权限、审计或可观测性。
7. LLM 与 MCP 均提供 Mock，以保证测试可重复且不依赖外部生产环境。
8. 报告结论必须有证据 ID 和可复核来源；证据不足时明确返回 `insufficient_data`。
9. 每阶段结束后提供：变更文件清单、架构差异、实际测试命令与结果、已知缺陷、剩余风险和下一阶段计划。
10. 不得伪造测试结果，不得通过硬编码案例答案来获得表面通过。
11. 先实现 CLI 原型和本地优先能力，再启用远程 MCP；远程访问默认关闭。
12. 保持模块边界和类型契约稳定，避免将所有逻辑写入单个 Agent 类或单个超大文件。

---

## 20. 最终交付清单

系统第一版至少交付：

- [ ] 可安装的 Python 包和 CLI。
- [ ] 配置文件模板与初始化命令。
- [ ] 多仓库工作区管理。
- [ ] Java 源码索引、符号搜索和引用定位。
- [ ] 混合日志解析与异常堆栈关联。
- [ ] 本地诊断状态机和受控 Agent Loop。
- [ ] Tool Registry、ToolExecutor、统一工具契约。
- [ ] 安全策略、目标白名单、审批和脱敏。
- [ ] Evidence Store、Hypothesis Evaluator 和停止条件。
- [ ] Markdown/JSON 诊断报告及引用校验。
- [ ] Trace、结构化日志、审计、指标和查询 CLI。
- [ ] SSH、数据库、Redis 的受限只读 MCP 适配器（按阶段交付）。
- [ ] 单元、集成、安全、E2E 测试。
- [ ] 固定故障案例和评估 Runner。
- [ ] 架构、工具契约、安全模型、可观测性和验收文档。

## 21. 设计结论

TraceMind Agent 应建设成一个**证据驱动、权限受控、可追溯的 Java 故障定位系统**，而不是把所有能力堆在一个通用 Agent 循环里。

- 日志解析和源码索引提供本地事实。
- LLM 负责提出调查方向、整理证据和更新假设。
- ToolExecutor、Policy Engine 和 Approval Gate 决定操作是否允许执行。
- MCP 提供经过限制的远程只读取证能力。
- Evidence Store 和报告校验保证结论可复核。
- Trace、结构化日志、审计和指标覆盖整个执行生命周期。
- 评估框架通过固定案例衡量准确性、证据质量、工具效率和安全性。

第一版优先完成本地诊断闭环和安全基础设施，再逐步接入远程工具。任何阶段都必须保持可测试、可回滚、可解释和可验证。
