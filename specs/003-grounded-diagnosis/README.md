# TraceMind v0.3 — 证据落地的自主鉴别诊断 SDD

- **状态**：IMPLEMENTED（T1–T7，2026-10-22）
- **日期**：2026-10-22
- **父设计**：[TraceMind v2.0](../../docs/TraceMind_Agent_System_Design_v2.md)
- **上一版本**：[v0.2 live DeepSeek](../002-live-deepseek/README.md)
- **目标版本**：`0.3.0`

## 1. 目标与范围

v0.3 把 TraceMind 从“异常定位器”升级为“证据落地的自主鉴别诊断器”：

1. LLM 自主提出多个候选原因，而不是只依赖栈帧生成单一假设。
2. 每个假设必须基于已有的日志、源码或工具证据；没有依据的猜测不能进入假设列表。
3. LLM 自主规划代码流分析和只读验证工具，但工具调用必须绑定假设和验证要求。
4. 修复建议由 LLM 生成，但每条建议必须绑定假设、证据和修改目标。
5. 假设状态由确定性代码按动态证据契约判定，LLM 不能自证。
6. 使用三个“日志症状相同、真实根因不同”的 case 验证鉴别诊断能力。
7. 数据库验证在 v0.3 使用同一只读契约的 Fake 实现；真实 MySQL 连接留到后续版本。

**不引入领域 catalog**：三个 case 的预期答案只存在于测试数据，不进入 runtime prompt 或运行时规则。后续根据实际运行记录决定是否提炼 catalog 或 skill。

### 主业务流程

```text
异常日志（扫描输入日志 / 手动提供日志文件）
  -> 解析日志与堆栈，选择 primary anomaly
  -> 提取同线程日志上下文，重建业务步骤
  -> LLM 基于日志/代码证据提出多个候选原因
  -> 按需调用代码流工具、只读数据验证工具
  -> 代码流程与同线程日志上下文互相印证
  -> LLM 评估证据，确定性 Evaluator 判定状态
  -> 输出问题原因 + 结构化修复建议
  -> 每条结论/建议可追溯到真实证据
```

| 流程步骤 | v0.3 实现 | 约束 |
|---|---|---|
| 发现/输入异常日志 | CLI `--log` + `LogParser`；选择顺序：带堆栈的异常事件 → ERROR → WARN | v0.3 只处理用户提供的日志文件；不做持续监听/采集 |
| 读取日志上下文 | T4 初始 `log_thread_context` + `logs.get_thread_context`；同线程、按日志顺序 | 跨线程事件不得混入上下文；无线程号时标注缺失 |
| LLM 分析 | T4 多假设规划、代码流/数据工具调用、证据评估 | LLM 不能创建证据或设置状态 |
| 分析代码流程 | T2 `code.get_symbol/get_callers/get_callees/find_sql`；用 logger/栈帧定位类和方法 | 调用边是 AST 启发式候选，不是运行时调用链；日志与代码结论需互相印证 |
| 访问数据库 | T3 `db.describe_table/get_row` + Fake backend | 只读、主键单行、白名单；`environment=fixture` |
| 给出问题原因 | T5 报告 `hypotheses` + 确定性确认门槛 | `confirmed` 需同线程上下文、代码/工具证据覆盖、替代假设排除 |
| 给出修改建议 | T5 `remediation_plan` | 必须绑定假设和真实证据；不自动改代码 |
| 结论有依据 | Evidence Ledger + basis + requirements + 引用校验 | 证据只能由 parser/index/tool 产生 |

### In scope

- 证据账本（Evidence Ledger）和证据来源/绑定模型。
- 动态假设验证契约：basis evidence、verification requirements、falsifiers、assessments。
- LLM 自主假设、调查、证据评估和修复方案协议。
- 代码流索引与工具：注解、调用点、注解 SQL、重载候选消歧。
- 只读验证工具契约 + Fake backend + `db.describe_table` / `db.get_row`。
- 确定性 Evaluator：覆盖、证伪、替代假设、排序、确认门槛。
- 结构化修复方案与报告 schema 0.3。
- 三个鉴别诊断 case + pytest 离线评测。
- opt-in live DeepSeek 验证、文档和发布。

### Out of scope

- 领域 catalog、skill 库、模式规则引擎。
- 持续日志监听、日志采集/告警平台接入；v0.3 只处理用户提供的日志文件。
- 真实 MySQL/PostgreSQL/Redis 连接、MCP、SSH、审批 UI。
- 任意 SQL、写操作、自动改代码、自动应用 diff。
- MyBatis XML、JDT sidecar、完整类型解析、运行时调用图。
- OTel、SQLite/FTS5、Web UI、LLM-only ablation。
- 生产环境验证或生产准确率声明。

## 2. 核心不变量

1. **证据唯一来源**：证据只能由日志解析器、索引器和 ToolExecutor 产生；LLM 不能创建、修改或伪造证据。
2. **假设必须有依据**：`basis_evidence_ids` 非空且必须是已存在的真实证据。
3. **调查必须可追溯**：验证类工具调用必须绑定 `hypothesis_id` + `requirement_id`；未绑定证据只能作为假设依据，不能用于满足验证要求。
4. **修复必须落地**：每条修复建议必须引用真实证据、绑定已支持/已确认的假设，并给出可校验的修改目标。
5. **LLM 不自证**：LLM 可以提出验证条件和证伪条件，但不能设置假设状态。
6. **鉴别优先**：至少两个候选假设被评估；仍有开放替代假设时不能 `confirmed`。
7. **来源覆盖**：确认必须覆盖日志、代码、工具结果三类来源；同线程日志上下文属于日志来源。
8. **上下文优先**：主事件有线程号时，必须结合同线程日志上下文和代码流程分析；缺少已评估的上下文不能 `confirmed`。
9. **诚实标注**：Fake 验证数据必须在证据 provenance 和报告中明确标注，不能冒充生产验证。
10. **只读有界**：所有工具只读、参数受限、输出截断、调用审计、预算有界。

## 3. 架构摘要

```text
异常日志（primary event + 同线程上下文）+ 仓库 + 验证数据
  -> LogParser / JavaIndex 产生初始证据
  -> LLM 提出 grounded hypotheses（basis + requirements + falsifiers）
  -> LLM 规划调查工具（绑定 hypothesis / requirement）
  -> ToolExecutor 只读执行并产生证据
  -> LLM 结合同线程日志与代码流提交结构化 assessment
  -> 确定性 Evaluator 更新状态、覆盖和排序
  -> LLM 基于已支持/已确认假设生成 remediation actions
  -> 确定性校验 -> report schema 0.3
```

跨任务的协议、数据模型、确认门槛、评分和报告契约见 [DESIGN.md](./DESIGN.md)。

## 4. 任务索引

| ID | 任务 | 依赖 | 状态 | Spec | Task |
|---|---|---|---|---|---|
| T1 | 证据账本与假设协议 | — | implemented | [spec](./T1-evidence-hypothesis-protocol/spec.md) | [task](./T1-evidence-hypothesis-protocol/task.md) |
| T2 | 代码流索引与工具 | T1 | implemented | [spec](./T2-code-flow-index/spec.md) | [task](./T2-code-flow-index/task.md) |
| T3 | 只读验证工具契约 | T1 | implemented | [spec](./T3-verification-tools/spec.md) | [task](./T3-verification-tools/task.md) |
| T4 | 鉴别诊断运行时 | T1、T2、T3 | implemented | [spec](./T4-differential-runtime/spec.md) | [task](./T4-differential-runtime/task.md) |
| T5 | 结构化修复与报告 0.3 | T4 | implemented | [spec](./T5-remediation-report/spec.md) | [task](./T5-remediation-report/task.md) |
| T6 | 三 case 与 pytest 评测 | T1–T5 | implemented | [spec](./T6-cases-eval/spec.md) | [task](./T6-cases-eval/task.md) |
| T7 | Live 验证、文档与发布 | T6 | implemented | [spec](./T7-live-docs-release/spec.md) | [task](./T7-live-docs-release/task.md) |

**执行顺序**：

```text
T1
 ├─> T2 ─┐
 └─> T3 ─┴─> T4 -> T5 -> T6 -> T7
```

T2 与 T3 可以在 T1 完成后并行；T4 需要两者都完成。T5 之后才能定义完整报告 schema；T6 是三 case 的集成验收，T7 才做 live 和发布。

## 5. 共享决策

### 5.1 无 catalog，LLM 自主规划

- 假设、验证要求、工具计划、修复方案均由 LLM 提出。
- 运行时只提供通用协议和安全边界，不内置三个 case 的领域规则。
- 三个 case 的 ground truth 只用于 pytest 断言，不进入 runtime。
- 后续是否增加 catalog/skill，由 T6/T7 的实际运行记录决定；v0.3 不实现。

### 5.2 动态证据契约

- 每个假设自带 `requirements[]` 和 `falsifiers[]`。
- LLM 通过 `diagnosis.propose_hypothesis` 创建假设，通过 `diagnosis.assess_evidence` 解释真实证据。
- 确定性 Evaluator 检查：basis、要求覆盖、区分性证据、来源类型、证伪、替代假设、引用。
- LLM 不传 `status`、不写 evidence、不直接决定报告状态。

### 5.3 工具调用绑定

- T1 定义证据类工具的公共元数据字段：`hypothesis_id`、`requirement_id`。
- 只有绑定了 requirement 的工具证据才能满足验证要求。
- 未绑定证据可以成为后续假设的 basis，但不会被计入确认覆盖。
- 一个真实工具事实可以有多个绑定，复用到其他 hypothesis/requirement，不重复复制证据或工具调用。
- assessment 按条校验；合法条目在部分失败批次中保留，同一目标重评修订旧 verdict。
- 控制工具输入可用 `evidence_id` 或 `source_ref`；runtime 统一解析为 evidence_id 并校验唯一性/关联性。
- 所有调用经过 ToolExecutor，记录参数 hash、绑定、结果、耗时和错误。

### 5.4 Fake 验证边界

- v0.3 只实现 `FakeVerificationBackend`，数据来自 `--verification-data` JSON。
- 数据库工具只支持 `describe_table` 和按主键 `get_row`；不开放任意 SQL。
- 证据 provenance 固定为 `fake_verification`；报告必须设置 `verification.environment=fixture` 并给出限制说明。
- 没有验证后端时，DB 工具不注册；数据类假设最多 `supported`，不能 `confirmed`。

### 5.5 评测方式

- 只做 pytest 验收，不新增 `tracemind eval` CLI。
- 三个 case 通过 MockProvider 脚本做确定性集成测试。
- 每个 case 检查：Top-1 原因、预期证据来源、要求覆盖、修复建议接地率、引用有效性、验证环境标注。
- 默认测试完全离线；live 测试在 T7 以 opt-in 方式加入。

### 5.6 报告与版本

- 报告 schema 升级到 `0.3`，不提供 `0.2` 兼容 shim。
- 新报告包含：鉴别诊断（hypotheses）、验证过程、结构化修复方案。
- 现有 `root_causes` 由 `hypotheses` 替代；CLI 摘要和 RunStore 同步升级。
- 退出码保持不变：`0` 成功，`1` 运行时错误，`2` CLI/配置错误，`3` 证据不足，`4` 预算耗尽。

### 5.7 Live 验证

- 只有 `--run-live`、`TRACEMIND_LIVE_TESTS=1` 和 Key 三者同时满足才运行 live。
- live 目标：三 case 报告结构合法、引用有效、修复接地；Top-1 ≥ 2/3、Top-3 3/3。
- 未达标必须记录为 FAIL/BLOCKED，不能写成通过。
- 2026-10-22 实际 gate：4 passed in 65.38s；三 case confirmed，Top-1 3/3、Top-3 3/3、同线程上下文 3/3、代码证据 3/3。
- live 预算为 16 iterations / 18 LLM calls / 24 tool calls / 2000 output tokens。
- live 结果受 DeepSeek 模型版本和网络影响；不宣称生产准确率。

## 6. 验收

详细矩阵见 [ACCEPTANCE.md](./ACCEPTANCE.md)。

v0.3 完成时至少满足：

- T1–T7 的 AC 全部有结果，不允许伪造 PASS。
- 离线 pytest 三 case 全部生成 schema 0.3 报告，Top-1 3/3。
- 未接地假设、伪造证据 ID、无效 assessment、无证据修复建议全部被拒绝。
- 所有 DB 调用只读、白名单内、可审计；越权调用 0。
- 报告引用有效率 100%；Fake 验证标注 100%。
- `ruff check .`、`mypy src` 通过。
- live 状态如实回填；无 Key 时为 BLOCKED。

## 7. 文档约定

- 每个任务包含 `spec.md`（Context、In/Out scope、FR、契约、AC、测试计划、风险、验证命令、变更记录）和 `task.md`（实施顺序、交付物、DoD、验证命令、风险、验证结果）。
- 未实现项状态写 `planned`；测试和结果未执行时写 `PLANNED`，不得预填 PASS。
- 不修改 `docs/TraceMind_Agent_System_Design*.md`、`specs/001-minimal-loop/**`、`specs/002-live-deepseek/**`。
- 跨任务协议以 [DESIGN.md](./DESIGN.md) 为准；若任务实现与 DESIGN 冲突，先更新 DESIGN 和受影响 spec，再改代码。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-22 | 创建 v0.3 SDD：无 catalog、LLM 自主规划、动态证据契约、Fake 验证、三 case、T1–T7 拆分 |
| 2026-10-22 | T1–T3 implemented：证据/假设协议、代码流索引与工具、只读验证工具 |
| 2026-10-22 | T4 implemented：grounded 多假设运行时、同线程上下文、确定性证据映射与 repair；Mock happy path 迁移；T5 待实现 |
| 2026-10-22 | T5 implemented：REPORTING 单次 remediation 调用、证据/假设/target 校验、报告 schema 0.3、引用与 fixture 标注校验；全量离线测试通过 |
| 2026-10-22 | T6 implemented：三 case 离线确认、同线程上下文与代码证据互证、负向/安全/防过拟合测试；Top-1 3/3、引用 100%、接地 100%、越权 0；49 项 T6 测试通过 |
| 2026-10-22 | T7 implemented：live 三 case 全部 confirmed（Top-1 3/3、Top-3 3/3），CLI 冒烟成功；证据多绑定/复用、assessment 修订/部分接受、prompt 正文暴露和 remediation allowed evidence 已回填；版本 0.3.0；最终离线 385 passed, 6 skipped |
