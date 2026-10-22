# T4 — 鉴别诊断运行时 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T1、T2、T3
- **下游**：T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T4 spec、[DESIGN §8](../DESIGN.md)、T1 workspace/evaluator、T2/T3 工具输出。
   - 确认 runtime 不内置 case 分支/期望答案。
   - 确认 T4 只返回 RunResult，不生成 remediation/report 0.3。
   - 确认同线程上下文证据的创建、绑定与确认门槛。

2. **先写集成测试**
   - 新增 `tests/integration/test_v03_runtime.py`，覆盖：
     - 多假设 happy path。
     - 开放替代不确认。
     - 单假设不确认。
     - ungrounded/invalid assessment/no tools/no evidence repair。
     - 缺同线程上下文 repair；有上下文后才可 confirmed。
     - 跨线程事件被排除；无线程号不影响确认。
     - 模型文本不能确认。
     - length/预算停止。
   - 更新现有 runtime 测试的预期（控制工具、证据模型、状态）。
   - 测试先失败。

3. **初始证据与工作区接线**
   - INGESTING 创建 log_event/log_thread_context/stack_frame/source_code。
   - 同线程上下文：主事件前后各 3 条同线程事件、按文件顺序、`logger_class` 派生；无线程号则跳过。
   - `logs.get_thread_context`：event_id 可选（默认 primary）、before/after 0..20、只返回锚点同线程事件。
   - 创建 EvidenceLedger、DiagnosisWorkspace、control tools、evidence mapper。
   - ToolContext 注入 workspace 和 verification backend。
   - RunResult 扩展 hypotheses/assessments/verification_environment。

4. **重写 prompt**
   - System prompt：角色/只读/grounding/确认规则/不可信数据/日志-代码协同。
   - User prompt：incident、同线程上下文、ledger、hypotheses、assessments、工具、预算、上一轮观察。
   - 明确指引：先还原同线程业务步骤，再用 logger_class/栈帧定位代码，再查调用链/SQL。
   - 证据/源码/日志摘要上限；不发送完整文件。
   - 不包含 expected 数据/硬编码 case 信息。

5. **实现主循环**
   - 按顺序处理控制/证据工具；接入 `logs.get_thread_context`。
   - 提取 meta；executor 校验；mapper 创建证据；workspace 创建假设/assessment。
   - 每轮 evaluator 并传 `require_log_thread_context=primary_event.thread is not None`、`required_log_thread=primary_event.thread`。
   - 事件；run 级 confirmation（含同线程上下文门槛）。
   - repair 逻辑（含 `missing_thread_context`）/预算/停止。
   - 不执行半截 length tool calls。

6. **迁移旧行为**
   - 现有 `basic_plan.json`/MockProvider 脚本加入控制工具序列。
   - 更新 runtime/seed/state/budget/observability/E2E 测试。
   - 保持默认离线、确定性。

7. **验证并回填**
   - 运行 T4 验证命令；回填 task/spec 变更记录。

## 2. 交付物

- [x] `src/tracemind/diagnosis/runtime.py` 重写/扩展
- [x] 证据 mapper（`src/tracemind/diagnosis/evidence_mapping.py`）
- [x] `logs.get_thread_context` 工具与同线程上下文初始证据
- [x] prompt 构造（`src/tracemind/diagnosis/prompts.py`）
- [x] `RunResult`/`Budget`/`BudgetUsage` 扩展
- [x] 控制工具注册与 workspace 注入
- [x] `tests/integration/test_v03_runtime.py`
- [x] `tests/unit/test_tool_executor.py` 扩展（同线程工具）
- [x] 更新的 runtime/seed/state/budget/observability/E2E 测试
- [x] 更新的 Mock 脚本

## 3. Definition of Done

- [x] AC-T4-01 至 AC-T4-17 全部满足。
- [x] LLM 自主提出 ≥2 grounded 假设；runtime 不预生成结论。
- [x] 工具绑定/证据映射/evaluator 闭环工作。
- [x] 同线程上下文只含本线程事件；有线程号时必须评估后才可 confirmed。
- [x] 开放替代假设时不 confirmed；模型文本不能确认。
- [x] repair、预算、停止、事件均有测试。
- [x] prompt 不含 case 期望答案；恶意内容不改变策略。
- [x] 默认离线测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/integration/test_v03_runtime.py tests/integration/test_minimal_loop_runtime.py tests/unit/test_tool_executor.py tests/unit/test_runtime_budget.py tests/unit/test_runtime_observability.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **Prompt 复杂度**：多假设/证据/要求会膨胀；用条数/字符上限和摘要。
- **模型行为不稳定**：repair 有界；live 结果在 T7 如实记录。
- **Mock 过拟合**：runtime 无 case 分支；Mock 只用于协议测试。
- **控制工具顺序**：同一轮绑定到未创建假设会报错；依赖 repair，测试覆盖。
- **旧测试迁移**：`supports`/单假设断言需删除；不要保留双语义。
- **确认语义**：替代假设必须 contradicted；不要为了 demo 放宽。
- **同线程门槛**：只检查绑定/评估，不判断上下文是否语义充分；T6 用 case 和负向测试约束。
- **跨线程噪声**：上下文提取和 `logs.get_thread_context` 必须共用同一过滤/source_ref 规则，避免重复证据或漏证据。
- **证据复用与修订**：同一事实可绑定多个 requirement；重评同一目标必须修订而不是重复；修订要计入进展，否则 live 运行会误停。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | Claude | T4 定向 pytest | 40 passed | v03 runtime、minimal loop、工具、预算、可观测性 |
| 2026-10-22 | Claude | `uv run pytest -q` | 294 passed, 2 skipped | live 测试保持 opt-in |
| 2026-10-22 | Claude | `uv run ruff check .` | passed | 修复 import 排序与行宽 |
| 2026-10-22 | Claude | `uv run mypy src` | passed | 47 source files；修复 thread_context logger 可选类型 |
| 2026-10-22 | Claude | 最终全量 `uv run pytest -q` | 385 passed, 6 skipped | live opt-in |
| 2026-10-22 | Claude | live 调优回归 | PASS | 多绑定/复用、assessment 修订与部分接受、源码/SQL/DB 正文进入 prompt |

实现备注：

- 修复 `DiagnosisWorkspace` 对空 ledger 的假值判断，确保 runtime 与 workspace 共享同一账本。
- 新增 `tests/integration/test_v03_runtime.py` 11 个场景，覆盖单假设、开放替代、缺/错线程上下文、未接地、无效 assessment、无新证据、prompt 约束、文本确认、工具预算。
- `test_live_resilience.py` 改为 grounded 协议下的有界 repair 测试；`test_evaluator.py` 随 legacy evaluator 删除。
- T4 报告仍为 schema 0.2；DB 引用校验与 remediation 留给 T5。
- T7 live 调优补强运行时协议：单机制假设提示、工具证据复用/多绑定、assessment 修订与部分接受、修订事件与进展计数；未加入 case 特判。
