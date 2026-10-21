# TraceMind v0.2 验收矩阵

- **日期**：2026-10-21
- **状态**：IN PROGRESS（T1–T5 已实现；T5 live BLOCKED；T6 planned）
- **范围**：T1–T6
- **AC 总数**：40
- **Live 状态**：规划时未配置 `DEEPSEEK_API_KEY`；live AC 在真实运行前标记 **BLOCKED**，不得标记 PASS
- **原则**：文档阶段只定义可测试目标，不伪造实现/测试/live 结果

> 结果列为 `PLANNED` 表示尚未执行；`BLOCKED` 表示依赖外部 Key/网络，当前不可执行。实现完成后逐项回填 PASS/FAIL/BLOCKED。

## 1. T1 — Provider 配置、`.env` 与 preflight

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T1-01 | 项目根 `.env` 可加载 `DEEPSEEK_API_KEY` | `tests/unit/test_llm_config.py::test_dotenv_loads_key` | PASS |
| AC-T1-02 | 真实环境变量优先于 `.env` | `test_real_env_wins_over_dotenv` | PASS |
| AC-T1-03 | CLI 参数优先于环境变量/`.env` | `test_cli_overrides_env` | PASS |
| AC-T1-04 | 缺 Key 在解析/索引/建目录前 preflight，退出 2，提示 `.env`/环境变量 | `tests/e2e/test_live_preflight.py` | PASS |
| AC-T1-05 | DeepSeek 使用配置的 model/base URL/timeout/max tokens/max retries；默认 `deepseek-flash` + thinking disabled | `test_deepseek_uses_configured_model_and_tokens` / thinking tests | PASS |
| AC-T1-06 | run.json 记录脱敏配置，不含 Key/`sk-` | Mock E2E run.json / `public_config` 测试 | PASS |
| AC-T1-07 | Mock 路径行为不变 | 全量离线测试 / E2E | PASS |
| AC-T1-08 | `.env` 被忽略，`.env.example` 被跟踪 | `.env` ignored；`.env.example` unignored | PASS（提交后 tracked） |

## 2. T2 — Transport hardening

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T2-01 | 429/5xx 重试最多 2 次，退避 0.5s/1.0s | `tests/unit/test_deepseek_retry.py` | PASS |
| AC-T2-02 | timeout/connection 重试；连续失败后明确失败 | `test_retries_exhausted` | PASS |
| AC-T2-03 | auth/bad request/invalid arguments 不重试 | `test_auth_error_is_not_retried` / `test_invalid_tool_arguments_are_not_retried` | PASS |
| AC-T2-04 | 错误包含 code/retryable/attempts/status_code/request_id | provider error tests | PASS |
| AC-T2-05 | OpenAI SDK `max_retries=0`，传入配置 timeout | `test_openai_client_is_configured_without_sdk_retries` | PASS |
| AC-T2-06 | fake-client 重试测试不访问网络 | 测试使用注入 client + 注入 sleep | PASS |
| AC-T2-07 | 成功响应保留 attempts | retry tests `response.attempts` | PASS |

## 3. T3 — Usage / latency / provenance

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T3-01 | `Usage` 含 total_tokens；`LLMResponse` 含 attempts | provider tests | PASS |
| AC-T3-02 | Runtime 每次 LLM 调用生成 `LLMCallRecord` | `tests/unit/test_runtime_observability.py` | PASS |
| AC-T3-03 | `RunResult` 有 usage summary（calls/tokens/latency/retries） | runtime integration test | PASS |
| AC-T3-04 | events/run.json/report schema 0.2 含 usage | `test_run_store.py` / `test_report.py` / E2E | PASS |
| AC-T3-05 | CLI Rich/JSON 显示 model、calls、tokens、latency | CLI tests / manual Mock CLI | PASS |
| AC-T3-06 | `budget_usage` 仍只有 iterations/llm_calls/tool_calls | budget/runtime tests | PASS |
| AC-T3-07 | usage/artifacts 不含 Key/`sk-` | secret scan / E2E | PASS |

## 4. T4 — Live-plan resilience

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T4-01 | 下一轮 prompt 含上一轮工具调用/结果/错误/新证据摘要 | `test_text_only_repair_recovers` / second-prompt assertions | PASS |
| AC-T4-02 | text-only 响应可 repair 后恢复 | `test_text_only_repair_recovers` | PASS |
| AC-T4-03 | unknown tool/invalid args/duplicate/无新证据可 repair | `test_unknown_tool_repair_recovers` / `test_invalid_arguments_repair_recovers` / duplicate integration | PASS |
| AC-T4-04 | `finish_reason=length` 不执行半截工具；repair 或明确失败 | `test_length_finish_reason_does_not_execute_tool_call` | PASS |
| AC-T4-05 | repair 最多 2 轮且受预算限制 | `test_repair_exhaustion_stops_without_confirmation` / `test_repair_is_bounded_by_iteration_budget` | PASS |
| AC-T4-06 | 只有 Evaluator 可 confirmed；模型文本不能直接确认 | `test_repair_exhaustion_stops_without_confirmation` | PASS |
| AC-T4-07 | Mock happy path 行为不变 | `test_happy_path_confirms_hypothesis` | PASS |

## 5. T5 — Opt-in live verification

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T5-01 | 默认 `pytest` 跳过 live，不访问网络 | `uv run pytest -q`；145 passed, 2 skipped | PASS |
| AC-T5-02 | 仅 `--run-live + TRACEMIND_LIVE_TESTS=1 + Key` 运行 live | `tests/conftest.py` gate；无 Key 时 2 skipped | PASS |
| AC-T5-03 | live adapter 返回 canonical tool call + usage | `tests/live/test_live_deepseek.py::test_live_adapter_returns_usage` | BLOCKED (no key) |
| AC-T5-04 | live CLI fixture 生成 5 产物、schema 0.2、三类证据、usage，无 secret | `test_live_cli_completes_fixture` | BLOCKED (no key) |
| AC-T5-05 | 无 Key 时 live AC 明确 BLOCKED，不写 PASS | skip 输出 + 验收文档 | PASS |

## 6. T6 — Docs / release

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T6-01 | 002 README + ACCEPTANCE + T1–T6 spec/task 齐全 | `find`/链接检查 | PLANNED |
| AC-T6-02 | README 记录 `.env`、优先级、live 命令、retry/repair/usage | 文档检查 | PLANNED |
| AC-T6-03 | 包版本升到 0.2.0 | `uv run tracemind --version` / pyproject | PLANNED |
| AC-T6-04 | 离线 pytest/ruff/mypy 通过；live 状态如实记录 | 全量命令 | PLANNED |
| AC-T6-05 | 链接有效；001 specs 和 docs 设计文档未修改 | 链接检查 + mtime/size | PLANNED |
| AC-T6-06 | 无伪造 live PASS；无 Key 时保持 BLOCKED | 验收文档审查 | PLANNED |

## 7. 计划验证命令

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src

# 配置/CLI 离线测试
uv run pytest tests/unit/test_llm_config.py tests/e2e/test_live_preflight.py -q

# live opt-in（需要项目 .env 或真实环境变量中的 Key）
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q

uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider deepseek \
  --output-dir /tmp/tracemind-v02-live \
  --max-iterations 4 --max-tool-calls 6 --llm-max-tokens 800
```

## 8. 当前限制

- 文档阶段未执行任何实现 AC；所有状态为 PLANNED。
- 当前没有 `DEEPSEEK_API_KEY`，T5 的真实 live AC 为 BLOCKED。
- live 成功标准只断言结构/证据/报告，不硬编码自然语言答案；DeepSeek 输出有非确定性。
- 仍只覆盖单个合成 fixture，不代表生产准确率。
