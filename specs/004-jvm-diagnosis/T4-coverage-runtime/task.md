# T4 — 覆盖模型与运行时 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T3
- **下游**：T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T4 spec、[DESIGN §7](../DESIGN.md)、v0.3 evaluator/runtime/prompt。
   - 确认只放宽同线程规则，不放宽替代假设/refute/工具证据。
   - 确认 artifacts 存在时也不自动生成 JVM 证据。

2. **先写测试**
   - `test_evidence_categories.py`：集合、warning。
   - `test_evaluator_v04.py`：仅 symptom/仅 mechanism、完整确认、同线程开关、旧规则。
   - `test_prompt_v04.py`：artifact 摘要/无 artifacts/JVM 指导/cause chain。
   - `test_v04_runtime.py`：注入 bundle、工具可见性、RunResult.artifacts、无 repair 误报。
   - 测试先失败。

3. **修改评估器**
   - 替换 LOG_KINDS/CODE_KINDS 为 SYMPTOM_KINDS/MECHANISM_KINDS。
   - 调整 coverage/warning；确认门槛增加 symptom/mechanism。
   - 保持 refute、discriminating、tool-derived、替代假设、ranking 语义。
   - 迁移/更新旧测试引用。

4. **修改运行时**
   - 构造函数接受 artifacts；RunResult.artifacts。
   - 同线程规则集中到一个方法；四处调用统一。
   - registry 传入 artifacts；ToolContext 传入。
   - 预算/repair/stop/event 不改变。

5. **修改 prompt**
   - artifact 摘要段（有才显示）。
   - JVM 通用指导（无 case 名称）。
   - 主异常 cause chain；seed cause frame 匹配。
   - 有 artifacts 时说明同线程不再强制；无 artifacts 保持旧措辞。

6. **回归**
   - v0.3 集成/eval 全量；无 artifacts 分支；JVM mock 集成（可用临时 bundle）。
   - ruff/mypy；回填。

## 2. 交付物

- [x] `src/tracemind/diagnosis/evaluator.py`
- [x] `src/tracemind/diagnosis/evidence.py`（RunResult.artifacts）
- [x] `src/tracemind/diagnosis/runtime.py`
- [x] `src/tracemind/diagnosis/prompts.py`
- [x] `tests/unit/test_evidence_categories.py`
- [x] `tests/unit/test_evaluator_v04.py`
- [x] `tests/unit/test_prompt_v04.py`
- [x] `tests/integration/test_v04_runtime.py`
- [x] 旧测试适配

## 3. Definition of Done

- [x] AC-T4-01 至 AC-T4-13 全部满足。
- [x] 有 artifacts 时同线程不阻塞确认；无 artifacts 时旧行为不变。
- [x] 只有 JVM symptom 无 mechanism 时最多 supported。
- [x] prompt 无 case 特判、无完整 dump。
- [x] JVM 工具调用有审计/预算。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_evidence_categories.py tests/unit/test_evaluator_v04.py tests/unit/test_prompt_v04.py -q
uv run pytest tests/integration/test_v04_runtime.py -q
uv run pytest tests/eval/test_v03_cases.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **旧 case 回归**：先跑 v0.3 全量；若 coverage 变化导致 confirmed 下降，修复映射/seed，不放宽门槛。
- **同线程规则集中**：避免四处布尔判断不一致；用单一方法。
- **artifact prompt**：只放 records，不放行内容；警告不重复。
- **运行时不自动收集 JVM 证据**：保持 LLM 自主规划与绑定语义。
- **cause chain**：主栈仍优先；cause 只在主栈无匹配时使用。
- **测试 fixture**：T4 可用内联临时 artifacts；完整 case 留给 T6。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_evidence_categories.py tests/unit/test_evaluator_v04.py tests/unit/test_prompt_v04.py -q` | PASS（16 passed） | 集合/warning、JVM 确认、同线程开关、refute/替代/单假设、prompt 摘要/JVM 指导/cause chain |
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_prompt_v04.py -q` | PASS（6 passed） | T7 live 调试后新增通用首轮候选/跨线程/日志上下文绑定断言 |
| 2026-10-23 | Claude | `uv run pytest tests/integration/test_v04_runtime.py -q` | PASS（3 passed） | artifact 注入、工具可见性、无 missing_thread_context repair、RunResult.artifacts、预算/审计、cause 帧 seed |
| 2026-10-23 | Claude | `uv run pytest tests/eval/test_v03_cases.py -q` | PASS（15 passed） | v0.3 三 case 无回归 |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（498 passed, 6 skipped） | 默认离线；仅 live opt-in 跳过 |
| 2026-10-23 | Claude | `uv run ruff check .` | PASS | 全仓无告警 |
| 2026-10-23 | Claude | `uv run mypy src` | PASS（59 source files） | 无类型错误 |

### 6.1 实现说明

- `SYMPTOM_KINDS`/`MECHANISM_KINDS` 覆盖全部 15 个 evidence kind 且互斥；确认新增 symptom 与 mechanism 覆盖，`missing_symptom_evidence`/`missing_mechanism_evidence` 只在对应覆盖缺失时出现。
- 同线程规则集中为 runtime 内部的 `requires_same_thread_context()`：仅当主异常有线程且未提供 artifacts 时为真；`required_thread()`、`thread_context_assessed()`、`stop_repair_reason()`、`complete_if_confirmed()` 全部复用该规则。v0.3 的 refute、替代假设、单假设、工具证据规则未改。
- `DiagnosisRuntime(artifacts=...)` 把 bundle 传给既有 registry/executor/context，并把 `ArtifactRecord` 原样放进 `RunResult.artifacts`；不自动把快照内容变成证据，JVM 证据仍由绑定工具调用产生。
- 有 artifacts 时 runtime 追加两条 limitation（用户提供的时间点快照、同线程上下文不再强制）；system prompt 替换强制同线程措辞并追加通用 JVM 分析指导，无 case 名称/期望答案。
- 用户 prompt 仅展示 artifact 元数据（≤8 条、每条 ≤3 个 warning 且单条截断到 160 字符），不包含文件全文或绝对路径；主异常增加最多 5 层 cause chain、每层最多 3 帧的展示。
- `_find_seed_matches` 先匹配主栈（≤50 帧），未命中时按 cause 顺序匹配，总帧数封顶 100；cause 帧仍走同一符号解析逻辑。
- 集成测试确认 JVM 工具只在提出两个假设后可见、评估前只暴露 assessment 工具；三次证据工具调用均进入 `tool_calls`/预算，且确认路径无 `missing_thread_context` repair。

### 6.2 T7 live 调试后的提示强化

首次 live CPU case 出现 `insufficient_data`：模型首轮把“远程阻塞”与“JVM 压力”合并成一个候选，遗漏 CPU-bound 机制；后续又把请求线程 `http-nio-8080-exec-7` 当作热点线程，因而被快照 refute。OOM case 还出现直接评估 seeded 日志上下文、未通过工具绑定的情况。

修复只改通用 prompt，不加 case/类名/答案：

- 有 thread CPU/dump 时，首轮分别提出 CPU-bound 应用代码候选与 blocking/lock/GC 候选；有 GC/heap 时分别提出 live heap 增长候选与容量/单次大对象候选；禁止用 “or” 合并机制。
- 请求线程不一定是 CPU 热点线程；不同 RUNNABLE 业务线程高 CPU 也能解释请求被延迟。
- 依赖日志上下文的 requirement 必须通过 `logs.get_thread_context` 获取并绑定，seeded context 不能直接评估。

新增断言位于 `test_jvm_guidance_requires_artifact_aware_candidates`；修正后 live 两 case 均 confirmed（详见 [T7 task §6](../T7-live-docs-release/task.md)）。
