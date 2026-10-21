# T4 — Live-Plan Resilience Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T2、T3
- **下游**：T5、T6

## 1. 实施顺序

> T4 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T4 spec、T3 usage 契约、现有 Runtime 的主循环/预算/停止。
   - 确认 repair 上限 2、Evaluator-only 确认。

2. **先写 fake live-like 测试**
   - `tests/unit/test_live_resilience.py`：text-only、unknown tool、invalid args、duplicate、length、repair 耗尽、模型自证。
   - 捕获第二次 prompt，断言 observation 块。
   - 测试先失败。

3. **实现观察块**
   - 在 runtime 保存上一轮 assistant 文本、tool calls/结果/错误、新证据数。
   - `build_messages()` 加入截断的 observation 和预算/repair 信息。
   - 源码/日志摘要上限。

4. **实现 repair 控制**
   - 增加 repair 计数器；由 settings.repair_attempts 限制。
   - 无 tool call/unknown/invalid/duplicate/no-evidence/length 触发 repair。
   - 先评估证据；只有 confirmed 才完成。
   - repair 耗尽按 spec 停止；预算优先。
   - `length` 不执行半截 calls。

5. **保持兼容**
   - Mock happy path/空计划结果预期按 spec 更新。
   - 不改变 Evaluator 确认门槛、ToolExecutor、报告校验。

6. **验证并回填**
   - 运行 T4 验证命令；回填 task §6 和 spec 变更记录。

## 2. 交付物

- [x] `src/tracemind/diagnosis/runtime.py` observation/repair
- [x] `src/tracemind/diagnosis/budget.py`/config repair 限制
- [x] `src/tracemind/diagnosis/state.py` 事件字段（如需要）
- [x] `tests/unit/test_live_resilience.py`
- [x] 更新 Mock 脚本/运行集成测试

## 3. Definition of Done

- [x] AC-T4-01 至 AC-T4-07 全部满足。
- [x] 上一轮工具结果/错误确实进入下一轮 prompt。
- [x] text-only/unknown/invalid/duplicate/length 在 2 次 repair 内恢复或明确停止。
- [x] 只有 Evaluator 能 confirmed；模型文本不能绕过。
- [x] Mock happy path 不变；空计划仍最终 no_progress。
- [x] 预算/停止原因/事件正确。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_live_resilience.py tests/integration/test_minimal_loop_runtime.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **Repair 成本**：最多 2 次并受迭代/token 预算；测试断言。
- **Prompt 膨胀**：截断/摘要/上限；不要把完整工具输出塞入。
- **行为回归**：空计划原来立即 no_progress；现在可 repair，更新 E2E/集成预期。
- **确认边界**：模型文本“已确认”只作为文本，不改变 hypothesis。
- **length 半截工具**：不执行 tool calls；repair 或失败。
- **Mock 确定性**：Mock 脚本需补 live-like 序列，但默认 happy path 不变。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | T4 专项 pytest | 13 passed | resilience/runtime/seed |
| 2026-10-21 | Claude | `uv run pytest -q` | 145 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 36 source files | — |
| 2026-10-21 | Claude | 上一轮观察 | assistant/tool/error/new evidence 进入下一 prompt | 2nd/3rd prompt |
| 2026-10-21 | Claude | repair/length | text-only/unknown/invalid/no-evidence 恢复；length 不执行半截工具 | bounded 2 |
| 2026-10-21 | Claude | 确认边界 | 模型文本未直接 confirmed | Evaluator-only |
