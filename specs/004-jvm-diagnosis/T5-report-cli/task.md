# T5 — 报告 0.4 与 CLI Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T5
- **状态**：implemented
- **依赖**：T1、T4
- **下游**：T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T5 spec、[DESIGN §8](../DESIGN.md)、v0.3 report/citation 实现。
   - 确认只校验结构化 source_ref，不从 Markdown/LLM 文本提取引用。
   - 确认不保留 0.3 shim。

2. **先写测试**
   - `test_report_v04.py`、`test_citation_v04.py`、`test_cli_v04.py`。
   - 覆盖合法/非法 artifact 引用、单点、越界、无 artifacts、secret/路径。
   - 更新旧 schema 断言。
   - 测试先失败。

3. **扩展报告模型**
   - `ReportArtifact`、`artifacts`、`sources.category=artifact`。
   - `validation.artifact_citations_valid`、`artifacts_labeled`。
   - schema 0.4 常量。
   - 保持 v0.3 字段（hypotheses/remediation/verification/limitations）。

4. **扩展引用校验**
   - `_check_source_ref` 增加 artifact 分支。
   - 行号解析严格；不存在/越界失败。
   - 其他 scheme 回归。

5. **报告 builder**
   - 从 `RunResult.artifacts` 生成 artifacts。
   - sources 去重/排序；加入 artifact 类别。
   - 自动 limitations（去重）。
   - Markdown 增加 Snapshots/JVM evidence 摘要。

6. **CLI**
   - run_meta schema 0.4 + artifacts。
   - JSON/文本摘要字段。
   - 无 artifacts 分支不变。

7. **回归**
   - 更新旧测试；全量离线；ruff/mypy；回填。

## 2. 交付物

- [x] `src/tracemind/diagnosis/report.py`
- [x] `src/tracemind/cli/main.py`
- [x] `tests/unit/test_report_v04.py`
- [x] `tests/unit/test_citation_v04.py`
- [x] `tests/e2e/test_cli_v04.py`
- [x] 旧 schema 断言迁移

## 3. Definition of Done

- [x] AC-T5-01 至 AC-T5-12 全部满足。
- [x] artifact 引用 100% 可解析；非法引用明确失败。
- [x] 报告无绝对路径/完整 dump/secret。
- [x] 无 artifacts 时报告 0.4 且 JVM 限制不出现。
- [x] 退出码不变；旧测试迁移后全绿。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_report_v04.py tests/unit/test_citation_v04.py tests/e2e/test_cli_v04.py -q
uv run pytest tests/unit/test_report_v03.py tests/unit/test_citation_validator.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **artifact 行号来源**：source_ref 由 T3 映射生成；builder 不做行号猜测。
- **validation 兼容**：旧字段保留；新增字段默认 false/true 需语义正确，不能默认 true。
- **Markdown**：只展示摘要；完整 artifact 不进入报告。
- **旧测试**：schema 0.3 断言全部迁移；不新增 shim 分支。
- **CLI 输出**：无 artifacts 时避免出现空 Snapshot 行，保持 v0.3 输出兼容。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_report_v04.py tests/unit/test_citation_v04.py tests/e2e/test_cli_v04.py -q` | PASS（23 passed） | schema/artifacts/limitations/Markdown 8；artifact 引用 11；CLI 4 |
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_report_v03.py tests/unit/test_citation_validator.py tests/unit/test_report.py tests/e2e/test_minimal_loop.py -q` | PASS（30 passed） | 旧报告/引用/CLI 迁移后无回归 |
| 2026-10-23 | Claude | `uv run pytest tests/eval/test_v03_cases.py -q` | PASS（15 passed） | v0.3 三 case 报告为 0.4 且仍 confirmed |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（521 passed, 6 skipped） | 默认离线；仅 live opt-in 跳过 |
| 2026-10-23 | Claude | `uv run ruff check .` | PASS | 全仓无告警 |
| 2026-10-23 | Claude | `uv run mypy src` | PASS（59 source files） | 无类型错误 |

### 6.1 实现说明

- `Report.schema_version` 与 CLI `run_meta["schema_version"]` 均为 `0.4`；不保留 0.3 输出分支，旧测试（含 v0.3 eval/live 与 002 live）的 schema 断言统一迁移。
- `ReportArtifact` 从 `RunResult.artifacts` 按 manifest 顺序生成，字段为 id/kind/source_name/source_environment/line_count/truncated/warnings；source_name 强制 basename，warnings 最多 10 条、每条最多 256 字符。
- `ReportSource.category` 由 evidence kind 确定性映射（artifact/log/code/sql/data/evidence），sources 去重后按 `(source_ref, evidence_id)` 排序；JVM evidence 归入 `artifact` 类别。
- artifact 引用先按 `artifact://<id>#Lx[-Ly]` 严格解析，再校验 id 存在、行号为正、x≤y、y≤line_count；解析/校验失败记入 `artifact_citations_valid=false`，同时使 `citations_valid=false` 并触发原有降级；错误中的 source_ref 截断到 200 字符。
- `artifacts_labeled` 检查报告 artifacts 与已加载 records 的 id 顺序一致且全部为 `user_provided`；标注失败只记 validation 错误，不降级状态。
- 有 artifacts 时自动追加用户快照、未解析 heap dump/JFR、同线程上下文可选三条限制；仅当存在有 JVM 证据但无 mechanism 证据的 confirmed/supported 假设时追加 JVM-only 限制；全部走 `_append_limitation` 精确去重，运行时快照文案与报告常量一致。
- Markdown 新增 `## JVM 快照` 与 `## 证据来源 > JVM 快照证据`，展示 artifact 元数据、引用与校验字段；不渲染完整 dump 或绝对路径。
- CLI JSON 摘要新增 `artifact_count`、`artifact_kinds`、`jvm_evidence_count`（后者统计全部 JVM kind evidence，包括未进入报告的匹配线程证据）；文本摘要仅在存在 artifacts 时打印 `Snapshots`/`JVM evidence` 与 artifact 校验字段。退出码逻辑未改。
