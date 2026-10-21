# T7 — 报告、CLI 与运行产物 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T7
- **状态**：implemented
- **依赖**：T6
- **下游**：T8

## 1. 实施顺序

> T7 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T7 `spec.md`，确认报告字段、状态映射、引用格式、CLI 参数、退出码。
   - 确认 T6 `RunResult` 字段足够；如缺字段，先改 T6 spec 再实现。

2. **定义报告模型**
   - `src/tracemind/diagnosis/report.py`：Report、ReportRootCause、ReportSource、ValidationResult。
   - 使用 Pydantic；schema_version=`0.1`。
   - 不引入 LLM 生成报告文本。

3. **先写报告/校验测试**
   - `tests/unit/test_report.py`：状态映射、根因/来源生成、Jinja2 模板条件分支。
   - `tests/unit/test_citation_validator.py`：repo/log 引用、无效行号、缺失证据、状态不一致。
   - 测试先失败。

4. **实现引用校验**
   - `repo://`：相对路径 + root 校验 + 行号范围。
   - `log://`：event_id 或行号范围。
   - evidence ID/状态一致性。
   - 校验失败时写 `validation` 字段并降级，不伪造通过。

5. **实现报告生成**
   - 从 `RunResult` 映射 root_causes/sources/tool_calls/limitations/stop/budget_usage。
   - 使用 Jinja2 模板 `src/tracemind/diagnosis/templates/report.md.j2` 渲染 Markdown；Python 只负责准备 `Report` 数据。
   - 不输出未脱敏敏感信息（v0.1 fixture 无敏感数据，但保留检查）。

6. **实现 Run Store**
   - `src/tracemind/storage/run_store.py`：创建 run 目录，写 run.json/events.jsonl/audit.jsonl/report.md/report.json。
   - events/audit 每行合法 JSON；run_id 唯一，不覆盖。
   - events 来自 T6 `RuntimeEvent`；audit 从 `ToolCallRecord` 派生。

7. **实现 CLI**
   - `src/tracemind/cli/main.py`：`diagnose` 命令，参数按 spec §5。
   - 连接 LogParser、JavaIndex、ToolRegistry/ToolExecutor、Mock/DeepSeek Provider、DiagnosisRuntime。
   - mock 默认脚本 `fixtures/mock/basic_plan.json`；`--mock-script` 覆盖。
   - 输出 Rich 摘要；写入运行产物。
   - 映射退出码。

8. **写 E2E**
   - `tests/e2e/test_minimal_loop.py`：运行 CLI mock，断言退出码、5 类产物、报告内容、引用校验、JSONL。
   - 证据不足/预算耗尽场景。

9. **验证并回填**
   - 运行 T7 spec 的验证命令，回填 §6。

## 2. 交付物

- [x] `src/tracemind/diagnosis/report.py`
- [x] `src/tracemind/diagnosis/templates/report.md.j2`
- [x] `src/tracemind/observability/events.py`（如需要事件序列化）
- [x] `src/tracemind/storage/run_store.py`
- [x] `src/tracemind/storage/__init__.py`
- [x] `src/tracemind/cli/main.py`（完整 diagnose）
- [x] `tests/unit/test_report.py`
- [x] `tests/unit/test_citation_validator.py`
- [x] `tests/unit/test_run_store.py`
- [x] `tests/e2e/test_minimal_loop.py`
- [x] `fixtures/mock/basic_plan.json`

## 3. Definition of Done

- [x] T7 spec 的 AC-T7-01 至 AC-T7-11 全部满足。
- [x] E2E mock 命令退出 0，生成 5 类产物。
- [x] 报告含根因、源码引用、证据 ID、限制；引用全部有效。
- [x] 证据不足/预算耗尽退出码正确。
- [x] `events.jsonl`/`audit.jsonl` 每行可解析。
- [x] 重复运行不覆盖旧目录。
- [x] 不依赖网络/真实 API Key（mock 路径）。
- [x] 报告不伪造“confirmed”；状态映射与 T6 一致。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_report.py tests/unit/test_citation_validator.py \
  tests/unit/test_run_store.py tests/e2e/test_minimal_loop.py -q
```

## 5. 开放问题 / 风险

- **Runtime 缺字段**：如果 T6 `RunResult` 缺少报告需要的 `source_refs`，优先在 T6 evidence 中补，不在 T7 重新解析源码。
- **Mock 脚本路径**：默认 `fixtures/mock/basic_plan.json`；E2E 可传 `tests/fixtures/mock_responses.json`；两者结构一致。
- **run_id 生成**：建议 `run_` + UTC 时间戳 + 短随机；确保不覆盖。
- **incident_id**：v0.1 每次运行新建；后续支持 resume/incident 复用。
- **audit 内容**：从 tool_calls 派生；路径拒绝是 error_code 的一种，v0.1 足够。
- **退出码 0 的含义**：0 只表示报告生成且状态 confirmed/probable，不代表“根因绝对正确”。
- **Markdown 模板**：确定性、可复核优先；不要为了好看引入 LLM 报告润色。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | T7 专项 pytest | 16 passed | report/citation/run_store/e2e |
| 2026-10-21 | Claude | `uv run pytest -q` | 112 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 35 source files | — |
| 2026-10-21 | Claude | 手动 CLI mock | 退出码 0；5 类产物；报告 confirmed | 引用校验通过 |
| 2026-10-21 | Claude | 异常 E2E | 证据不足退出 3；预算耗尽退出 4 | 重复运行生成不同 run 目录 |
| 2026-10-21 | Claude | Jinja2 模板 | 正常/空 sections 渲染通过 | `test_report.py` 模板用例 |
