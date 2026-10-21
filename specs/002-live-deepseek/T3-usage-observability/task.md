# T3 — LLM Usage / Latency / Provenance Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T3
- **状态**：implemented
- **依赖**：T1、T2
- **下游**：T4、T5、T6

## 1. 实施顺序

> T3 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T3 spec、T1 settings、T2 error metadata、现有 RunResult/report/run_store/CLI。
   - 确认 `budget_usage` 三个 key 不改变。

2. **先写 usage 测试**
   - `tests/unit/test_runtime_observability.py`：Mock usage → record/summary；失败调用；attempts/retries。
   - 报告/run store/E2E schema 0.2 断言。
   - 测试先失败。

3. **扩展模型**
   - `Usage.total_tokens`。
   - `LLMCallRecord`、`LLMUsageSummary`。
   - `RunResult.llm_calls`、`RunResult.llm_usage`。
   - 保留 `budget_usage`。

4. **Runtime 埋点**
   - 在 `provider.complete()` 周围测 latency。
   - 成功/失败都创建 LLMCallRecord；记录 attempts/request_id/tokens/finish_reason/error。
   - 汇总 usage summary；事件增加字段。
   - 不改 Evaluator 确认逻辑。

5. **报告/存储/CLI**
   - run.json 增加 schema_version 0.2、LLM config/usage/calls。
   - report schema 0.2、Report 模型/模板增加 usage。
   - CLI JSON/Rich 显示 model/calls/tokens/latency。
   - 确保无 Key/`sk-`。

6. **验证并回填**
   - 运行 T3 验证命令；更新所有 schema 0.1 断言；回填 task §6 和 spec 变更记录。

## 2. 交付物

- [x] `src/tracemind/llm/messages.py` total_tokens
- [x] `src/tracemind/diagnosis/evidence.py` LLMCallRecord/LLMUsageSummary/RunResult fields
- [x] `src/tracemind/diagnosis/runtime.py` usage/latency 埋点
- [x] `src/tracemind/diagnosis/report.py` + `templates/report.md.j2` schema 0.2/usage
- [x] `src/tracemind/storage/run_store.py` run.json usage/config
- [x] `src/tracemind/cli/main.py` usage 输出
- [x] `tests/unit/test_runtime_observability.py` 及相关测试更新

## 3. Definition of Done

- [x] AC-T3-01 至 AC-T3-07 全部满足。
- [x] 每次调用有 record；成功的调用有 tokens/latency/attempts。
- [x] run.json/report/events/CLI 显示 usage；report schema 0.2。
- [x] `budget_usage` 三 key 语义不变。
- [x] 无 Key/`sk-` 泄漏。
- [x] Mock 全量测试与 live 结构兼容。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_runtime_observability.py tests/unit/test_report.py tests/unit/test_run_store.py tests/e2e/test_minimal_loop.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **schema 更新**：多个测试断言 0.1；集中更新，避免遗漏。
- **usage 缺失**：字段可空；不要伪造 0。
- **latency 口径**：包含 retry 等待；attempts 单独记录。
- **budget 语义**：retry 不增加 `llm_calls`；只记录 attempts。
- **Secret**：不把 Key 放进配置 record；测试扫描产物。
- **Mock**：使用固定 usage；测试 totals 可确定。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | T3 专项 pytest | 12 passed | observability/report/run_store/e2e |
| 2026-10-21 | Claude | `uv run pytest -q` | 139 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 36 source files | — |
| 2026-10-21 | Claude | Mock CLI | calls=1 tokens=100/30/130 latency=0ms | schema 0.2 |
| 2026-10-21 | Claude | budget_usage | 三个原始 key 保持不变 | runtime tests |
