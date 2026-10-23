# T4 — 覆盖模型与运行时 Spec

- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T3
- **下游**：T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §7](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.3 evaluator 用硬编码的 `LOG_KINDS` / `CODE_KINDS` 计算覆盖，确认门槛还要求主异常线程的同线程日志上下文。JVM 问题通常是跨线程/全局的：CPU 热点在其他线程，OOM 由堆整体增长导致；如果仍强制同线程上下文，会触发错误 repair，甚至无法确认有充分快照+代码证据的根因。

T4 把覆盖改为 `symptom` / `mechanism` 两类：日志、栈、JVM 快照、DB 行提供症状；源码、调用路径、SQL、注解、配置、库结构提供机制。确认门槛的其他部分（替代假设、refute、工具证据、discriminating requirement）不变。提供 artifacts 时，同线程上下文从强制改为可选；无 artifacts 时保持 v0.3 行为。

**用户故事**：作为诊断运行时，当用户提供 JVM 快照时，我能让热点线程/GC/堆事实成为症状证据，再要求代码机制；我不会因为没有“同线程日志上下文”而错误地拒绝一个跨线程根因。当没有快照时，我仍像 v0.3 一样要求同线程上下文，避免同步请求类问题漏看日志。LLM 仍不能设置状态，所有确认由确定性代码完成。

## 2. In scope

- `diagnosis/evidence.py`：新 kind/provenance、`RunResult.artifacts`。
- `diagnosis/evaluator.py`：`SYMPTOM_KINDS`/`MECHANISM_KINDS`、覆盖 warning、同线程参数。
- `diagnosis/runtime.py`：artifacts 注入、同线程规则、repair/completion、cause-chain seed。
- `diagnosis/prompts.py`：artifact 摘要、JVM 通用指导、cause chain 展示。
- ToolContext/registry 接线（T3 已提供，T4 在 runtime 使用）。
- 单元/集成/回归测试：旧三 case 行为不变，新增 JVM 场景。

## 3. Out of scope

- 报告 0.4（T5）。
- 两个 case/fixture（T6）。
- live（T7）。
- 根据 artifact 自动预先生成假设/证据（仍由 LLM 自主规划）。
- 领域 catalog、case 特判、JVM 调优知识库。
- 修改 v0.3 的替代假设/refute/工具绑定规则。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T4-01 | `SYMPTOM_KINDS` 包含日志/栈/JVM/DB_ROW；`MECHANISM_KINDS` 包含源码/调用路径/SQL/注解/配置/库结构 | must |
| FR-T4-02 | 确认要求至少一个 symptom 和至少一个 mechanism；缺失分别给出明确 warning | must |
| FR-T4-03 | 原有替代假设、refute、discriminating requirement、工具证据规则不变 | must |
| FR-T4-04 | `run` 接受 `artifacts: ArtifactBundle | None`；结果携带 records | must |
| FR-T4-05 | 有 artifacts 时同线程上下文要求关闭；无 artifacts 时保持 v0.3 | must |
| FR-T4-06 | `required_thread`/`thread_context_assessed`/`stop_repair_reason`/`complete_if_confirmed` 使用同一规则 | must |
| FR-T4-07 | ToolContext 携带 artifacts，registry 注册对应 JVM 工具 | must |
| FR-T4-08 | prompt 展示 artifact 摘要（id/kind/source_name/line_count/warnings），不展示全文 | must |
| FR-T4-09 | system prompt 增加通用 JVM 分析指导，不含 case 特判 | must |
| FR-T4-10 | 用户 prompt 展示 cause chain；seed 匹配在主栈失败时尝试 cause frames | must |
| FR-T4-11 | 工具可见性仍遵循 v0.3 协议阶段（propose → assess → investigate） | must |
| FR-T4-12 | 无 artifacts 时 JVM 工具不出现，prompt 不出现 artifact 段 | must |
| FR-T4-13 | 预算/repair/stop/event 语义不变；JVM 调用计入预算 | must |
| FR-T4-14 | JVM 场景中只有快照无 mechanism 时 evaluator 不得 confirmed | must |
| FR-T4-15 | 旧 v0.3 三 case 离线确认结果不回归 | must |

## 5. 契约

### 5.1 覆盖

```python
SYMPTOM_KINDS = frozenset({
    EvidenceKind.LOG_EVENT,
    EvidenceKind.LOG_THREAD_CONTEXT,
    EvidenceKind.STACK_FRAME,
    EvidenceKind.THREAD_DUMP,
    EvidenceKind.THREAD_CPU,
    EvidenceKind.GC_EVENT,
    EvidenceKind.GC_SUMMARY,
    EvidenceKind.HEAP_SUMMARY,
    EvidenceKind.DB_ROW,
})
MECHANISM_KINDS = frozenset({
    EvidenceKind.SOURCE_CODE,
    EvidenceKind.CALL_PATH,
    EvidenceKind.SQL,
    EvidenceKind.ANNOTATION,
    EvidenceKind.CONFIG,
    EvidenceKind.DB_SCHEMA,
})
```

- `_evaluate_hypothesis` 的 `tool_coverage` 判定保持：至少一条绑定并评估为 supports 的工具证据。
- 新增/替换 coverage warning：`missing_symptom_evidence`、`missing_mechanism_evidence`。
- 旧 `log_coverage`/`code_coverage` 字段若被外部测试引用，保留只读属性或同步迁移；不保留两套判定逻辑。
- 排序分不要求 LLM confidence；可沿用现有公式，symptom/mechanism 的计数替换 log/code。

### 5.2 同线程规则

```python
def requires_same_thread_context(self) -> bool:
    return self._primary.thread is not None and self._artifacts is None
```

- `required_thread()` 只在规则为真时返回主线程。
- `evaluate_current()` 传 `require_log_thread_context=self.requires_same_thread_context()`。
- `thread_context_assessed()` 仅在规则为真时参与 repair/complete。
- 有 artifacts 时 report limitations 增加“no same-thread log context required”。
- 这条规则不能由 LLM 设置/覆盖。

### 5.3 运行时

```python
class DiagnosisRuntime:
    def __init__(..., artifacts: ArtifactBundle | None = None): ...
    def run(...) -> RunResult: ...
```

- `RunResult.artifacts: list[ArtifactRecord]`（默认空列表）。
- 初始 seed：沿用 v0.3；不自动把整个 artifact 变成 evidence（JVM 证据由工具查询产生，确保绑定/评估）。
- prompt 的 artifact 摘要来自 bundle.records；没有 artifacts 时省略该段。
- `_incident_lines`：显示主异常及 cause chain（最多 5 层，避免膨胀）。
- `_find_seed_matches`：主栈无匹配时遍历 cause frames，使用同一匹配逻辑；不改变 seed 语义。
- 工具注册：`build_default_registry(..., artifacts=self._artifacts)`。

### 5.4 Prompt 指导

System prompt 增加（通用，非 case）：

- CPU：先看线程 CPU 热点，按 nid 映射线程转储；区分业务线程与 GC/编译线程；用 GC 摘要、死锁/锁状态排除 GC 压力和锁竞争。
- 内存/OOM：结合 GC 摘要（Full GC 频率、GC 后堆是否回落）、堆直方图主导类、代码中的无界集合/缓存/大对象；单次快照不能证明泄漏，必须有代码机制。
- 所有 artifact 结论标注“用户提供的时间点快照”，不得声称实时采集。
- 无对应 artifact 时不得假设工具可用。

## 6. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T4-01 | symptom/mechanism 集合与 DESIGN 一致，旧 kind 映射正确 |
| AC-T4-02 | 只有 symptom 无 mechanism 时不能 confirmed，warning 明确 |
| AC-T4-03 | 只有 mechanism 无 symptom 时不能 confirmed |
| AC-T4-04 | 完整 symptom+mechanism+工具证据+替代排除+discriminating 时可 confirmed |
| AC-T4-05 | v0.3 refute/替代假设/单假设规则未放松 |
| AC-T4-06 | 有 artifacts 时主线程存在也不要求同线程上下文，repair 不再报 missing_thread_context |
| AC-T4-07 | 无 artifacts 时主线程存在仍强制同线程上下文，v0.3 行为不变 |
| AC-T4-08 | RunResult 携带 artifact records，无绝对路径 |
| AC-T4-09 | prompt 含 artifact 摘要/工具，无 artifacts 时不含 artifact 段 |
| AC-T4-10 | prompt 含 JVM 通用指导，不含 case 名称/期望答案 |
| AC-T4-11 | cause chain 被展示，cause 帧可用于 seed 匹配 |
| AC-T4-12 | JVM 工具调用计入预算/审计，可见性遵循协议阶段 |
| AC-T4-13 | 旧 v0.3 三 case 集成/eval 全部通过 |

## 7. 测试计划

- `tests/unit/test_evidence_categories.py`：集合、coverage warning。
- `tests/unit/test_evaluator_v04.py`：symptom/mechanism、同线程开关、替代/refute 回归。
- `tests/unit/test_prompt_v04.py`：artifact 摘要、JVM 指导、cause chain、无 artifacts 分支。
- `tests/integration/test_v04_runtime.py`：mock 脚本两场景；artifacts 注入；同线程放宽；RunResult records。
- `tests/eval/test_v03_cases.py` 回归（T6 可扩展参数化 helper）。

## 8. 风险与开放问题

- **覆盖语义变化**：旧 case 必须仍满足新集合；若失败优先检查 evidence mapping，不得放宽确认。
- **同线程规则**：只能由 artifacts 是否存在决定；不要加“主线程是否在 artifact 中”等额外条件。
- **artifact seed**：不自动生成 JVM evidence，避免未绑定证据污染 coverage；由工具调用产生。
- **prompt 膨胀**：摘要只放 records（≤8 条），不放大段文本。
- **cause chain**：限制层数和帧数，避免 prompt 过大；解析器已有帧上限。
- **兼容字段**：若旧测试引用 log_coverage/code_coverage，优先迁移测试；不保留两套覆盖率逻辑。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_evidence_categories.py tests/unit/test_evaluator_v04.py tests/unit/test_prompt_v04.py -q
uv run pytest tests/integration/test_v04_runtime.py -q
uv run pytest tests/eval/test_v03_cases.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T4 spec：symptom/mechanism、同线程条件放宽、runtime/prompt/cause chain |
| 2026-10-23 | 实现并回填：symptom/mechanism 覆盖、artifacts 注入、同线程规则集中、prompt/JVM 指导/cause chain；定向 19 测试、全量 498 通过 |
| 2026-10-23 | T7 live 调试后强化通用 JVM 指导：首轮分别提出 CPU-bound / blocking 与 heap-growth / capacity 候选；说明请求线程不一定等于热点线程；要求日志上下文通过 `logs.get_thread_context` 绑定。新增 prompt 断言，未加入 case/类名/答案。 |
