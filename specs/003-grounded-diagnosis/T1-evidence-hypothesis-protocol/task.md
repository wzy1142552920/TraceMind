# T1 — 证据账本与假设协议 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T1
- **状态**：implemented（过渡兼容已由 T4 清理）
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6、T7

## 1. 实施顺序

严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认契约**
   - 阅读 T1 spec 与 [DESIGN §3–§6](../DESIGN.md)。
   - 确认 v0.3 不再保留 v0.2 的 `Evidence.supports` 语义；旧测试由 T4/T6 迁移。
   - 确认控制工具也经过 ToolExecutor，不允许直接写 ledger。

2. **先写模型/账本测试**
   - `tests/unit/test_evidence_ledger.py`：创建、检索、去重、截断。
   - `tests/unit/test_hypothesis_protocol.py`：合法/非法假设、超限、额外字段、basis/assessment 的 source_ref 解析（唯一/多条/零条）、evidence kind 与 requirement 不匹配的拒绝。
   - `tests/unit/test_grounded_evaluator.py`：确认门槛、替代假设、refute、排序。
   - `tests/unit/test_tool_binding.py`：元数据成对、result/audit 绑定。
   - 测试先失败。

3. **实现模型与账本**
   - 扩展 `diagnosis/evidence.py` 或新增 `diagnosis/hypotheses.py`：
     - EvidenceKind / EvidenceProvenance / Evidence 扩展。
     - HypothesisStatus / EvidenceRequirement / Hypothesis / EvidenceAssessment。
   - 新增 `diagnosis/ledger.py`：EvidenceLedger（绑定可写 tool_call_id，复用初始证据不复制）。
   - 不破坏日志解析/索引的现有模型。

4. **实现工作区与控制工具**
   - 新增 `diagnosis/workspace.py`：DiagnosisWorkspace。
   - 新增 `tools/control.py`：
     - `diagnosis.propose_hypothesis`
     - `diagnosis.assess_evidence`
   - Pydantic 输入模型 `extra="forbid"`；runtime 字段不可由 LLM 传入。
   - ID 分配：`hyp_001...`、`hyp_001_req_01...`、`asm_0001...`。
   - 校验 basis、requirements、falsifiers、limits、绑定关系。
   - 新增错误码 `HYPOTHESIS_NOT_GROUNDED`、`INVALID_BINDING`、`INVALID_ASSESSMENT`。

5. **实现工具绑定元数据**
   - `tools/contracts.py` 增加 `EvidenceToolMeta`、`ToolResult.bound_*`、`AuditEvent.bound_*`。
   - `ToolExecutor` 校验元数据；handler 不消费。
   - 现有证据类工具参数继承 meta；无 meta 时保持兼容。

6. **实现确定性 evaluator**
   - 重写 `diagnosis/evaluator.py` 为纯函数，输入 hypotheses/evidence/assessments。
   - 实现 requirement 覆盖、refute、qualifies、run 级确认、排序分、ambiguity。
   - 支持 `require_log_thread_context` + `required_log_thread`：主事件有线程时，qualifying 假设必须有已评估的 `log_thread_context`，且线程号匹配。
   - 不在 evaluator 中发事件/写文件/调 LLM。

7. **接线与回归**
   - 控制工具注册到 registry；workspace 通过 ToolContext 注入。
   - 更新受影响的旧测试（只做 T1 范围内的适配；主循环迁移在 T4）。
   - 运行 T1 验证命令并回填。

## 2. 交付物

- [x] `src/tracemind/diagnosis/evidence.py` / `hypotheses.py` 扩展
- [x] `src/tracemind/diagnosis/ledger.py`
- [x] `src/tracemind/diagnosis/workspace.py`
- [x] `src/tracemind/diagnosis/evaluator.py` 重写
- [x] `src/tracemind/tools/control.py`
- [x] `src/tracemind/tools/contracts.py` 绑定字段/错误码
- [x] `src/tracemind/tools/executor.py` 元数据校验
- [x] `tests/unit/test_evidence_ledger.py`
- [x] `tests/unit/test_hypothesis_protocol.py`
- [x] `tests/unit/test_grounded_evaluator.py`
- [x] `tests/unit/test_tool_binding.py`
- [x] 受影响的 registry/executor/runtime 单元测试适配

## 3. Definition of Done

- [x] AC-T1-01 至 AC-T1-13 全部满足。
- [x] 未接地假设、伪造 evidence ID、越界 ID 被拒绝；非法 assessment 按条拒绝，全批无效才失败；批内重复保留首条；重评修订。
- [x] 未绑定工具证据不能通过 assessment 满足 requirement；已绑定工具证据可复用到其他 requirement。
- [x] 单假设或存在开放替代时不能 run 级 confirmed。
- [x] 同一评估集中 refute 不会被 supports 抵消；重评可修订 verdict。
- [x] 控制工具调用进入审计；ledger 只能由 runtime/mapper 写。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002 specs 或 v2 设计文档。
- [x] 移除 v0.2 `supports` / `missing_evidence` / `source_matches` 过渡语义（T4 迁移主循环时完成）。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_evidence_ledger.py tests/unit/test_hypothesis_protocol.py tests/unit/test_grounded_evaluator.py tests/unit/test_tool_binding.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **控制工具进入 executor**：workspace 通过 `ToolContext` 注入；测试必须确认没有绕过审计的直接调用路径。
- **旧 `supports` 语义**：v0.3 明确移除；T4/T6 迁移相关断言，禁止保留双写。
- **ID 稳定性**：ID 只由 runtime 分配；LLM 提供的 ID 一律忽略/拒绝。
- **refute 与修订**：评估器不会用并存的 supports 抵消 refute；工作区允许重评同一目标并修订 verdict，最新判断生效。
- **评估语义**：evaluator 只检查结构化覆盖，不判断 rationale 的真实性；T6 用三 case + 负向测试约束模型行为。
- **上下文门槛**：`require_log_thread_context` + `required_log_thread` 只检查是否绑定并评估了主线程的真实上下文，不判断上下文是否足以解释根因。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | Claude | T1 定向 pytest | 52 passed | 账本、协议、evaluator、工具绑定 |
| 2026-10-22 | Claude | `uv run pytest -q` | 198 passed, 2 skipped | live 测试保持 opt-in |
| 2026-10-22 | Claude | `uv run ruff check .` | passed | — |
| 2026-10-22 | Claude | `uv run mypy src` | passed | 40 source files |
| 2026-10-22 | Claude | 过渡兼容检查 | 已清理 | T4 删除 legacy evaluator/对应测试，runtime 改用 grounded workspace 与 `evaluate_hypotheses` |
| 2026-10-22 | Claude | 最终全量 `uv run pytest -q` | 385 passed, 6 skipped | live 测试保持 opt-in |
| 2026-10-22 | Claude | 实现后协议回归 | PASS | 证据多绑定、工具证据复用、assessment 修订/部分接受、批内重复拒绝 |
| 2026-10-22 | Claude | `ruff check .` / `mypy src` | PASS | 版本 0.3.0 |
