# T6 — 三 case 与 pytest 评测 Spec

- **任务 ID**：T6
- **状态**：implemented
- **依赖**：T1、T2、T3、T4、T5
- **下游**：T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.2 只有一个合成 case，且根因就是异常位置；它无法证明“日志定位点 ≠ 真因”，也无法证明代码流和只读验证工具的价值。v0.3 需要三个日志症状几乎相同、但根因不同的 case，并用 pytest 做确定性验收。

**用户故事**：作为项目作者，我能运行 `pytest`，看到三个 case 都生成 schema 0.3 报告，Top-1 原因正确、证据链可复核、修复建议有证据绑定；没有 catalog 或 case 特判在“作弊”。

## 2. In scope

- 三个 case：
  - C1：orders 表无该行 → `UPDATE` 0 行 → Service 抛错。
  - C2：orders 行存在且已 PAID，SQL 带 `status <> ?` → 0 行 → Service 抛错。
  - C3：Mapper `updateStatus` 是 `default` 方法且方法体 `return 0` → SQL 未执行 → 0 行 → Service 抛错。
- 两份仓库变体（共享 Service/Controller）：
  - `minimal-order-service-fixed`（C1/C2）。
  - `minimal-order-service`（C3；保留现有 fixture）。
- 三份日志（内容一致，避免日志泄漏答案）：
  - 主事件所在线程的完整业务步骤（INFO → WARN → ERROR）。
  - 混入其他线程的 DEBUG 噪声，验证同线程上下文过滤。
- 三份验证数据。
- 三份 MockProvider JSON 脚本。
- 三份 expected YAML（含预期线程、同线程上下文事件、证据种类）。
- pytest 评测 harness：
  - Top-1 原因、预期证据来源、同线程上下文与代码证据互证、requirements 覆盖、引用有效、remediation 接地、fixture 标注。
  - 负向测试：未接地假设、伪造证据、无证据修复、开放替代假设、未知表/列、缺同线程上下文、跨线程证据。
  - Prompt injection/不可信数据测试。
  - 防过拟合检查：runtime/prompt 不含 case ID/期望答案。
- 验收阈值和结果回填。

## 3. Out of scope

- `tracemind eval` CLI（明确不做）。
- LLM-only ablation。
- live DeepSeek 结果（T7）。
- 真实 DB、MCP、MyBatis XML、Redis、连接池、异步等更多 fixture。
- 统计意义上的准确率声明。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T6-01 | 三 case 日志症状一致，根因分别由数据/代码差异决定 | must |
| FR-T6-02 | fixed/stub 两份仓库共享 Service/Controller，仅 Mapper 变化 | must |
| FR-T6-03 | 三份验证数据分别覆盖缺失行、PAID 行、PENDING 行 | must |
| FR-T6-04 | 三份 Mock 脚本完整走通假设/代码流/DB/assessment/remediation | must |
| FR-T6-05 | 三份 expected YAML 定义 Top-1 关键词/证据/状态/修复类型 | must |
| FR-T6-06 | pytest 对三 case 生成 schema 0.3 报告并断言关键指标 | must |
| FR-T6-07 | 离线 Top-1 3/3、requirements 覆盖 3/3、引用 100%、remediation 接地 100% | must |
| FR-T6-08 | 负向测试覆盖未接地/伪造证据/无效 assessment/无证据修复 | must |
| FR-T6-09 | 开放替代假设时不得 confirmed | must |
| FR-T6-10 | 未知表/列、越权 DB 调用被拒绝 | must |
| FR-T6-11 | 恶意日志/DB 内容不改变工具策略 | must |
| FR-T6-12 | runtime/prompt 无 case 特判/期望答案 | must |
| FR-T6-13 | 默认 pytest 完全离线、确定性 | must |
| FR-T6-14 | 测试失败信息可定位到 case/断言 | must |
| FR-T6-15 | 三 case 的 Top-1 同时具备同线程上下文与代码/工具证据，并在报告中可复核 | must |
| FR-T6-16 | 日志含跨线程噪声；缺上下文/跨线程证据的负向测试通过 | must |

## 5. 接口/数据契约

### 5.1 Fixture 布局

```text
fixtures/
├── logs/
│   ├── v03-c1-missing-row/incident.log
│   ├── v03-c2-duplicate-callback/incident.log
│   └── v03-c3-mapper-stub/incident.log
├── repos/
│   ├── minimal-order-service/            # C3: default mapper returns 0
│   └── minimal-order-service-fixed/      # C1/C2: @Update abstract method
├── verification/
│   ├── v03-c1-missing-row.json
│   ├── v03-c2-duplicate-callback.json
│   └── v03-c3-mapper-stub.json
├── mock/
│   ├── v03-c1-missing-row.json
│   ├── v03-c2-duplicate-callback.json
│   └── v03-c3-mapper-stub.json
└── expected/
    ├── v03-c1-missing-row.yaml
    ├── v03-c2-duplicate-callback.yaml
    └── v03-c3-mapper-stub.yaml
```

### 5.2 日志

三份日志内容一致（可逐字节比较），使用真实调用栈，并混入跨线程噪声：

```text
2026-10-18 10:21:03.409 DEBUG [http-nio-8080-exec-3] c.e.pay.PaymentNotifier - webhook ack orderId=10086
2026-10-18 10:21:03.412 INFO  [http-nio-8080-exec-7] c.e.order.OrderController - paid callback orderId=10086
2026-10-18 10:21:03.413 DEBUG [http-nio-8080-exec-3] c.e.pay.PaymentNotifier - retry probe scheduled
2026-10-18 10:21:03.415 WARN  [http-nio-8080-exec-7] c.e.order.OrderService - updateStatus returned rows=0, orderId=10086
2026-10-18 10:21:03.416 ERROR [http-nio-8080-exec-7] c.e.order.OrderService - failed to update order status
java.lang.IllegalStateException: update failed for orderId=10086
    at com.example.order.OrderService.updateStatus(OrderService.java:24)
    at com.example.order.OrderService.handlePaid(OrderService.java:14)
    at com.example.order.OrderController.paid(OrderController.java:16)
    at java.base/java.lang.Thread.run(Thread.java:840)
```

- 日志只指向 Service，不包含 Mapper/DB 真相。
- 三 case 日志相同，确保区分只能靠代码流/验证数据。
- 同线程 `http-nio-8080-exec-7` 的可分析上下文为 INFO/WARN/ERROR 三条；`http-nio-8080-exec-3` 的 DEBUG 是非同线程噪声，不能被 `logs.get_thread_context` 或初始上下文证据包含。

### 5.3 仓库变体

共享文件：

- `OrderController.java`
- `OrderService.java`

差异仅在 `OrderMapper.java`：

**fixed（C1/C2）**

```java
@Mapper
public interface OrderMapper {
    @Select("SELECT status FROM orders WHERE id = #{orderId}")
    String findStatus(Long orderId);

    @Update("UPDATE orders SET status = #{status} WHERE id = #{orderId} AND status <> #{status}")
    int updateStatus(Long orderId, String status);
}
```

**stub（C3）**

```java
@Mapper
public interface OrderMapper {
    @Select("SELECT status FROM orders WHERE id = #{orderId}")
    String findStatus(Long orderId);

    default boolean exists(Long orderId) {
        return findStatus(orderId) != null;
    }

    @Update("UPDATE orders SET status = #{status} WHERE id = #{orderId}")
    default int updateStatus(Long orderId, String status) {
        return 0;
    }
}
```

- C3 的 `default` 方法体 `return 0` 是根因；`@Update` 存在但 MyBatis 不执行 default 方法体。
- 两份仓库的 `OrderService` 行号保持一致，日志栈可复用。

### 5.4 验证数据

| Case | orders 表 | 其他 |
|---|---|---|
| C1 | 无 id=10086 的行 | columns: id/status/updated_at |
| C2 | id=10086, status=PAID, updated_at 较早 | 同一 SQL guard 导致 0 行 |
| C3 | id=10086, status=PENDING | Mapper 未执行 SQL |

```json
{
  "backend": "fake",
  "tables": {
    "orders": {
      "primary_key": "id",
      "columns": ["id", "status", "updated_at"],
      "sensitive_columns": [],
      "rows": []
    }
  }
}
```

### 5.5 Expected YAML

```yaml
case_id: v03-c1-missing-row
symptom: "updateStatus returned rows=0; update failed"
expected_top_cause_keywords:
  - missing
  - not found
  - 不存在
expected_thread: http-nio-8080-exec-7
expected_thread_context_messages:
  - "paid callback orderId=10086"
  - "updateStatus returned rows=0"
  - "failed to update order status"
forbidden_thread_context_markers:
  - PaymentNotifier
  - retry probe
expected_evidence_refs:
  - "db://orders/id=10086"
  - "repo://src/main/java/com/example/order/OrderService.java"
expected_evidence_kinds:
  - log_thread_context
  - source_code
  - db_row
expected_status: confirmed
expected_hypothesis_status: confirmed
expected_remediation_types:
  - code
  - test
expected_remediation_target_keywords:
  - OrderService
forbidden_tool_calls: []
notes: "订单行不存在；修复应区分不存在与无变化，并补充测试。"
```

- C2 关键词：duplicate / idempotent / already paid / 幂等 / 重复回调；Top-1 refs 指向 `OrderService.java`、`OrderMapper.java` 与 DB。
- C3 关键词：default / stub / return 0 / 默认方法 / 未执行。
- expected 只用于测试，runtime/prompt 不得读取。
- 证据 refs 检查子集（允许额外证据）；C1/C2 期望 Service/DB 与对应代码证据，C3 至少包含 `OrderMapper.java`。
- `expected_evidence_kinds` 检查 Top-1 已满足的 requirement 覆盖种类（子集）；每个 case 必须包含 `log_thread_context` 与至少一种代码证据（`source_code`/`call_path`/`sql`）。
- 同线程上下文检查：证据 source_ref 的 thread 必须等于 `expected_thread`；上下文摘要不得包含 `forbidden_thread_context_markers`。
- C1/C2 的替代假设（缺失 SQL 谓词、default stub、Service 忽略 rows）通过读取 `OrderMapper.java` / `OrderService.java` 反驳；这不要求出现在 Top-1 的 expected refs 中。

### 5.6 Mock 脚本

三份 JSON 脚本按轮次返回：

1. 提出 3 个候选假设（basis 使用初始证据 ID 或 source_ref）。
2. 调用 `logs.get_thread_context`，绑定正确假设的“同线程上下文” requirement，并提交 supports assessment。
3. 调用代码流工具和 DB 工具（使用 T1 meta 绑定 hypothesis/requirement；evidence 引用用 `source_ref` 解析）。
4. 提交 assessments（supports/refutes），排除替代假设。
5. 如仍有缺口，补充工具/assessment。
6. REPORTING 提交 remediation actions（引用 `evidence_source_refs` 或 evidence IDs）。

- 脚本必须覆盖“支持正确原因 + 反驳另外两个”的完整路径。
- 正确假设至少包含同线程上下文、代码、工具三类来源的 requirement，且全部被 assess；否则无法通过确认门槛。
- 同线程上下文 requirement 只绑定到正确假设（expected Top-1）；替代假设用代码/DB 证据反驳，避免同一证据被重复绑定到多个 requirement。
- C3 必须调用 `code.get_source_range` 读取 `OrderMapper.updateStatus` 方法体，证明 `default` + `return 0`；仅看 `@Update` 注解不足以定位。C1/C2 也需读取 SQL guard 或调用链，不能只依赖初始源码证据。
- 脚本不得引用不存在的表/列/证据；不得把 `PaymentNotifier` 或跨线程 DEBUG 事件写入上下文证据。
- 初始证据顺序固定：`ev_0001` log_event、`ev_0002` log_thread_context、`ev_0003` stack_frame、`ev_0004` source_code；脚本尽量用 source_ref，减少对 ID 顺序的依赖。
- JSON 脚本可安全使用 `basis_source_refs` / assessment `source_ref` / `evidence_source_refs`；runtime 解析为 evidence_id，静态脚本无需知道动态 ID。

### 5.7 pytest harness

- `tests/eval/test_v03_cases.py`：参数化三 case。
- `tests/eval/helpers.py`：加载 case、运行 runtime、构建报告、收集指标。
- 每个 case 断言：
  1. `report.schema_version == "0.3"`。
  2. `report.status == expected_status`。
  3. `report.hypotheses[0].status == expected_hypothesis_status`。
  4. Top-1 statement 含任一关键词。
  5. Top-1 的 basis/supporting source_refs 包含 expected refs（子集）。
  6. Top-1 至少一个 satisfied requirement 的 kind 为 `log_thread_context`，其证据 source_ref 的 thread 等于 `expected_thread`，且报告 source 的 `messages`（或 claim）包含 expected messages、不含 forbidden markers。
  7. Top-1 至少一个 satisfied requirement 的 kind ∈ {source_code, call_path, sql}。
  8. 所有 requirements `satisfied=true`。
  9. `report.remediation_plan` 非空；所有 action 的 evidence IDs 存在并关联假设；type 包含期望类型；targets 含关键词。
  10. `validation.citations_valid/evidence_ids_valid/hypotheses_valid/remediation_grounded/verification_labeled/status_consistent` 为 true。
  11. `verification.environment == "fixture"`。
  12. 无 forbidden tool call；audit 中所有 DB 调用为只读白名单。
- 指标：Top-1 3/3、Top-3 3/3、同线程上下文 3/3、代码证据 3/3、覆盖 3/3、引用 100%、接地 100%、越权 0。
- 失败信息包含 case_id 和失败断言。

### 5.8 负向测试

- `tests/eval/test_v03_negative.py`：
  - 未接地假设（无 basis）→ 拒绝。
  - 伪造 evidence ID → 拒绝。
  - assessment 引用未绑定证据 → 拒绝。
  - remediation 无证据 → 拒绝。
  - 开放替代假设仍 supported → 不 confirmed。
  - DB 未知表/列 → TARGET_DENIED。
  - DB 数据行含“忽略之前指令”→ 不改变工具/预算/确认。
  - log 含伪造 system 文本 → 不改变策略。
  - 跨线程 DEBUG 事件不能作为 `log_thread_context` 证据（工具过滤 + 证据 kind/source_ref 校验）。
  - 有线程号但不调用 `logs.get_thread_context`、不评估上下文 → 不得 confirmed，触发 `missing_thread_context` repair。
  - 未绑定的初始上下文证据直接 assessment → INVALID_ASSESSMENT。
- `tests/eval/test_no_case_overfit.py`：
  - 扫描 runtime/prompt/control/evidence 源码，禁止出现 case ID、expected 关键词、fixture 路径。
  - 允许测试/fixture 目录出现。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T6-01 | 三份日志内容一致且不含 Mapper/DB 真相 | `test_v03_cases.py::test_logs_are_identical` |
| AC-T6-02 | fixed/stub 仓库差异仅在 OrderMapper | 文件 diff 测试 |
| AC-T6-03 | C1/C2/C3 验证数据符合定义 | 数据加载测试 |
| AC-T6-04 | 三 case 离线报告 schema 0.3、Top-1 3/3 | 参数化 E2E |
| AC-T6-05 | 三 case requirements 覆盖 3/3 | 同上 |
| AC-T6-06 | 三 case 引用有效率 100%、fake 标注 100% | 同上 |
| AC-T6-07 | 三 case remediation 接地率 100% | 同上 |
| AC-T6-08 | 负向测试全部通过 | `test_v03_negative.py` |
| AC-T6-09 | 开放替代/单假设不得 confirmed | 同上 |
| AC-T6-10 | DB 越权/未知表/列被拒绝 | 同上 |
| AC-T6-11 | 恶意日志/DB 内容不改变策略 | 同上 |
| AC-T6-12 | runtime/prompt 无 case 特判 | `test_no_case_overfit.py` |
| AC-T6-13 | 默认 pytest 离线、确定性 | 全量测试；无网络 |
| AC-T6-14 | 失败信息包含 case/断言 | 测试代码审查 |
| AC-T6-15 | 三 case Top-1 均有已评估的同线程上下文与代码证据，且上下文不含跨线程事件 | 参数化 E2E |
| AC-T6-16 | 缺上下文/跨线程/未绑定上下文的负向测试通过 | `test_v03_negative.py` |

## 7. 测试计划

### 新增

- `tests/eval/test_v03_cases.py`
- `tests/eval/test_v03_negative.py`
- `tests/eval/test_no_case_overfit.py`
- `tests/eval/helpers.py`
- `tests/eval/conftest.py`（如需）

### 更新

- 现有 `tests/e2e/test_minimal_loop.py`：fixture/schema 0.3 或迁移到新 case。
- `tests/live/` 不在 T6 修改（T7）。

### 断言策略

- Mock 下可以断言关键词和证据来源。
- live 下只断言结构/证据/接地，不锁定自然语言（T7）。
- 关键词只用于测试，不能进入 runtime/prompt。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| Mock 脚本过拟合 | 脚本按 case 编排 | runtime 无 case 分支；overfit 扫描；T7 live |
| 关键词脆弱 | 同义表达 | Mock 使用明确短语；live 看证据/结构 |
| 三 case 太相似 | 只测一个模式 | C1/C2/C3 分别覆盖数据缺失/幂等/代码缺陷 |
| Fake 数据不真实 | 生产行为差异 | 明确 fixture 边界；T7 只做结构验证 |
| 日志相同但栈行号变化 | 仓库改动导致栈不匹配 | 保持 Service/Controller 行号；测试校验 |
| 证据 refs 依赖 LLM 输出 | 自由文本不精确 | 用结构化 evidence source_refs 断言 |
| 同线程噪声过多 | 干扰上下文还原 | 仅混入 2 条跨线程 DEBUG；断言被排除 |
| 上下文证据未绑定 | 初始上下文只能当 basis | Mock 显式调用 `logs.get_thread_context` 并 assess；负向测试 |
| 测试运行时间 | 三 case + runtime | 离线 Mock，小预算；无网络 |

**开放问题**

- 是否需要第四个 case（例如 SQL 条件写错）？v0.3 三个足够；后续扩展。
- 是否输出指标汇总文件？pytest-only，不新增 CLI/文件；用断言和 `-ra` 输出。
- 是否保留 v0.2 basic case？保留为回归，但主验收用三 case。

## 9. 验证命令

```bash
uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py tests/eval/test_no_case_overfit.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| 2026-10-22 | T6 pytest（3 个文件） | PASS：49 passed |
| 2026-10-22 | 全量 `pytest -q` | PASS：374 passed, 2 skipped |
| 2026-10-22 | `ruff check .` | PASS |
| 2026-10-22 | `mypy src` | PASS（48 source files） |

指标：Top-1 3/3、Top-3 3/3、同线程上下文 3/3、代码证据 3/3、requirements 覆盖 3/3、引用 18/18（100%）、remediation 接地 6/6（100%）、DB 越权 0、fixture 标注 3/3。每 case 4 次 LLM 调用、11 次工具调用、5 次 assessment、2 条修复建议，全部 validation flag 为 true。详细结果见 [task.md §6](./task.md#6-验证结果实现后回填)。

未达标项：无。

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-22 | 创建 T6 spec：三 case、仓库变体、验证数据、Mock 脚本、pytest 评测与负向/防过拟合测试 |
| 2026-10-22 | 日志加入跨线程噪声；评测增加同线程上下文+代码互证、上下文负向测试与 AC-15/16 |
| 2026-10-22 | T6 实现完成：三 case 离线确认、49 项 T6 测试通过，指标全部达标 |
