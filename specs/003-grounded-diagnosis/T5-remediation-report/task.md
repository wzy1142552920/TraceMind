# T5 — 结构化修复与报告 0.3 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T5
- **状态**：implemented
- **依赖**：T4
- **下游**：T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T5 spec、[DESIGN §9–§11](../DESIGN.md)、T4 的 RunResult。
   - 确认一次 remediation 调用覆盖所有 supported/confirmed 假设。
   - 确认只展示建议，不生成 diff、不执行。
   - 确认报告能展示同线程日志上下文与代码证据的互证关系。

2. **先写 remediation/report 测试**
   - `tests/unit/test_remediation.py`：合法/非法 action、target、证据 ID 与 evidence_source_refs 解析、上限。
   - `tests/unit/test_report_v03.py`：schema、状态、conditional、verification、同线程上下文展示。
   - `tests/unit/test_citation_validator.py`：`db://`、thread 级 `log://`、fake 标注。
   - 测试先失败。

3. **实现 remediation 模型/工具**
   - `RemediationAction` / 输入模型（extra=forbid、无 action_id）。
   - `diagnosis.propose_remediation` 控制工具/workspace 方法。
   - 校验 hypothesis/evidence/type/target/长度/去重/上限。
   - 错误码 `INVALID_REMEDIATION`；无效 action 记录 rejected。

4. **接入 REPORTING**
   - T4 runtime 在 REPORTING 发起一次 remediation LLM 调用。
   - 仅暴露 remediation 控制工具；只处理 supported/confirmed 假设。
   - 调用计入 LLM/tool 预算；预算不足时跳过并记录 limitation。
   - 无有效 action 时报告不伪造修复方案。

5. **实现报告 0.3**
   - 重写 `diagnosis/report.py` 模型：
     - ReportHypothesis / ReportRequirement / ReportRemediationAction / ReportVerification。
     - validation 扩展。
   - 状态映射、排序、conditional。
   - Markdown 模板新增鉴别诊断/验证过程/修复方案；按类别展示同线程日志上下文（线程/行范围/messages）、代码/调用链、SQL、数据证据。
   - CLI/RunStore/JSON 摘要更新。

6. **校验**
   - repo/log/db 引用；thread 级 log 上下文引用；证据 ID；run 级 confirmed；remediation 接地；fixture 标注；status 一致。
   - 诊断失败降级；remediation 失败丢弃并标记。

7. **迁移与回归**
   - 更新旧 report/citation/run_store/CLI/E2E 测试，移除 root_causes。
   - 运行 T5 验证命令并回填。

## 2. 交付物

- [x] `src/tracemind/diagnosis/remediation.py`（模型/校验）
- [x] `src/tracemind/diagnosis/workspace.py` remediation 方法
- [x] `src/tracemind/tools/control.py` propose_remediation
- [x] `src/tracemind/diagnosis/report.py` schema 0.3
- [x] `templates/report.md.j2` 更新
- [x] `src/tracemind/cli/main.py` 摘要/JSON
- [x] `src/tracemind/storage/run_store.py` 0.3
- [x] `tests/unit/test_remediation.py`
- [x] `tests/unit/test_report_v03.py`
- [x] `tests/unit/test_citation_validator.py` 扩展
- [x] 更新的 E2E/CLI/run_store 测试

## 3. Definition of Done

- [x] AC-T5-01 至 AC-T5-15 全部满足。
- [x] 每条修复建议有假设、证据、目标；无效建议不进入报告。
- [x] 报告展示同线程日志上下文与代码/工具证据，thread 级引用可校验。
- [x] supported 假设建议标记 conditional；无 confirmed 时不冒充确定修复。
- [x] 报告 schema 0.3 完整；Markdown/CLI/RunStore 一致。
- [x] db:// 引用、fixture 标注、状态一致性校验通过。
- [x] 无 key/完整 DB 行/完整源码泄露。
- [x] 全量离线测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_remediation.py tests/unit/test_report_v03.py tests/unit/test_citation_validator.py tests/e2e/test_minimal_loop.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **修复建议幻觉**：严格证据/假设/target 校验，conditional 标注；不自动执行。
- **证据洗白**：报告展示证据和 rationale，测试负向用例。
- **Fake 验证误读**：environment/note/limitations 强制；T6/T7 验收检查。
- **Schema 0.2 破坏**：无 shim；所有测试同步迁移。
- **一次 remediation 调用**：覆盖所有假设，避免多次调用成本；无效 action 丢弃。
- **config/ops/test target**：只校验非空，报告中标注未自动验证。
- **同线程上下文引用**：thread 级 source_ref 是多事件聚合，不能按单事件 ID 校验；必须验证明细项都属于该线程且行范围一致。
- **allowed evidence 与重复 action**：prompt 应直接列出可引用证据和字段上限；同一 action 重复提交只作为一次被拒，不应否定已生成的有效方案。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | Claude | `uv run pytest tests/unit/test_remediation.py tests/unit/test_report_v03.py tests/unit/test_citation_validator.py tests/e2e/test_minimal_loop.py -q` | PASS（42 passed） | 新增 remediation、报告 0.3、引用校验测试 |
| 2026-10-22 | Claude | `uv run pytest -q` | PASS（325 passed, 2 skipped） | live 测试默认跳过 |
| 2026-10-22 | Claude | `uv run ruff check .` | PASS | — |
| 2026-10-22 | Claude | `uv run mypy src` | PASS（48 source files） | — |
| 2026-10-22 | Claude | 预算跳过用例 | PASS | `test_remediation_is_skipped_when_llm_budget_is_exhausted` 覆盖 AC-T5-14 |
| 2026-10-22 | Claude | 最终全量 `uv run pytest -q` | PASS（385 passed, 6 skipped） | live 默认跳过 |
| 2026-10-22 | Claude | 接地语义/绑定证据回归 | PASS | 混合被拒尝试保留 grounded plan；全部被拒仍失败；绑定证据可用于修复建议 |
