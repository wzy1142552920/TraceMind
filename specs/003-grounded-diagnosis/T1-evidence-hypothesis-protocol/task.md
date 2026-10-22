# T1 — 证据账本与假设协议 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T1
- **状态**：planned
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

- [ ] `src/tracemind/diagnosis/evidence.py` / `hypotheses.py` 扩展
- [ ] `src/tracemind/diagnosis/ledger.py`
- [ ] `src/tracemind/diagnosis/workspace.py`
- [ ] `src/tracemind/diagnosis/evaluator.py` 重写
- [ ] `src/tracemind/tools/control.py`
- [ ] `src/tracemind/tools/contracts.py` 绑定字段/错误码
- [ ] `src/tracemind/tools/executor.py` 元数据校验
- [ ] `tests/unit/test_evidence_ledger.py`
- [ ] `tests/unit/test_hypothesis_protocol.py`
- [ ] `tests/unit/test_grounded_evaluator.py`
- [ ] `tests/unit/test_tool_binding.py`
- [ ] 受影响的 registry/executor/runtime 单元测试适配

## 3. Definition of Done

- [ ] AC-T1-01 至 AC-T1-13 全部满足。
- [ ] 未接地假设、伪造 evidence ID、无效/重复 assessment 全部拒绝。
- [ ] 未绑定工具证据不能通过 assessment 满足 requirement。
- [ ] 单假设或存在开放替代时不能 run 级 confirmed。
- [ ] refute 后不能被 supports 覆盖。
- [ ] 控制工具调用进入审计；ledger 只能由 runtime/mapper 写。
- [ ] 全量离线测试、ruff、mypy 通过。
- [ ] 不修改 001/002 specs 或 v2 设计文档。

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
- **refute 终止性**：v0.3 不支持翻案；如产品需要，后续版本再设计。
- **评估语义**：evaluator 只检查结构化覆盖，不判断 rationale 的真实性；T6 用三 case + 负向测试约束模型行为。
- **上下文门槛**：`require_log_thread_context` + `required_log_thread` 只检查是否绑定并评估了主线程的真实上下文，不判断上下文是否足以解释根因。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | 待实现 | PLANNED | — |
