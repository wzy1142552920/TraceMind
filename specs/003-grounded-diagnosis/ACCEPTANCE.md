# TraceMind v0.3 验收矩阵

- **日期**：2026-10-22
- **状态**：PASS（T1–T7 implemented，2026-10-22）
- **范围**：T1–T7
- **AC 总数**：99
- **live 状态**：PASS（2026-10-22 执行完整 gate；Key/网络可用）
- **原则**：结果按实际测试/live 输出回填；未达标必须记录 FAIL/BLOCKED，不得伪造

> 本矩阵中 99 项 AC 均已执行并通过。离线结果：385 passed, 6 skipped；live 结果：4 passed in 65.38s。live 依赖外部模型/网络，不代表生产准确率。

## 1. T1 — 证据账本与假设协议

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T1-01 | Evidence 扩展字段/枚举完整，Ledger 去重/检索/绑定升级正确 | `tests/unit/test_evidence_ledger.py` | PASS |
| AC-T1-02 | 无 basis / basis 或 source_ref 无法解析 / 无 discriminating requirement 被拒绝 | `test_hypothesis_protocol.py` | PASS |
| AC-T1-03 | 合法假设（ID 或 source_ref basis）获得 runtime ID 和 requirement IDs | 同上 | PASS |
| AC-T1-04 | assessment 引用未绑定/不存在证据、歧义 source_ref 或 kind 不匹配被拒绝 | 同上 | PASS |
| AC-T1-05 | 同批重复 assessment 保留首条并进入 `rejected[]`；跨调用重评修订原判断并返回 `revised_assessment_ids` | 同上 | PASS |
| AC-T1-06 | 工具元数据成对校验，绑定写入 result/audit | `test_tool_binding.py` | PASS |
| AC-T1-07 | 单假设 qualifies 但替代未排除 → 不 confirmed | `test_grounded_evaluator.py` | PASS |
| AC-T1-08 | 全覆盖 + 替代 contradicted + 三类来源 → confirmed | 同上 | PASS |
| AC-T1-09 | 评估集中存在 refute 使假设 contradicted，并存 supports 不抵消；重评修订后按最新判断 | 同上 | PASS |
| AC-T1-10 | ranking_score 确定性、可解释、无 LLM confidence | 同上 | PASS |
| AC-T1-11 | 假设/requirement 超限被拒绝 | `test_hypothesis_protocol.py` | PASS |
| AC-T1-12 | 控制工具进入执行器审计，不直接写 evidence | `test_tool_binding.py` | PASS |
| AC-T1-13 | `require_log_thread_context=true` 时缺已评估上下文不能 confirmed；跨线程上下文不能计入；false 时不受影响 | `test_grounded_evaluator.py` | PASS |

## 2. T2 — 代码流索引与工具

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T2-01 | Controller/Service/Mapper 类/方法注解被索引 | `tests/unit/test_java_index.py` | PASS |
| AC-T2-02 | `handlePaid` → `updateStatus` 自调用边可查 | `test_code_flow.py` | PASS |
| AC-T2-03 | Controller → Service 调用边可查 | 同上 | PASS |
| AC-T2-04 | 重载 `updateStatus` 按参数个数过滤，保留候选 | 同上 | PASS |
| AC-T2-05 | `@Update` SQL/表名被提取 | 同上 | PASS |
| AC-T2-06 | `code.get_symbol` 返回注解/参数数/签名 | `test_code_flow_tools.py` | PASS |
| AC-T2-07 | 未知 symbol_id 返回 TARGET_DENIED | 同上 | PASS |
| AC-T2-08 | callers/callees 返回 confidence/provenance/source_ref | 同上 | PASS |
| AC-T2-09 | find_sql 可按表名/SQL 片段/符号搜索 | 同上 | PASS |
| AC-T2-10 | 工具描述/结果明确标注候选调用边 | 代码审查 + 测试 | PASS |
| AC-T2-11 | 现有 find_symbol/get_source_range 行为兼容 | 全量旧测试 | PASS |
| AC-T2-12 | 元数据参数可被 executor 识别，handler 不报错 | `test_tool_binding.py` | PASS |
| AC-T2-13 | 日志 `logger` 简单类名/栈帧可解析到类或方法 | `test_code_flow_tools.py` | PASS |

## 3. T3 — 只读验证工具契约

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T3-01 | 合法数据文件加载，describe/get_row 可用 | `tests/unit/test_fake_verification.py` | PASS |
| AC-T3-02 | 非法 JSON/schema/标识符/大文件被拒绝 | 同上 | PASS |
| AC-T3-03 | 未知表/列返回 TARGET_DENIED | `test_db_tools.py` | PASS |
| AC-T3-04 | 主键命中/未命中都返回结构化结果和 source_ref | 同上 | PASS |
| AC-T3-05 | columns 子集与敏感列脱敏正确 | 同上 | PASS |
| AC-T3-06 | 无 backend 时 DB 工具不注册 | registry/CLI 测试 | PASS |
| AC-T3-07 | `--verification-data` 非法时退出 2 且无 run 目录 | CLI E2E | PASS |
| AC-T3-08 | 所有 DB 调用有审计、只读、无任意 SQL 入口 | executor/audit 测试 | PASS |
| AC-T3-09 | 结果 environment=fixture，工具描述含非生产提示 | 工具/CLI 测试 | PASS |
| AC-T3-10 | 输出截断/超限标记 | tool executor 测试 | PASS |
| AC-T3-11 | 绑定元数据可传入且不破坏参数校验 | `test_tool_binding.py` | PASS |
| AC-T3-12 | 验证数据/证据不含秘密 | secret scan / 代码审查 | PASS |

## 4. T4 — 鉴别诊断运行时

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T4-01 | 初始证据含 log_event/log_thread_context/stack_frame/source_code | `tests/integration/test_v03_runtime.py` | PASS |
| AC-T4-02 | prompt 含同线程上下文、证据/假设/requirements/assessment/预算 | prompt 捕获测试 | PASS |
| AC-T4-03 | 控制工具可创建假设/assessment，LLM 不能传 status；重评修订原判断并发 `assessment.revised` | 集成测试 | PASS |
| AC-T4-04 | 证据工具绑定 meta，结果写入 bound_* | `test_tool_binding.py` + runtime | PASS |
| AC-T4-05 | 工具结果映射为证据，LLM 文本不进入 claim；同一真实事实可复用到其他 requirement | 集成测试 | PASS |
| AC-T4-06 | 每轮后 evaluator 更新状态/排序 | 集成测试 | PASS |
| AC-T4-07 | 开放替代假设时不 confirmed | 脚本化 provider | PASS |
| AC-T4-08 | 模型文本声称 confirmed 无效 | `test_model_prose_cannot_confirm` | PASS |
| AC-T4-09 | ungrounded/invalid assessment/no tools/no evidence/missing thread context 可 repair | 脚本化序列 | PASS |
| AC-T4-10 | repair 受预算限制，不重置状态 | budget 测试 | PASS |
| AC-T4-11 | 预算耗尽 → STOPPED_BUDGET；无进展 → INSUFFICIENT_DATA | runtime 测试 | PASS |
| AC-T4-12 | length 不执行半截工具 | 序列测试 | PASS |
| AC-T4-13 | 事件覆盖假设/评估/修订/证据/停止 | observability 测试 | PASS |
| AC-T4-14 | prompt 不含 case 期望答案/硬编码路径 | 代码审查 + prompt 断言 | PASS |
| AC-T4-15 | 现有 Mock happy path 迁移后通过 | 全量旧测试/E2E | PASS |
| AC-T4-16 | `logs.get_thread_context` 只返回同线程事件，映射为 `log_thread_context` 并支持绑定 | `test_v03_runtime.py` + tool 测试 | PASS |
| AC-T4-17 | 有线程号但缺已评估上下文、或上下文属于其他线程时不得 confirmed，且触发 repair | 脚本化序列 | PASS |

## 5. T5 — 结构化修复与报告 0.3

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T5-01 | 报告含 hypotheses/remediation_plan/verification，schema 0.3 | `tests/unit/test_report_v03.py` | PASS |
| AC-T5-02 | 修复建议只针对 supported/confirmed 假设 | `test_remediation.py` | PASS |
| AC-T5-03 | 无证据/伪造 evidence/无法解析 source_ref/错误 hypothesis 的 action 被拒绝 | 同上 | PASS |
| AC-T5-04 | code target 越界/不存在、data target 非白名单被拒绝 | 同上 | PASS |
| AC-T5-05 | 去重/每假设/总数上限生效 | 同上 | PASS |
| AC-T5-06 | supported 假设的建议标记 conditional | 报告测试 | PASS |
| AC-T5-07 | 无有效修复时不伪造并报 validation error；部分尝试被拒但保留有效方案时仍 grounded，只加 limitation | 同上 | PASS |
| AC-T5-08 | `db://`/thread 级 `log://` 引用校验、fake 环境标注 | `test_citation_validator.py` | PASS |
| AC-T5-09 | 诊断校验失败降级 status；remediation 失败不降级 | 报告测试 | PASS |
| AC-T5-10 | Markdown/CLI/RunStore 0.3 字段完整 | E2E/CLI 测试 | PASS |
| AC-T5-11 | 退出码不变 | CLI 测试 | PASS |
| AC-T5-12 | 报告/产物无 Key/完整 DB 行/完整源码 | secret scan/E2E | PASS |
| AC-T5-13 | 旧 root_causes 测试迁移，无 0.2 shim | 全量测试 | PASS |
| AC-T5-14 | remediation 调用计入 LLM/工具预算 | runtime 测试 | PASS |
| AC-T5-15 | 报告展示并校验同线程上下文证据（线程/行范围/messages） | `test_report_v03.py` + `test_citation_validator.py` | PASS |

## 6. T6 — 三 case 与 pytest 评测

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T6-01 | 三份日志内容一致且不含 Mapper/DB 真相 | `test_v03_cases.py::test_logs_are_identical` | PASS |
| AC-T6-02 | fixed/stub 仓库差异仅在 OrderMapper | 文件 diff 测试 | PASS |
| AC-T6-03 | C1/C2/C3 验证数据符合定义 | 数据加载测试 | PASS |
| AC-T6-04 | 三 case 离线报告 schema 0.3、Top-1 3/3 | 参数化 E2E | PASS |
| AC-T6-05 | 三 case requirements 覆盖 3/3 | 同上 | PASS |
| AC-T6-06 | 三 case 引用有效率 100%、fake 标注 100% | 同上 | PASS |
| AC-T6-07 | 三 case remediation 接地率 100% | 同上 | PASS |
| AC-T6-08 | 负向测试全部通过 | `test_v03_negative.py` | PASS |
| AC-T6-09 | 开放替代/单假设不得 confirmed | 同上 | PASS |
| AC-T6-10 | DB 越权/未知表/列被拒绝 | 同上 | PASS |
| AC-T6-11 | 恶意日志/DB 内容不改变策略 | 同上 | PASS |
| AC-T6-12 | runtime/prompt 无 case 特判 | `test_no_case_overfit.py` | PASS |
| AC-T6-13 | 默认 pytest 离线、确定性 | 全量测试；无网络 | PASS |
| AC-T6-14 | 失败信息包含 case/断言 | 测试代码审查 | PASS |
| AC-T6-15 | 三 case Top-1 均有同线程上下文与代码证据，上下文不含跨线程事件 | 参数化 E2E | PASS |
| AC-T6-16 | 缺上下文/跨线程/未绑定上下文的负向测试通过 | `test_v03_negative.py` | PASS |

## 7. T7 — Live 验证、文档与发布

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T7-01 | 默认 pytest 跳过 live，不访问网络 | 全量离线测试 | PASS |
| AC-T7-02 | live gate 三条件同时满足才运行 | conftest/gate 测试 | PASS |
| AC-T7-03 | 三 case live 报告结构 3/3 | live 测试 | PASS |
| AC-T7-04 | live Top-1 ≥2/3、Top-3 3/3 | live 断言/结果表 | PASS |
| AC-T7-05 | live 证据来源/接地/fixture 标注校验 | live 断言 | PASS |
| AC-T7-06 | live CLI 冒烟生成产物、无 secret | CLI E2E | PASS |
| AC-T7-07 | prompt/repair 无 case 硬编码 | 代码审查/overfit 扫描 | PASS |
| AC-T7-08 | README 记录 v0.3 能力/命令/限制 | 文档检查 | PASS |
| AC-T7-09 | ACCEPTANCE/T1–T7 回填，未达标如实记录 | 文档检查 | PASS |
| AC-T7-10 | 版本 0.3.0 一致 | `tracemind --version`/pyproject/lock | PASS |
| AC-T7-11 | 链接有效；旧 docs/specs 未修改 | 链接检查/git status | PASS |
| AC-T7-12 | 无 Key/`sk-` 泄露 | secret scan | PASS |
| AC-T7-13 | live Top-1 具备同线程上下文与代码证据；缺任一项不 confirmed | live 断言/结果表 | PASS |

## 8. 验证命令（已执行）

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src

# v0.3 专项离线
uv run pytest tests/unit/test_evidence_ledger.py tests/unit/test_hypothesis_protocol.py tests/unit/test_grounded_evaluator.py tests/unit/test_tool_binding.py -q
uv run pytest tests/unit/test_java_index.py tests/unit/test_code_flow.py tests/unit/test_code_flow_tools.py -q
uv run pytest tests/unit/test_fake_verification.py tests/unit/test_db_tools.py tests/e2e/test_cli_verification.py -q
uv run pytest tests/integration/test_v03_runtime.py -q
uv run pytest tests/unit/test_remediation.py tests/unit/test_report_v03.py tests/unit/test_citation_validator.py -q
uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py tests/eval/test_no_case_overfit.py -q

# live opt-in（需要项目 .env 或真实环境变量中的 Key）
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q
```

## 9. 最终验证与限制

最终验证（2026-10-22，版本 0.3.0）：

| 检查 | 结果 |
|---|---|
| 默认离线 `uv run pytest -q` | 385 passed, 6 skipped（live opt-in，不访问网络） |
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS（48 source files） |
| `uv run pytest --run-live -m live tests/live/test_live_v03_cases.py` | 4 passed in 65.38s |
| live 三 case | 3/3 confirmed；Top-1 3/3；Top-3 3/3；同线程上下文 3/3；代码证据 3/3 |
| live CLI 冒烟 | 退出码 0；5 类产物；schema 0.3；全部 validation flag=true；无 secret |
| 版本 | `tracemind 0.3.0`（pyproject/`__init__`/lock 一致） |
| 旧文档 | `docs/TraceMind_Agent_System_Design*.md`、`specs/001-minimal-loop/**`、`specs/002-live-deepseek/**` 未修改 |

live 一次记录：C1 11 calls/15 tools/74,918 tokens/23.8s；C2 7 calls/11 tools/41,548 tokens/17.6s；C3 11 calls/17 tools/71,296 tokens/23.8s。

限制：

- 三 case 是合成 fixture，不代表生产准确率；Fake 验证不等同真实数据库验证。
- v0.3 只分析用户提供的日志文件；不做持续监听、日志采集或告警接入。同线程上下文仅限该文件内事件。
- live 结果依赖外部 Key、网络和 DeepSeek 模型版本，具有非确定性；本次通过不应解读为稳定准确率。
- 代码流是 tree-sitter 启发式候选边，不是运行时调用图。
- 无 catalog/skill；新根因覆盖能力有限，后续根据实际记录决定是否增加。
- 修复建议只展示，不自动应用；不生成可执行补丁。
- 默认测试完全离线；live 测试必须显式 gate，未满足时只能记 BLOCKED。
