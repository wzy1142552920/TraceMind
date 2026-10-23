# T3 — JVM 工具与证据映射 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T3
- **状态**：implemented
- **依赖**：T1、T2
- **下游**：T4、T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T3 spec、T1 bundle、T2 解析模型、v0.3 `tools/contracts.py`/`executor.py`/`evidence_mapping.py`。
   - 确认工具条件注册与 DB 工具模式一致。

2. **先写测试**
   - `tests/unit/test_jvm_tools.py`：注册、参数、过滤、映射、截断、绑定。
   - `tests/unit/test_jvm_evidence_mapping.py`：每种 kind/source_ref。
   - 测试先失败。

3. **扩展上下文**
   - `ToolContext` 增加 `artifacts: ArtifactBundle | None`。
   - 不改变 frozen 语义；现有构造调用点补 `artifacts=None`（或默认值）。
   - `build_default_registry` 增加 `artifacts` 参数，条件注册。

4. **实现工具**
   - 新增 `tools/jvm.py`，每个工具：
     - Pydantic 输入（继承 EvidenceToolMeta，`extra="forbid"`）。
     - 选择 artifact、调用 T2 parser、过滤/limit、生成有界输出。
     - 结果带 artifact_ids/warnings/truncated。
   - hot threads 需同时有 thread_cpu + thread_dump；nid 归一化；未匹配 warning。
   - 无匹配返回空结果而非错误；非法参数由 executor 拒绝。

5. **证据映射**
   - 扩展 `EvidenceKind`/`EvidenceProvenance`（若尚未有）。
   - `evidence_mapping.py` 增加 jvm.* 分支；每条证据带 artifact source_ref。
   - 行号校验：artifact id 存在、1≤start≤end≤line_count；否则跳过 + warning。
   - 复用 `MappingOutcome` 与工具绑定/去重。

6. **接线与回归**
   - registry/CLI 构造传 artifacts（CLI 在 T1 已加载）。
   - runtime 暂不使用 JVM 工具（T4 做 prompt/阶段），但注册可用。
   - 全量旧测试；ruff/mypy；回填。

## 2. 交付物

- [x] `src/tracemind/tools/jvm.py`
- [x] `src/tracemind/tools/contracts.py`（artifacts 上下文）
- [x] `src/tracemind/tools/builtin.py`（条件注册）
- [x] `src/tracemind/diagnosis/evidence.py`（新 kind/provenance）
- [x] `src/tracemind/diagnosis/evidence_mapping.py`（JVM 分支）
- [x] `tests/unit/test_jvm_tools.py`
- [x] `tests/unit/test_jvm_evidence_mapping.py`
- [x] 受影响的 registry/runtime 构造测试适配

## 3. Definition of Done

- [x] AC-T3-01 至 AC-T3-15 全部满足。
- [x] 无 artifacts/缺少所需 kind 时工具不注册。
- [x] 工具只读、无任意路径/命令/网络。
- [x] 映射 source_ref 均可在 bundle 中解析。
- [x] 绑定元数据进入 result/audit，未绑定证据不计入 requirement。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_jvm_tools.py tests/unit/test_jvm_evidence_mapping.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **ToolContext 构造**：多处直接构造；加默认值避免大范围破坏，但 CLI/runtime 必须显式传。
- **hot threads 输出**：limit 同时影响样本/匹配线程；映射只对已返回项生成证据。
- **证据去重**：thread dump 与 deadlocks 共用 source_ref 时由 ledger 合并；不要重复生成冲突 content。
- **工具注册顺序**：保持稳定顺序，prompt 测试才可断言。
- **边界**：T3 不修改 evaluator，不放松确认门槛。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_jvm_tools.py tests/unit/test_jvm_evidence_mapping.py -q` | PASS（20 passed） | 条件注册、参数、过滤、hot threads、deadlock、GC、heap、绑定、32 KiB、静态扫描、六类映射与非法引用 |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（479 passed, 6 skipped） | 默认离线；仅 live opt-in 跳过 |
| 2026-10-23 | Claude | `uv run ruff check .` | PASS | 全仓无告警 |
| 2026-10-23 | Claude | `uv run mypy src` | PASS（59 source files） | 无类型错误 |

### 6.1 实现说明

- 工具输出以有界 `dict` 经 `ToolHandlerResult` 返回；输入仍由 Pydantic 模型校验，executor 负责 32 KiB 截断、绑定、去重与审计。
- 注册依赖使用 artifact kind 集合：`thread_dump` → dump/deadlocks；`thread_dump + thread_cpu` → hot_threads；`gc_log` → summary/events；`heap_histogram` → heap。无 bundle 时完全不注册。
- 同 kind 多个 artifact 时使用 manifest 中第一个并产生 warning；不做跨 artifact 合并。
- `jvm.get_gc_summary(full_only=True)` 保留全局 summary，并额外返回基于保留窗口的 `full_scope`（含 `window_truncated`），避免把截断窗口冒充全量。
- hot threads 以归一化 nid 匹配，未匹配 TID 进入 `unmatched_tids` 且只产生 warning；不构造虚构线程名。
- 映射逐条校验 `artifact://<id>#Lx[-Ly]`：id 必须存在、`1 <= start <= end <= line_count`；非法项跳过并 warning，不使整次映射失败。
- JVM 证据统一 `provenance=USER_ARTIFACT`、`strength="strong"`；frame/lock/类名/GC summary 字段均有长度与数量上限，content 不含绝对路径或完整快照。
- 未绑定 requirement 的 JVM 证据沿用 v0.3 workspace/evaluator 规则，不能覆盖 requirement；由既有 `test_grounded_evaluator.py`、`test_tool_binding.py` 覆盖。
