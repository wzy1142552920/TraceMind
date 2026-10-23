# T5 — 报告 0.4 与 CLI Spec

- **任务 ID**：T5
- **状态**：implemented
- **依赖**：T1、T4
- **下游**：T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §8](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.3 报告 schema 0.3 能展示 evidence/hypotheses/remediation/verification，但不知道 JVM 快照来自哪里、引用了哪一行、结论受什么限制。用户需要看到“这次用了哪些用户提供的快照、哪些结论引用了快照、快照不是实时采集”。

T5 升级报告到 schema 0.4：新增 artifacts 元数据、artifact source 类别和 `artifact://` 引用校验；CLI 摘要展示 artifact/JVM 信息；自动追加快照限制。报告仍由证据/假设驱动，不因存在 artifact 自动提升状态。

**用户故事**：作为用户，我能从报告中看到使用了哪些快照（类型、行数、warning），每条 JVM 结论指向具体 artifact 行；如果引用无效或 artifact 未标注，validation 会失败；我还能清楚看到“这是时间点快照、未解析 hprof/JFR”的限制。

## 2. In scope

- `diagnosis/report.py`：schema 0.4、`artifacts[]`、artifact source、引用校验、limitations、validation。
- `cli/main.py`：run_meta/schema 0.4、artifact 数量/类型、JVM 证据摘要。
- 更新现有 0.3 schema 断言为 0.4。
- 报告/引用/CLI E2E 测试。

## 3. Out of scope

- 修改证据/覆盖/运行时（T4 已完成）。
- 新增 JVM 工具（T3）。
- case/fixture（T6）。
- live（T7）。
- 0.3 兼容 shim。
- 在报告中展示完整 artifact/dump/绝对路径/秘密。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T5-01 | 报告 schema_version=0.4；run_meta 同步 | must |
| FR-T5-02 | `artifacts[]` 含 artifact_id/kind/source_name/source_environment/line_count/truncated/warnings | must |
| FR-T5-03 | `sources` 增加 artifact 类别；只展示 id/basename/kind | must |
| FR-T5-04 | 引用校验支持 `artifact://<id>#Lx-Ly` 与 `#Lx` | must |
| FR-T5-05 | 校验 artifact 存在、行号正整数、x≤y、y≤line_count | must |
| FR-T5-06 | 无效 artifact 引用使 `citations_valid=false`，记录截断的 source_ref | must |
| FR-T5-07 | validation 增加 `artifact_citations_valid` 与 `artifacts_labeled` | must |
| FR-T5-08 | 自动 limitations：用户快照、未解析 hprof/JFR、仅快照不能确认 | must |
| FR-T5-09 | 报告 Markdown 展示 artifacts 和 JVM 证据摘要，不展示绝对路径/完整 dump | must |
| FR-T5-10 | CLI JSON/文本摘要展示 artifact 数量/类型、JVM 证据数 | must |
| FR-T5-11 | 无 artifacts 时报告仍为 0.4，artifacts=[]，限制不出现 JVM 文案 | must |
| FR-T5-12 | 退出码保持 0/1/2/3/4 | must |
| FR-T5-13 | 报告/产物无 secret、绝对 artifact 路径 | must |

## 5. 报告契约

```json
{
  "schema_version": "0.4",
  "artifacts": [
    {
      "artifact_id": "thread-dump",
      "kind": "thread_dump",
      "source_name": "thread-dump.txt",
      "source_environment": "user_provided",
      "line_count": 123,
      "truncated": false,
      "warnings": []
    }
  ],
  "sources": [
    {
      "source_ref": "artifact://thread-dump#L10-L20",
      "category": "artifact",
      "description": "thread_dump thread-dump"
    }
  ],
  "validation": {
    "citations_valid": true,
    "artifact_citations_valid": true,
    "artifacts_labeled": true
  }
}
```

- `artifacts` 顺序与 manifest 一致。
- `source_name` 仅 basename。
- `warnings` 来自 `ArtifactRecord`，最长 10 条/条 256 字符（超出截断）。
- `sources` 去重后按 source_ref 排序；JVM evidence source_ref 自然出现。
- 若 report 模型需要向后兼容，缺失 artifacts 默认 `[]`；但仍输出 schema 0.4。

### 5.1 引用校验

- 支持 scheme：`repo://`、`log://`、`db://`、`artifact://`。
- `artifact://id#Lx-Ly`：id 必须存在于 `run_result.artifacts`；1≤x≤y≤line_count。
- 单点 `#Lx` 合法。
- 非法 scheme/格式/不存在/越界：`citations_valid=false`，`artifact_citations_valid=false`。
- 只有 `artifact://` 引用参与 artifact 专用校验；其他 scheme 仍按 v0.3。
- 报告 builder 不能信任 LLM 自由文本中的引用；只校验结构化 evidence/sources/remediation 的 source_ref。

### 5.2 Limitations

自动追加（仅当有对应 artifacts）：

- “JVM snapshots are user-provided point-in-time text files; no live attach or collection was performed.”
- “Heap dump/JFR was not parsed; CPU/memory conclusions are limited to the snapshot window.”
- 如果没有任何 mechanism evidence 的 confirmed/supported JVM 假设：“No code mechanism evidence was found; JVM-only evidence cannot confirm a root cause.”
- 有 artifacts 时说明同线程上下文未强制。

去重、顺序稳定；不覆盖用户已有 limitations。

### 5.3 CLI

- `run_meta`：`schema_version=0.4`、`artifacts=[record...]`。
- JSON summary：`artifact_count`、`artifact_kinds`、`jvm_evidence_count`。
- 文本摘要：`Snapshots: N (thread_dump, gc_log, ...)`、`JVM evidence: N`。
- 无 artifacts 时不显示 Snapshot/JVM 行，保持旧输出简洁。

## 6. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T5-01 | 报告/run_meta schema 0.4 |
| AC-T5-02 | artifacts[] 字段/顺序/basename/标注正确 |
| AC-T5-03 | 无 artifacts 时 artifacts=[]，无 JVM 限制 |
| AC-T5-04 | artifact 引用合法时 citations/artifact_citations 为 true |
| AC-T5-05 | 不存在 id/越界/反向/零行引用使校验失败 |
| AC-T5-06 | 单点 `#Lx` 合法；其他 scheme 行为不变 |
| AC-T5-07 | artifacts_labeled 正确；source_environment 非 user_provided 时 false |
| AC-T5-08 | JVM limitations 自动追加且不重复；无 artifacts 不追加 |
| AC-T5-09 | Markdown 展示 artifacts/JVM 证据，无绝对路径/完整 dump |
| AC-T5-10 | CLI 摘要/JSON 字段正确；无 artifacts 时旧字段不变 |
| AC-T5-11 | 退出码不变 |
| AC-T5-12 | 报告/产物无 secret；旧 0.3 断言已迁移 |

## 7. 测试计划

- `tests/unit/test_report_v04.py`：schema、artifacts、limitations、Markdown、无 artifacts。
- `tests/unit/test_citation_v04.py`：合法/非法 artifact 引用、单点、越界、非 JVM scheme 回归。
- `tests/e2e/test_cli_v04.py`：mock 诊断 + artifacts，schema 0.4、摘要字段、无 secret。
- 更新 `tests/unit/test_report_v03.py`/schema 断言为 0.4（不保留 shim）。

## 8. 风险与开放问题

- **引用来源**：只校验结构化 source_ref；不要让 LLM 自由文本制造引用。
- **artifact records 来源**：从 `RunResult.artifacts` 取，不从 manifest 直接读，确保与实际加载一致。
- **limitations 文案**：英文/中文一致？沿用报告现有语言（英文），README 可中文说明。
- **旧测试迁移**：schema 断言统一更新；不要保留 0.3/0.4 双输出。
- **Markdown 体积**：只展示摘要/Top-N；不渲染完整 artifact。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_report_v04.py tests/unit/test_citation_v04.py tests/e2e/test_cli_v04.py -q
uv run pytest tests/unit/test_report_v03.py tests/unit/test_citation_validator.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T5 spec：schema 0.4、artifacts[]、artifact 引用、limitations、CLI 摘要 |
| 2026-10-23 | 实现并回填：报告/run_meta 0.4、artifacts[]/category、artifact 引用校验、JVM limitations、Markdown/CLI 摘要；定向 23 测试、全量 521 通过 |
