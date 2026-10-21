# T3 — LLM Usage / Latency / Provenance Spec

- **任务 ID**：T3
- **状态**：draft
- **依赖**：T1、T2
- **下游**：T4、T5、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.1 的 DeepSeek adapter 已经解析 usage，但 runtime 只记录 LLM 调用次数和 finish_reason；run.json/report/CLI 看不到 token、延迟、request ID、重试次数和实际 model。真实 live 诊断需要成本/性能可追踪，且不能把 Key 写入产物。

**用户故事**：作为开发者，我能在 run.json、报告和 CLI 摘要里看到每次 LLM 调用的 model、request ID、token、latency、attempts 和 finish_reason；报告 schema 升到 0.2，原有预算计数字段保持稳定。

## 2. In scope

- `Usage` 增加 `total_tokens`；`LLMResponse` 已有 `attempts`（T2）。
- 新增 `LLMCallRecord` 和 `LLMUsageSummary`。
- Runtime 记录每次成功/失败的 LLM 调用（model/request_id/latency/attempts/finish_reason/tool_calls/tokens/error）。
- RunResult 增加 `llm_calls`、`llm_usage`；保留 `budget_usage` 精确三个 key。
- events/run.json/report/CLI 暴露 usage。
- 报告 schema `0.2`；Jinja2 模板显示 usage 摘要。
- Secret 检查：不写入 Key/`sk-`。

## 3. Out of scope

- 价格估算/账单。
- Prompt caching 统计（若 Provider 返回可未来扩展）。
- 每次 retry attempt 的独立 latency。
- 完整 conversation replay。
- 修改 budget_usage 语义。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T3-01 | `Usage` 含 total_tokens（可空） | must |
| FR-T3-02 | 每次 LLM 调用生成 `LLMCallRecord` | must |
| FR-T3-03 | `RunResult` 含 `llm_calls` 与 `llm_usage` | must |
| FR-T3-04 | `llm.called`/`llm.error` 事件包含 usage/latency/attempts | must |
| FR-T3-05 | run.json 增加 schema_version 0.2、LLM 配置、usage、per-call records | must |
| FR-T3-06 | report schema 0.2，模板显示 usage 摘要 | must |
| FR-T3-07 | CLI Rich/JSON 显示 model/calls/tokens/latency | must |
| FR-T3-08 | `budget_usage` 仍只含 iterations/llm_calls/tool_calls | must |
| FR-T3-09 | 产物不含 Key/`sk-` | must |

## 5. 接口/数据契约

### `LLMCallRecord`

| 字段 | 类型 | 说明 |
|---|---|---|
| `llm_call_id` | `str` | `llm_0001` |
| `round` | `int` | 运行轮次 |
| `provider` | `str` | `deepseek`/`mock` |
| `model` | `str` | 实际配置 model |
| `request_id` | `str \| None` | Provider request ID |
| `started_at` | `str` | ISO |
| `latency_ms` | `int` | 包含 retry 等待的墙钟时间 |
| `attempts` | `int` | 总 attempts |
| `ok` | `bool` | 调用是否成功 |
| `finish_reason` | `str \| None` | stop/tool_calls/length/... |
| `tool_calls` | `int` | 返回的 tool call 数 |
| `input_tokens` | `int \| None` | — |
| `output_tokens` | `int \| None` | — |
| `total_tokens` | `int \| None` | — |
| `error_code` | `str \| None` | 失败时 |

### `LLMUsageSummary`

| 字段 | 默认 | 说明 |
|---|---|---|
| `calls` | 0 | LLM 调用数 |
| `failed_calls` | 0 | 失败调用数 |
| `retries` | 0 | attempts - calls（>=0） |
| `input_tokens` | None | 累加，缺失时不伪造 0 |
| `output_tokens` | None | 同上 |
| `total_tokens` | None | 同上 |
| `latency_ms` | 0 | 总墙钟 latency |

### Flow

- `RunResult.llm_calls: list[LLMCallRecord]`
- `RunResult.llm_usage: LLMUsageSummary`
- `events.jsonl`：
  - `llm.called`：call id/round/model/request_id/finish_reason/attempts/tool_calls/tokens/latency_ms
  - `llm.error`：call id/code/attempts/status_code/request_id
- `run.json`：
  - `schema_version: "0.2"`
  - `llm`: provider/model/base_url/timeout/max_tokens/max_retries
  - `llm_usage`: summary
  - `llm_calls`: records
- `report.json`：schema `0.2`，增加 `llm_usage`、`llm_calls`；模板显示 usage 摘要和每 call 一行。
- CLI `--json` 增加 model/llm_usage；Rich 显示 calls/tokens/latency/retries。
- `budget_usage` 保持 `iterations`、`llm_calls`、`tool_calls` 三个 key，值语义是逻辑调用数，不含 retry attempts。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T3-01 | Usage total_tokens / LLMResponse attempts | provider tests |
| AC-T3-02 | 每次 LLM 调用产生 LLMCallRecord | `test_runtime_observability.py` |
| AC-T3-03 | RunResult usage summary 正确 | runtime integration |
| AC-T3-04 | events/run.json/report schema 0.2 含 usage | run_store/report/E2E |
| AC-T3-05 | CLI 显示 model/calls/tokens/latency | CLI tests |
| AC-T3-06 | budget_usage 三个 key 不变 | budget/runtime tests |
| AC-T3-07 | 产物无 Key/`sk-` | secret scan |

## 7. 测试计划

### 单元

- `tests/unit/test_runtime_observability.py`
  - Mock 固定 usage → record/summary totals。
  - 失败调用记录 error/attempts。
  - budget_usage 精确 key。
- `tests/unit/test_report.py`
  - schema 0.2、llm_usage/llm_calls、模板显示。
- `tests/unit/test_run_store.py`
  - run.json LLM config/usage/records，无 secret。
- `tests/e2e/test_minimal_loop.py`
  - CLI Rich/JSON 使用量；报告 schema 0.2。

### 更新

- 所有断言 schema 0.1 的测试改为 0.2。
- 保持 `budget_usage` 测试不变。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 测试 churn | schema 0.1 → 0.2 影响报告/E2E | 集中更新；v0.1 文档保留历史 |
| usage 缺失 | Provider 不返回 usage | 字段可空，不伪造 0；summary 标记 None |
| latency 口径 | retry 等待是否计入 | 计入墙钟；record 记录 attempts |
| budget 语义 | retry 是否算 llm_calls | 不算；llm_calls 是逻辑调用数 |
| Secret | usage 元数据误带 Key | 只记录非敏感字段；secret scan |

**开放问题**

- 是否记录 cached tokens？v0.2 不做。
- 是否估算 cost？不做，避免虚假价格。
- 报告是否保留 0.1 reader？不做兼容 shim。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_runtime_observability.py tests/unit/test_report.py tests/unit/test_run_store.py tests/e2e/test_minimal_loop.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T3 spec；定义 per-call usage、summary、run/report/CLI 流向 |
