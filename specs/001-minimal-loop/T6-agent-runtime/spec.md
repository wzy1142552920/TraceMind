# T6 — Agent Runtime、Evidence、Evaluator Spec

- **任务 ID**：T6
- **状态**：draft
- **依赖**：T2、T3、T4、T5
- **下游**：T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

T2 提供日志/堆栈，T3 提供源码定位，T4 提供受控工具，T5 提供 LLM Provider。T6 把它们串成一个确定性的最小诊断循环：种子假设 → LLM 规划工具 → 执行工具 → 记录证据 → 评估假设 → 停止。LLM 只负责规划，不负责确认。

**用户故事**：作为用户，我传入日志、仓库、服务和 Provider，运行时能返回一个 `RunResult`：包含假设、证据、工具调用、停止原因和预算使用量；T7 可以据此生成报告。

## 2. In scope

- 显式状态机：`INGESTING → SEEDING → PLANNING → EXECUTING → EVALUATING → REPORTING`；终态 `COMPLETED`/`INSUFFICIENT_DATA`/`STOPPED_BUDGET`/`FAILED`。
- 从 T2 primary event 的最上层 in-project frame 生成种子假设。
- 生成 `stack_frame` 和 `log_event` 种子证据；`source_code` 证据必须来自工具结果。
- 构建紧凑上下文，调用 T5 Provider 规划工具。
- 通过 T4 ToolExecutor 执行工具；工具结果转证据。
- 最小 Evaluator/确认门槛。
- 预算、去重、停止原因、事件收集。
- 返回 `RunResult`；不负责写报告/CLI（T7）。

## 3. Out of scope

- Reflection、审批、远程工具、完整知识 catalog、多 Agent。
- SQLite/持久化；运行时只返回内存对象，T7 负责落盘。
- LLM 生成最终报告文本；v0.1 报告用确定性模板（T7）。
- 复杂重试/退避；Provider 错误直接终止或记录。
- 多轮完整 conversation 回放；v0.1 每轮重建紧凑上下文。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T6-01 | 运行时按状态表推进，每次转换发事件 | must |
| FR-T6-02 | 从 primary event 的最上层 in-project frame 生成 `hyp_001` | must |
| FR-T6-03 | 生成 `stack_frame`、`log_event` 种子证据；`source_code` 只来自工具 | must |
| FR-T6-04 | 每轮构建紧凑上下文并调用 Provider；记录 llm_calls | must |
| FR-T6-05 | 只通过 ToolExecutor 执行工具；记录 tool_calls | must |
| FR-T6-06 | 工具结果转换为 Evidence，并关联假设 | must |
| FR-T6-07 | Evaluator 按证据覆盖更新假设状态 | must |
| FR-T6-08 | 确认门槛：`stack_frame + log_event + source_code` 且无矛盾 | must |
| FR-T6-09 | 预算：max_iterations、max_tool_calls、max_same_tool_same_args、per_tool_timeout | must |
| FR-T6-10 | 停止原因：evidence_sufficient/no_progress/budget_exhausted/error | must |
| FR-T6-11 | 返回 RunResult（hypotheses/evidence/tool_calls/stop/budget_usage/events） | must |
| FR-T6-12 | 无 in-project frame 时返回 INSUFFICIENT_DATA，不伪造源码 | must |

## 5. 接口/数据契约

### 运行时状态

```text
INGESTING -> SEEDING -> PLANNING -> EXECUTING -> EVALUATING -> REPORTING
                                  ^                |
                                  |                +--> PLANNING（继续）
                                  |                +--> REPORTING（证据足够）
                                  |                +--> STOPPED_BUDGET
                                  |                +--> INSUFFICIENT_DATA
                                  +--（下一轮）----+
```

终态：`COMPLETED`、`INSUFFICIENT_DATA`、`STOPPED_BUDGET`、`FAILED`。

`REPORTING` 在 v0.1 中表示运行时已完成证据收集、准备交棒；实际报告生成由 T7 负责。T6 返回 `RunResult`，不写报告文件。

### `Budget`

| 字段 | 默认值 | 说明 |
|---|---|---|
| `max_iterations` | 6 | 规划/执行轮数上限 |
| `max_tool_calls` | 8 | 工具调用总数上限 |
| `max_same_tool_same_args` | 1 | 同工具同参数上限（T4 执行） |
| `per_tool_timeout_seconds` | 5 | 单工具超时（v0.1 记录字段，同步执行） |
| `max_output_bytes` | 32768 | 工具输出上限 |

### `Evidence`

| 字段 | 类型 | 说明 |
|---|---|---|
| `evidence_id` | `str` | `ev_...` |
| `kind` | `str` | `stack_frame` / `log_event` / `source_code` |
| `claim` | `str` | 证据支持的事实陈述 |
| `source_ref` | `str` | `log://...` / `repo://...` |
| `supports` | `list[str]` | 假设 ID |
| `strength` | `str` | `strong` / `medium` / `weak` |
| `tool_call_id` | `str \| None` | 来自工具时 |
| `created_at` | `str` | ISO 时间 |

### `Hypothesis`

| 字段 | 类型 | 说明 |
|---|---|---|
| `hypothesis_id` | `str` | `hyp_...` |
| `statement` | `str` | 假设陈述 |
| `status` | `str` | candidate/supported/confirmed/insufficient_data |
| `evidence_ids` | `list[str]` | 关联证据 |
| `missing_evidence` | `list[str]` | 缺失的 evidence kind |
| `source_matches` | `list[SourceMatch]` | 种子阶段解析到的候选源码（用于上下文） |

### `ToolCallRecord`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_call_id` | `str` | LLM/运行时 ID |
| `tool_name` | `str` | 工具名 |
| `arguments` | `dict` | 参数 |
| `ok` | `bool` | 是否成功 |
| `error_code` | `str \| None` | 错误码 |
| `duration_ms` | `int` | 耗时 |
| `evidence_ids` | `list[str]` | 产生的证据 |

### `RunResult`

| 字段 | 类型 | 说明 |
|---|---|---|
| `incident_id` | `str` | `inc_...` |
| `run_id` | `str` | `run_...` |
| `service` | `str` | 服务名 |
| `state` | `str` | 终态 |
| `stop_reason` | `str` | 停止原因 |
| `hypotheses` | `list[Hypothesis]` | 假设 |
| `evidence` | `list[Evidence]` | 证据 |
| `tool_calls` | `list[ToolCallRecord]` | 工具调用 |
| `budget_usage` | `dict` | iterations/llm_calls/tool_calls |
| `limitations` | `list[str]` | 已知限制 |
| `events` | `list[RuntimeEvent]` | 运行事件 |

### 接口

```python
class DiagnosisRuntime:
    def run(
        self,
        parsed_log: ParsedLog,
        java_index: JavaIndex,
        service: str,
        provider: LLMProvider,
        budget: Budget | None = None,
    ) -> RunResult: ...
```

### 种子规则

1. 取 `parsed_log.primary_event_id` 对应事件。
2. 遍历其 `stack_frames`，依次用 `java_index.resolve_frame`；选第一个有结果的 in-project frame。
3. 生成 `hyp_001`：
   - `statement`: `Exception originates at <fqn>.<method> (<file>:<line>)`
   - `missing_evidence`: `["source_code"]`
   - `source_matches`: 解析结果列表。
4. 生成 `ev_stack`（stack_frame，source_ref 指向日志行）和 `ev_log`（log_event，source_ref 指向 primary event）。
5. 若没有 in-project frame：`hyp_001` 状态 `insufficient_data`，停止/继续规划取决于是否有其他线索；v0.1 直接 `INSUFFICIENT_DATA`。

### 规划上下文

每轮构造新的紧凑上下文（不重放完整 conversation）：

- system：角色、只读、工具使用规则、不得确认根因、预算。
- user：incident 摘要、primary event、stack frames、当前假设/证据摘要、源码候选、剩余预算。
- tools：T4 注册的 `ToolDefinition` 列表。

### 证据转换

| 工具 | 证据 kind | source_ref |
|---|---|---|
| `code.find_symbol` | `source_code` | `repo://<path>#Lx-Ly` |
| `code.get_source_range` | `source_code` | `repo://<path>#Lx-Ly` |
| `logs.search` | `log_event` | `log://<event_id>` 或 `log://<file>#Lx-Ly` |
| `logs.get_event_context` | `log_event` | 对应日志行范围 |

- 同一工具/相同参数重复结果不重复计证据（T4 去重）。
- 工具错误不生成证据，只记录 `ToolCallRecord` 和事件。
- `source_code` 证据必须来自工具，不由种子阶段直接创建。

### Evaluator / 确认门槛

- `source_code + log_event + stack_frame` 全部存在，且都指向 `hyp_001` → `confirmed`。
- 有部分证据但缺 `source_code` → `supported`，`missing_evidence=["source_code"]`。
- 无证据 → `candidate`。
- 无 in-project source → `insufficient_data`。
- 不使用 LLM 自报 confidence；v0.1 不做数值评分，只做证据覆盖状态。

### 停止条件

| 条件 | 终态 | stop_reason |
|---|---|---|
| 假设 confirmed | COMPLETED | evidence_sufficient |
| 本轮无 tool call 且未 confirmed | INSUFFICIENT_DATA | no_progress |
| 迭代/工具调用超预算 | STOPPED_BUDGET | budget_exhausted |
| Provider 不可恢复错误 | FAILED | error |
| 无 in-project frame | INSUFFICIENT_DATA | no_progress |

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T6-01 | 使用 T5 Mock 脚本 + T2/T3 fixture，运行时得到 `confirmed` 假设 | 集成测试 |
| AC-T6-02 | `RunResult` 含 `stack_frame`、`log_event`、`source_code` 三类证据 | 集成测试 |
| AC-T6-03 | 证据 `source_ref` 指向 fixture 的 `OrderService.java` 行范围 | 集成测试 |
| AC-T6-04 | 停止原因为 `evidence_sufficient`；预算使用量正确 | 集成测试 |
| AC-T6-05 | 无 in-project frame 时返回 `INSUFFICIENT_DATA`，不生成 `source_code` 证据 | 单元测试 |
| AC-T6-06 | Mock 返回空 tool calls 且未 confirmed → `no_progress` | 单元测试 |
| AC-T6-07 | `max_iterations=1` 且 Mock 持续返回工具调用 → `STOPPED_BUDGET` | 单元测试 |
| AC-T6-08 | 同一工具+相同参数重复调用只执行一次，不重复生成证据 | 单元测试 |
| AC-T6-09 | Provider 抛错 → `FAILED`/`error`，不崩溃 | 单元测试 |
| AC-T6-10 | 事件包含状态转换、LLM 调用、工具调用、证据创建、停止 | 单元测试 |
| AC-T6-11 | LLM 不能直接把假设设为 confirmed；确认只由 Evaluator 决定 | 代码审查/测试 |

## 7. 测试计划

### 单元

- `tests/unit/test_runtime_state.py`：状态转换、终态、停止原因。
- `tests/unit/test_runtime_budget.py`：迭代/工具调用预算、重复调用。
- `tests/unit/test_evaluator.py`：证据覆盖、确认门槛、缺失证据。
- `tests/unit/test_runtime_seed.py`：种子假设、无 in-project frame。

### 集成

- `tests/integration/test_minimal_loop_runtime.py`：
  - T2 ParsedLog + T3 JavaIndex + T4 ToolExecutor + T5 MockProvider。
  - 断言 confirmed、证据种类/引用、stop_reason、budget_usage。
  - 用固定 Mock 脚本，不调用网络。

### E2E

- 由 T7 使用 runtime 生成报告；T6 不直接跑 CLI。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| LLM 规划不稳定 | 真实 Provider 可能不调用关键工具 | v0.1 用 Mock 做验收；真实 Provider 作为可选 demo；报告 allowed to be probable |
| 确认门槛过松/过紧 | 只有三类证据，可能误判 | 明确 evidence kind/来源；后续 catalog/评分增强 |
| 上下文重建 | 不重放完整 conversation，模型可能缺少细节 | 每轮摘要包含关键证据/源码候选；测试 Mock 确定性 |
| 事件收集 | 内存事件与 T7 落盘耦合 | RuntimeEvent 列表返回；T7 写 JSONL |
| Provider 错误 | 可能终止整个运行 | 捕获并转 FAILED/error；记录事件 |
| 证据重复 | 同工具重复结果 | T4 去重 + Evaluator 按 evidence kind 检查 |

**开放问题**

- 是否需要在种子阶段直接生成 `source_code` 证据？v0.1 不生成，保留工具调用价值。
- 是否允许 LLM 提出新假设？v0.1 不做；只评估种子假设。
- 是否需要在无 tool call 时自动补一次源码工具？v0.1 不自动，保持确定性；Mock 脚本负责。
- 多轮上下文中是否发送工具结果历史？v0.1 只发摘要，不重放完整消息。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_runtime_state.py tests/unit/test_runtime_budget.py \
  tests/unit/test_evaluator.py tests/unit/test_runtime_seed.py \
  tests/integration/test_minimal_loop_runtime.py -q
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T6 spec；定义最小状态机、种子证据、确认门槛、预算和停止条件 |
