# T7 — 报告、CLI 与运行产物 Spec

- **任务 ID**：T7
- **状态**：draft
- **依赖**：T6
- **下游**：T8
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T6 已能跑出 `RunResult`，但用户需要的是可执行的 CLI 和可复核的报告。T7 负责把假设/证据/工具调用转换为 Markdown/JSON 报告，校验引用，写出运行产物，并提供 `tracemind diagnose` 命令。

**用户故事**：作为用户，我运行一条命令，能得到终端摘要和一个 `.tracemind/runs/<run_id>/` 目录；报告里的每个源码/日志引用都能点回真实位置。

## 2. In scope

- 报告 JSON schema `0.1` 和 Markdown 报告。
- 引用校验：`repo://`、`log://`、证据 ID、状态一致性。
- 运行产物：
  - `run.json`
  - `events.jsonl`
  - `audit.jsonl`
  - `report.md`
  - `report.json`
- CLI `tracemind diagnose`，连接 T2–T6。
- Rich 终端摘要。
- 退出码约定。
- Mock/DeepSeek Provider 选择。
- `--output-dir`、`--mock-script`、预算覆盖参数。

## 3. Out of scope

- Web UI、OTel、OTLP、远程 MCP、审批。
- 长期保留/轮转/加密。
- 报告的自然语言润色（v0.1 用确定性模板）。
- 多 incident 管理、数据库存储。
- JSON 日志、多仓库。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T7-01 | 生成 `report.json`（schema 0.1），字段完整 | must |
| FR-T7-02 | 生成 `report.md`，包含摘要/根因/证据/源码/工具/限制 | must |
| FR-T7-03 | 校验源码引用：文件存在、行号范围有效 | must |
| FR-T7-04 | 校验日志引用：event_id 存在或行号范围有效 | must |
| FR-T7-05 | 校验证据 ID 存在、根因引用的证据存在、状态一致 | must |
| FR-T7-06 | 写 `run.json`/`events.jsonl`/`audit.jsonl` | must |
| FR-T7-07 | CLI `diagnose` 连接 LogParser/JavaIndex/ToolExecutor/Provider/Runtime | must |
| FR-T7-08 | 支持 `--provider mock|deepseek`；mock 使用 `--mock-script` | must |
| FR-T7-09 | 退出码：0 成功、1 错误、2 用法、3 证据不足、4 预算耗尽 | must |
| FR-T7-10 | 终端摘要显示状态、根因、证据数、报告路径 | must |
| FR-T7-11 | 运行产物在 `.tracemind/runs/<run_id>/`，可重复运行 | must |

## 5. 接口/数据契约

### CLI

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock \
  --mock-script tests/fixtures/mock_responses.json \
  [--output-dir .tracemind/runs] \
  [--max-iterations 6] \
  [--max-tool-calls 8]
```

- `--log`：日志文件路径（必填）。
- `--repo`：仓库根目录（必填）。
- `--service`：服务名（必填）。
- `--provider`：`mock`（默认）或 `deepseek`。
- `--mock-script`：provider=mock 时使用；默认 `fixtures/mock/basic_plan.json`。
- `--output-dir`：默认 `.tracemind/runs`。
- `--max-iterations`、`--max-tool-calls`：覆盖预算。
- `--json`：只输出 JSON 摘要（可选）。

### 报告 JSON

```json
{
  "schema_version": "0.1",
  "incident_id": "inc_...",
  "run_id": "run_...",
  "service": "order-service",
  "status": "probable",
  "summary": "...",
  "root_causes": [
    {
      "hypothesis_id": "hyp_001",
      "statement": "...",
      "status": "supported",
      "evidence_ids": ["ev_..."],
      "source_refs": ["repo://...", "log://..."],
      "missing_evidence": []
    }
  ],
  "sources": [
    {
      "source_ref": "repo://src/main/java/com/example/order/OrderService.java#L24-L30",
      "kind": "source_code",
      "verified": true
    }
  ],
  "tool_calls": [
    {
      "tool_call_id": "call_1",
      "tool_name": "code.get_source_range",
      "ok": true,
      "error_code": null,
      "duration_ms": 3
    }
  ],
  "limitations": [],
  "stop": {
    "reason": "evidence_sufficient",
    "state": "COMPLETED"
  },
  "budget_usage": {
    "iterations": 2,
    "llm_calls": 2,
    "tool_calls": 2
  },
  "validation": {
    "citations_valid": true,
    "evidence_ids_valid": true,
    "status_consistent": true
  }
}
```

### 报告状态映射

| Runtime 结果 | Report status |
|---|---|
| 任一 hypothesis `confirmed` | `confirmed` |
| 任一 hypothesis `supported` | `probable` |
| 无 supported/confirmed，或 `INSUFFICIENT_DATA` | `insufficient_data` |
| `STOPPED_BUDGET` 且有 supported | `probable` + limitation |
| `FAILED` | `insufficient_data` + error limitation |

### 引用格式

- 源码：`repo://<relative_path>#Lx-Ly`；行号 1-based，包含端点。
- 日志：`log://<event_id>` 或 `log://<log_file>#Lx-Ly`。
- 证据 ID：`ev_...`；假设 ID：`hyp_...`；工具调用：`call_...`/`tc_...`。

### 引用校验

1. `repo://`：相对路径在 repo root 内；文件存在；行号范围在文件内。
2. `log://event_id`：event_id 在 `ParsedLog.events` 中。
3. `log://file#Lx-Ly`：文件匹配输入日志；行号范围有效。
4. 根因引用的 evidence ID 必须存在于 `RunResult.evidence`。
5. `confirmed` 必须有 confirmed hypothesis；否则状态降级。
6. 报告不得包含伪源码/伪事件引用。

### 运行产物

```text
.tracemind/runs/<run_id>/
  run.json        # run metadata: provider/model/state/stop/budget/service/log/repo
  events.jsonl    # state/llm/tool/evidence/stop events
  audit.jsonl     # tool calls: tool, args_hash, ok/error, duration
  report.md       # human-readable
  report.json     # schema 0.1
```

- `events.jsonl`/`audit.jsonl` 每行一个合法 JSON。
- `run.json` 不含 API Key/完整敏感内容。
- 重复运行创建新 run_id，不覆盖旧目录。

### 退出码

| 退出码 | 条件 |
|---|---|
| 0 | 报告生成且状态为 confirmed/probable |
| 1 | 运行时/IO/Provider 不可恢复错误 |
| 2 | CLI 用法错误 |
| 3 | 报告状态 insufficient_data |
| 4 | stop_reason=budget_exhausted / STOPPED_BUDGET |

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T7-01 | E2E mock 命令退出码 0 | CLI 测试 |
| AC-T7-02 | 运行目录包含 5 类产物 | 文件断言 |
| AC-T7-03 | `report.json` 符合 schema 0.1，字段完整 | JSON/schema 测试 |
| AC-T7-04 | 报告含根因候选、源码引用、证据 ID、limitations | 内容断言 |
| AC-T7-05 | 所有引用校验通过；`validation.citations_valid=true` | 校验器测试 |
| AC-T7-06 | 构造无效引用时校验失败，报告状态/标记正确 | 单元测试 |
| AC-T7-07 | `events.jsonl`/`audit.jsonl` 每行可解析 | 测试 |
| AC-T7-08 | 证据不足时退出码 3；预算耗尽时退出码 4 | CLI 测试 |
| AC-T7-09 | `run.json` 不含 API Key/敏感字段 | 内容检查 |
| AC-T7-10 | 终端摘要显示状态/根因/证据数/报告路径 | CLI 快照/字符串断言 |
| AC-T7-11 | 重复运行生成新 run_id，不覆盖旧产物 | CLI 测试 |

## 7. 测试计划

### 单元

- `tests/unit/test_report.py`：状态映射、根因/来源生成、schema。
- `tests/unit/test_citation_validator.py`：repo/log 引用、无效行号、缺失证据、状态不一致。
- `tests/unit/test_run_store.py`：5 类产物、JSONL 可解析、run_id 不覆盖。

### 集成/E2E

- `tests/e2e/test_minimal_loop.py`：
  - 运行 CLI mock，断言退出码/产物/报告内容/引用。
  - 证据不足/预算耗尽场景的退出码。
  - Mock 脚本使用 T5 fixture，不访问网络。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 行号漂移 | 源码被修改后引用失效 | 校验失败降级并标记；报告注明本地索引版本 |
| 状态不一致 | Runtime 状态与报告状态映射错误 | 固定映射表 + 单元测试 |
| 产物覆盖 | 重复运行写同一目录 | run_id 唯一；不覆盖 |
| 审计内容 | 从 tool_calls 派生，缺少路径决策细节 | v0.1 接受；后续 T4 审计收集器直接落盘 |
| 真实 Provider | live 运行可能失败/不稳定 | E2E 用 Mock；live 可选；错误退出 1 |
| 报告模板 | 确定性模板可能过于简单 | v0.1 先保证可复核；后续 LLM 润色 |

**开放问题**

- `report.json` 的 `incident_id` 是否应跨 run 复用？v0.1 每次生成新的 incident/run；后续支持 resume/incident 管理。
- `events.jsonl` 的 schema 是否需要版本号？v0.1 每行含 `type`/`timestamp`/`data`；后续加 `schema_version`。
- audit 是否要记录路径拒绝的原始参数？v0.1 记录 args_hash/错误码，不记录敏感原文。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_report.py tests/unit/test_citation_validator.py \
  tests/unit/test_run_store.py tests/e2e/test_minimal_loop.py -q
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T7 spec；定义报告 schema、引用校验、运行产物、CLI 和退出码 |
