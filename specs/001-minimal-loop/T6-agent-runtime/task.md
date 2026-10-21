# T6 — Agent Runtime、Evidence、Evaluator Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T6
- **状态**：draft
- **依赖**：T2、T3、T4、T5
- **下游**：T7

## 1. 实施顺序

> 当前阶段只生成文档；以下步骤供后续实现会话执行。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T6 `spec.md`，确认状态机、种子规则、证据转换、确认门槛、停止条件。
   - 确认 T2/T3/T4/T5 的模型与接口可直接组合，无需修改契约。

2. **定义模型**
   - `src/tracemind/diagnosis/state.py`：RuntimeState、StopReason、RuntimeEvent。
   - `src/tracemind/diagnosis/budget.py`：Budget、BudgetUsage。
   - `src/tracemind/diagnosis/evidence.py`：Evidence、Hypothesis、ToolCallRecord、RunResult。
   - 复用 T3 的 SourceMatch、T4 的 ToolResult、T5 的 LLMResponse。

3. **先写状态/预算测试**
   - `tests/unit/test_runtime_state.py`：合法/非法转换、终态、停止原因。
   - `tests/unit/test_runtime_budget.py`：max_iterations、max_tool_calls、重复调用。
   - 测试先失败。

4. **写种子/评估测试**
   - `tests/unit/test_runtime_seed.py`：primary event → in-project frame → hyp_001 + 种子证据；无 frame → insufficient_data。
   - `tests/unit/test_evaluator.py`：证据覆盖/确认门槛/缺失证据。

5. **实现种子与证据**
   - 从 `ParsedLog.primary_event_id` 取事件。
   - 遍历 frames，调用 `JavaIndex.resolve_frame`，选第一个有结果的 in-project frame。
   - 生成 hyp_001、ev_stack、ev_log；`source_code` 留待工具。
   - 记录事件。

6. **实现规划/执行循环**
   - 构造 system/user 消息 + ToolDefinition 列表。
   - 调 `provider.complete`；记录 llm_calls。
   - 对每个 tool call：`ToolExecutor.execute`；记录 ToolCallRecord；成功结果转 Evidence。
   - 每轮重建上下文；不重放完整 conversation。

7. **实现 Evaluator/停止**
   - 检查 `stack_frame + log_event + source_code`。
   - 更新 hypothesis.status/missing_evidence。
   - 根据 spec §5 停止条件设置终态/stop_reason。
   - 无 tool call 且未 confirmed → no_progress。

8. **集成测试**
   - 用 T2 fixture + T3 fixture index + T4 executor + T5 Mock 脚本跑通 happy path。
   - 测无源码/空计划/预算/重复/provider 错误。

9. **验证并回填**
   - 运行 T6 spec 的验证命令，回填 §6。

## 2. 交付物

- [ ] `src/tracemind/diagnosis/__init__.py`
- [ ] `src/tracemind/diagnosis/state.py`
- [ ] `src/tracemind/diagnosis/budget.py`
- [ ] `src/tracemind/diagnosis/evidence.py`
- [ ] `src/tracemind/diagnosis/evaluator.py`
- [ ] `src/tracemind/diagnosis/runtime.py`
- [ ] `tests/unit/test_runtime_state.py`
- [ ] `tests/unit/test_runtime_budget.py`
- [ ] `tests/unit/test_runtime_seed.py`
- [ ] `tests/unit/test_evaluator.py`
- [ ] `tests/integration/test_minimal_loop_runtime.py`

## 3. Definition of Done

- [ ] T6 spec 的 AC-T6-01 至 AC-T6-11 全部满足。
- [ ] Happy path 得到 confirmed 假设和三类证据。
- [ ] 无源码/空计划/预算/重复/provider 错误路径都有明确终态与 stop_reason。
- [ ] LLM 不能直接确认假设；确认由 Evaluator 决定。
- [ ] 所有工具调用经过 T4 ToolExecutor。
- [ ] `RunResult` 可直接被 T7 生成报告。
- [ ] 没有网络依赖；Mock 脚本确定性。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_runtime_state.py tests/unit/test_runtime_budget.py \
  tests/unit/test_evaluator.py tests/unit/test_runtime_seed.py \
  tests/integration/test_minimal_loop_runtime.py -q
```

## 5. 开放问题 / 风险

- **证据来源**：`source_code` 必须来自工具；种子阶段只解析 SourceMatch，不直接生成证据。这样 LLM 的工具规划有实际作用。
- **确认门槛**：v0.1 只要求三类证据；如果真实 Provider 不调用源码工具，报告只能 probable/insufficient_data，这是可接受的诚实结果。
- **空计划**：Mock 脚本第二个响应无 tool calls；运行时应 no_progress，不要无限循环。
- **重复调用**：T4 返回 DUPLICATE_CALL；运行时不应把重复结果重复计入证据。
- **Provider 错误**：v0.1 不重试；捕获后 FAILED/error，保留已收集证据。
- **事件落盘**：T6 只返回 events；T7 写 events.jsonl，避免 runtime 依赖文件系统。
- **状态机实现**：不要用复杂框架；一个枚举 + 显式转换校验即可。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | — | 未执行 | 当前阶段只生成文档 |
