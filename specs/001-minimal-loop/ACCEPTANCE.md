# TraceMind v0.1 验收矩阵

- **日期**：2026-10-21
- **范围**：T1–T7 验收标准（T8 自检见末尾）
- **结论**：65 条 AC，64 条通过，1 条可选 fallback deferred（T3-AC-08）
- **验证环境**：Python 3.12.13、uv 0.11.19、tree-sitter 0.26.0、tree-sitter-java 0.23.5

> 结果来自当前 checkout 的实际命令；未执行项不写成通过。

## 1. 全局验证快照

| 检查 | 结果 |
|---|---|
| `uv sync` | 成功 |
| `uv run pytest -q` | **112 passed** |
| `uv run ruff check .` | All checks passed |
| `uv run mypy src` | Success: no issues found in 35 source files |
| Mock CLI | 退出码 0；5 类产物；报告 `confirmed`；引用校验通过 |
| Spec / Task 数量 | 8 / 8 |
| 链接检查 | 无断链 |
| 原始设计文档 | 未被修改 |

## 2. T1 — 工程骨架

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T1-01 | `uv sync` 成功并生成锁文件 | `uv sync` | PASS |
| AC-T1-02 | `tracemind --help` 包含 `diagnose` | `uv run tracemind --help`；`tests/unit/test_cli.py::test_help_lists_diagnose` | PASS |
| AC-T1-03 | `--version` 输出版本 | `uv run tracemind --version`；`test_version` | PASS |
| AC-T1-04 | pytest 可收集测试 | `uv run pytest --collect-only -q` | PASS |
| AC-T1-05 | `ruff check .` 通过 | `uv run ruff check .` | PASS |
| AC-T1-06 | `mypy src` 通过 | `uv run mypy src` | PASS |
| AC-T1-07 | T1–T8 spec/task 齐全、链接有效 | `find` + 链接检查脚本 | PASS |
| AC-T1-08 | 原始设计文档未被修改 | `docs/*.md` mtime/size 检查 | PASS |

## 3. T2 — 日志解析

专项命令：`uv run pytest tests/unit/test_log_parser.py tests/unit/test_stacktrace.py -q` → **18 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T2-01 | fixture 解析 3 个事件，primary 为 ERROR | `test_fixture_parses_three_events_and_primary_error` | PASS |
| AC-T2-02 | primary 时间/级别/线程/logger/message 正确 | `test_fixture_parses_three_events_and_primary_error` | PASS |
| AC-T2-03 | 异常类型/消息正确 | `test_fixture_exception_and_stack_frames` | PASS |
| AC-T2-04 | 至少 3 个 stack frame，首帧为 `OrderService.updateStatus` | `test_fixture_exception_and_stack_frames` | PASS |
| AC-T2-05 | `Caused by` 进入 cause_chain，帧包含 `OrderMapper.updateStatus` | `test_fixture_cause_chain` | PASS |
| AC-T2-06 | 未知行有行号 warning，不崩溃 | `test_unknown_line_records_warning_with_line_number` | PASS |
| AC-T2-07 | 空文件返回 0 事件 + warning | `test_empty_file_returns_warning` | PASS |
| AC-T2-08 | `ParsedLog.model_dump_json()` 可序列化 | `test_fixture_is_pydantic_serializable` | PASS |

补充覆盖：native/unknown/reflection/proxy 帧（`tests/unit/test_stacktrace.py`）、截断堆栈、`Suppressed`、缺失文件错误。

## 4. T3 — Java 源码索引

专项命令：`uv run pytest tests/unit/test_java_index.py -q` → **16 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T3-01 | 找到 `OrderService` 和 `updateStatus` | `test_find_symbol_class_and_method` | PASS |
| AC-T3-02 | T2 首帧解析到 `OrderService.java` / `updateStatus` / 行 24 | `test_resolve_order_service_frame` | PASS |
| AC-T3-03 | `get_source_range` 包含第 24 行 throw | `test_get_source_range` | PASS |
| AC-T3-04 | 不存在的类/方法返回空列表 | `test_resolve_missing_class_returns_empty` | PASS |
| AC-T3-05 | 嵌套类 FQN 可匹配 | `test_find_nested_class` / `test_resolve_nested_class_frame` | PASS |
| AC-T3-06 | 重载方法按行号选择候选 | `test_resolve_overloaded_method_prefers_line_range` | PASS |
| AC-T3-07 | 越界行号裁剪并标记 | `test_get_source_range_clamps` | PASS |
| AC-T3-08 | （可选）无 tree-sitter 时 regex fallback | tree-sitter 0.26.0/0.23.5 已验证可用；fallback 未实现 | **DEFERRED** |

补充覆盖：构造器、路径逃逸、索引前查询、索引统计、源码路径安全。

## 5. T4 — Tool 层

专项命令：`uv run pytest tests/unit/test_tool_executor.py tests/unit/test_tool_registry.py -q` → **17 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T4-01 | `logs.search` 命中 WARN 事件 | `test_logs_search` | PASS |
| AC-T4-02 | `logs.get_event_context` 返回上下文 | `test_logs_get_event_context` | PASS |
| AC-T4-03 | `code.find_symbol` 返回源码位置 | `test_code_find_symbol` | PASS |
| AC-T4-04 | `code.get_source_range` 包含第 24 行 | `test_code_get_source_range` | PASS |
| AC-T4-05 | `../` 路径穿越返回 `TARGET_DENIED` | `test_path_escape_is_denied` | PASS |
| AC-T4-06 | 未知工具返回 `TOOL_NOT_FOUND` | `test_unknown_tool_is_denied` | PASS |
| AC-T4-07 | 非法参数返回 `INVALID_ARGUMENTS` | `test_invalid_arguments_are_rejected` | PASS |
| AC-T4-08 | 同工具同参数重复调用不执行 | `test_duplicate_call_is_not_executed` | PASS |
| AC-T4-09 | 输出超限裁剪、`truncated=True` | `test_output_limit_truncates` | PASS |
| AC-T4-10 | 每次调用产生审计事件 | `test_audit_events_record_outcomes` | PASS |
| AC-T4-11 | 只读、不写文件、不执行命令 | 代码审查 + 工具测试 | PASS |

补充覆盖：绝对路径、符号链接逃逸、参数额外字段、输出上限、Registry 重复注册/排序。

## 6. T5 — LLM Provider

专项命令：`uv run pytest tests/unit/test_mock_provider.py tests/unit/test_deepseek_provider.py tests/unit/test_llm_contract.py -q` → **14 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T5-01 | Mock 返回脚本 tool call（ID/name/arguments 正确） | `test_scripted_responses` | PASS |
| AC-T5-02 | 第二次调用返回第二个响应；两次运行一致 | `test_scripted_responses` / `test_mock_provider_is_deterministic` | PASS |
| AC-T5-03 | 无 tool call 响应返回空列表 | `test_scripted_responses` | PASS |
| AC-T5-04 | DeepSeek fake client 正确映射 messages/tools/tool_calls | `test_deepseek_maps_messages_tools_and_tool_calls` | PASS |
| AC-T5-05 | usage 映射正确；缺失 usage 不崩溃 | `test_deepseek_maps_messages_tools_and_tool_calls` / `test_deepseek_handles_missing_content_and_usage` | PASS |
| AC-T5-06 | 非法 tool arguments JSON 抛 `LLMProviderError` | `test_deepseek_invalid_tool_arguments` | PASS |
| AC-T5-07 | 缺 API Key 抛清晰错误，不发网络请求 | `test_deepseek_missing_api_key` | PASS |
| AC-T5-08 | Mock/DeepSeek 满足同一 Provider 契约 | `tests/unit/test_llm_contract.py` | PASS |

补充覆盖：空 choices、上游错误包装、Mock 脚本缺失/坏 JSON、空 tools。

## 7. T6 — Agent Runtime / Evidence / Evaluator

专项命令：

```bash
uv run pytest tests/unit/test_runtime_state.py tests/unit/test_runtime_budget.py \
  tests/unit/test_evaluator.py tests/unit/test_runtime_seed.py \
  tests/integration/test_minimal_loop_runtime.py -q
```

结果：**17 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T6-01 | Mock + T2/T3 fixture 得到 confirmed | `test_happy_path_confirms_hypothesis` | PASS |
| AC-T6-02 | RunResult 含 stack_frame/log_event/source_code | `test_happy_path_confirms_hypothesis` | PASS |
| AC-T6-03 | source_ref 指向 OrderService.java 行范围 | `test_happy_path_confirms_hypothesis` | PASS |
| AC-T6-04 | stop=evidence_sufficient，预算正确 | `test_happy_path_confirms_hypothesis` | PASS |
| AC-T6-05 | 无 in-project frame → INSUFFICIENT_DATA，无 source_code | `test_no_in_project_frame_returns_insufficient_data` | PASS |
| AC-T6-06 | 空 tool calls 且未 confirmed → no_progress | `test_empty_plan_stops_with_no_progress` | PASS |
| AC-T6-07 | max_iterations=1 持续工具调用 → STOPPED_BUDGET | `test_budget_exhaustion_stops_with_budget_reason` | PASS |
| AC-T6-08 | 同工具同参数重复调用只执行一次 | `test_duplicate_tool_call_is_not_executed_twice` | PASS |
| AC-T6-09 | Provider 抛错 → FAILED/error，不崩溃 | `test_provider_error_fails_without_crashing` | PASS |
| AC-T6-10 | 事件包含状态/LLM/工具/证据/停止 | `test_happy_path_confirms_hypothesis` | PASS |
| AC-T6-11 | LLM 不能直接 confirmed；由 Evaluator 决定 | `tests/unit/test_evaluator.py` + runtime 代码审查 | PASS |

补充覆盖：状态转换合法性、预算默认值、无证据/证据不完整、工具错误、上下文重建。

## 8. T7 — 报告、CLI 与运行产物

专项命令：

```bash
uv run pytest tests/unit/test_report.py tests/unit/test_citation_validator.py \
  tests/unit/test_run_store.py tests/e2e/test_minimal_loop.py -q
```

结果：**16 passed**。

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T7-01 | E2E mock 命令退出码 0 | `test_happy_path_cli_and_repeat_run` | PASS |
| AC-T7-02 | 运行目录包含 5 类产物 | `test_happy_path_cli_and_repeat_run` / `test_write_all_run_artifacts` | PASS |
| AC-T7-03 | `report.json` schema 0.1 字段完整 | `test_build_confirmed_report` / `test_report_json_and_markdown` | PASS |
| AC-T7-04 | 报告含根因、源码引用、证据 ID、限制 | `test_build_confirmed_report` / E2E | PASS |
| AC-T7-05 | 所有引用校验通过 | `test_build_confirmed_report` / E2E | PASS |
| AC-T7-06 | 无效引用校验失败并降级 | `test_invalid_repo_path_is_rejected` 等引用校验测试 | PASS |
| AC-T7-07 | events/audit JSONL 每行可解析 | `test_write_all_run_artifacts` / E2E | PASS |
| AC-T7-08 | 证据不足退出 3；预算耗尽退出 4 | `test_insufficient_data_exit_code` / `test_budget_exit_code` | PASS |
| AC-T7-09 | `run.json` 不含 API Key/敏感字段 | `test_write_all_run_artifacts` / E2E | PASS |
| AC-T7-10 | 终端摘要显示状态/根因/证据数/报告路径 | `test_happy_path_cli_and_repeat_run` | PASS |
| AC-T7-11 | 重复运行生成新 run_id，不覆盖 | `test_repeated_runs_use_distinct_directories` / E2E | PASS |

补充覆盖：Jinja2 模板正常/空 sections 渲染、状态不一致降级、缺失 evidence ID、无效日志 event、有效 log 文件引用。

## 9. T8 自检

| AC | 验收标准 | 证据 | 结果 |
|---|---|---|---|
| AC-T8-01 | README 快速开始可执行 | 本 README 的 `uv sync` / `--help` 命令 | PASS |
| AC-T8-02 | Demo 命令与 CLI 参数一致 | README vs `tracemind diagnose --help` | PASS |
| AC-T8-03 | 验收矩阵覆盖 T1–T7 AC | 本文档 65 条 AC | PASS |
| AC-T8-04 | 8 spec + 8 task，链接有效 | `find` + 链接检查 | PASS |
| AC-T8-05 | 每个 spec/task 含规定章节 | 人工检查 8 个目录 | PASS |
| AC-T8-06 | Mock Demo 可离线运行 | `test_happy_path_cli_and_repeat_run` / 手动 CLI | PASS |
| AC-T8-07 | 已知限制与 v0.1/v2 差异写清楚 | README “已知限制 / v0.1 与 v2 设计” | PASS |
| AC-T8-08 | 原始文档未修改；未执行项未写成通过 | mtime/size 检查；T3-AC-08 标记 DEFERRED | PASS |

## 10. 最终命令

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

## 11. Deferred / 限制

- T3-AC-08（regex fallback）为可选功能，**DEFERRED**；tree-sitter 已验证可用。
- 真实 DeepSeek、远程 MCP、OTel、6 个 Java fixture 和 LLM-only ablation 不在 v0.1 验收范围。
- 当前只有一个合成 fixture；结果不代表生产准确率。
- 未执行项不会标记为 PASS。
