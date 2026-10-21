# T4 — Live-Plan Resilience Spec

- **任务 ID**：T4
- **状态**：draft
- **依赖**：T2、T3
- **下游**：T5、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.1 每轮重建紧凑 prompt，但只放入 evidence 的 ID/kind/source_ref，不把上一轮工具结果或错误反馈给模型；无 tool call、未知工具、非法参数、重复调用或无新证据时会直接 `no_progress`。真实 DeepSeek 输出有非确定性，需要有限次“计划修复”才能稳定完成最小循环，同时不能牺牲确定性边界。

**用户故事**：作为运行时，当模型只返回文本、调用未知工具、参数错误、重复调用或返回被截断时，我能在预算内用上一轮观察提示它修正；如果仍不能产生证据，就明确停止，不让模型直接确认根因。

## 2. In scope

- 每次 prompt 增加“上一轮观察”块：
  - 上一轮 LLM 文本（截断）。
  - 上一轮工具调用/参数/结果/错误/新证据数。
  - 证据摘要、源码候选、缺失证据、预算/repair 剩余。
- 有界 repair：默认最多 2 次；计入 iteration/llm_calls；不重置。
- 触发 repair：
  - 无 tool call 且未 confirmed。
  - `finish_reason=length`。
  - unknown tool / invalid args / duplicate call / 无新证据。
- 先评估已有证据，再决定停止；只有 Evaluator 可以 `confirmed`。
- 已知工具调用失败但其他证据满足确认门槛：允许完成，记录失败调用。
- 保持 Mock happy path 不变。

## 3. Out of scope

- 完整 conversation replay / 扩展 Message 支持 assistant tool_calls。
- 自动执行“默认工具计划”或硬编码工具序列。
- 新工具/fixture、模型自评分、绕过 Evaluator。
- 多 Agent/reflection 框架。
- 自定义上下文摘要模型（只做确定性截断/摘要）。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T4-01 | prompt 包含上一轮工具结果/错误/新证据/剩余预算 | must |
| FR-T4-02 | 无 tool call 时可 repair，最多 `repair_attempts` | must |
| FR-T4-03 | unknown/invalid/duplicate/no-evidence 可 repair | must |
| FR-T4-04 | `finish_reason=length` 不执行半截工具；repair 或失败 | must |
| FR-T4-05 | repair 受 iterations/llm/tool 预算约束 | must |
| FR-T4-06 | 只有 Evaluator 可 confirmed；模型文本不能确认 | must |
| FR-T4-07 | Mock happy path 行为和证据门槛不变 | must |

## 5. 接口/数据契约

### Repair 状态

- `repair_attempts_used: int`（每 run 0..settings.repair_attempts）。
- 触发 repair 时：
  - `usage.iterations += 1`（下一轮）
  - `usage.llm_calls += 1`
  - 记录 `agent.repair` / `llm.called` 事件，包含 `reason`。
- 耗尽后：
  - 无证据/无进展 → `INSUFFICIENT_DATA` / `no_progress`
  - `length` 仍无法修复 → `FAILED` / `error`
  - 预算耗尽 → `STOPPED_BUDGET` / `budget_exhausted`

### 上一轮观察块（user prompt）

```text
Previous observation:
- Assistant text: <truncated 500 chars>
- Tool calls: name(args) -> ok/error / evidence count
- New evidence: N
- Evidence summary: ids/kinds/source refs
- Current hypothesis status: supported/confirmed/missing...
- Repair remaining: N
```

- 源码片段/日志摘要每项上限约 2,000 chars；总上下文仍受 `max_context_chars` 约束。
- 不发送完整工具结果/完整源码；保留 source_ref 和短摘要。

### 评估顺序

1. 收到响应，记录 LLM call。
2. 若有可执行 tool calls，执行并记录结果/证据。
3. 调用 `evaluate()` 更新 hypothesis。
4. 只有 `status == confirmed` 才 `REPORTING`/`COMPLETED`。
5. 未 confirmed 时按 repair/stop 规则处理。

模型文本/自述 confidence 不进入 hypothesis 状态。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T4-01 | 下一轮 prompt 含上一轮工具结果/错误/新证据 | `test_prompt_contains_previous_observation` |
| AC-T4-02 | text-only 响应 repair 后恢复 | `test_text_only_repair` |
| AC-T4-03 | unknown/invalid/duplicate/no-evidence 可 repair | fake sequence tests |
| AC-T4-04 | `length` 半截工具不执行；repair 或明确失败 | `test_length_finish_reason` |
| AC-T4-05 | repair 最多 2 轮且受预算限制 | `test_repair_budget_exhaustion` |
| AC-T4-06 | 模型文本不能直接 confirmed | `test_model_prose_cannot_confirm` |
| AC-T4-07 | Mock happy path 不变 | `test_happy_path_confirms_hypothesis` |

## 7. 测试计划

### 单元/集成

- 新增 `tests/unit/test_live_resilience.py`：
  - 第一响应 text-only → 第二响应有效工具 → confirmed。
  - 第一响应 unknown tool / invalid args / duplicate → 第二响应有效工具 → confirmed。
  - 第一响应 `finish_reason=length` 带半截 tool call → 不执行 → repair → success/fail。
  - repair 耗尽 → INSUFFICIENT_DATA/FAILED，预算正确。
  - 捕获第二次 prompt，断言上一轮 observation 存在。
  - 模型文本声明“根因已确认”但证据不足 → 不 confirmed。
- 更新 `tests/integration/test_minimal_loop_runtime.py` 的 happy path/空计划预期（如 repair 改变 llm_calls）。
- MockProvider 脚本补充 live-like 序列（测试 fixture）。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| repair 循环/成本 | 模型持续空计划 | 最多 2 次；受迭代/token 预算 |
| Prompt 膨胀 | 工具结果过多 | 摘要/截断/字符上限 |
| 错误被隐藏 | repair 掩盖真实 provider error | 只有特定错误 repair；auth/timeout 失败 |
| 模型自证 | 文本声称 confirmed | Evaluator 唯一确认来源 |
| Mock 回归 | 修复改变现有空计划行为 | 明确空计划在 repair 耗尽后仍 no_progress |
| 误确认 | source_code 不相关 | v0.2 不扩展 Evaluator；报告声明限制 |

**开放问题**

- repair 次数是否按错误类型区分？v0.2 统一 2 次。
- 是否对“无新证据”也 repair？是，但最多 2 次。
- 是否显示 assistant text 到报告？不；只用于下一轮上下文。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_live_resilience.py tests/integration/test_minimal_loop_runtime.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T4 spec；定义上一轮观察、有限 repair、length/错误处理和 Evaluator 边界 |
