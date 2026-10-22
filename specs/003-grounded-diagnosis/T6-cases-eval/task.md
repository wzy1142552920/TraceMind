# T6 — 三 case 与 pytest 评测 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T6
- **状态**：implemented
- **依赖**：T1、T2、T3、T4、T5
- **下游**：T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T6 spec、[DESIGN §13](../DESIGN.md)、T1–T5 的工具/证据/报告契约。
   - 确认只做 pytest，不新增 `tracemind eval` CLI。
   - 确认三 case 的 expected 只在测试数据，不进入 runtime/prompt。
   - 确认同线程上下文与代码证据都要被评测。

2. **准备 fixtures**
   - 复制现有 order-service 为 `minimal-order-service-fixed`，只改 `OrderMapper.updateStatus` 为抽象 `@Update`。
   - 保留 `minimal-order-service` 作为 C3 stub 变体。
   - 创建三份内容一致的日志：同线程 INFO/WARN/ERROR + 两条跨线程 DEBUG 噪声。
   - 创建三份验证数据。
   - 创建三份 expected YAML（线程、上下文消息、禁止标记、证据种类）。
   - 校验行号：日志栈指向 `OrderService.java:24`、`OrderService.java:14`、`OrderController.java:16`。

3. **编写 Mock 脚本**
   - 三份 JSON 脚本按 T6 spec 的轮次编排。
   - 假设 basis 用初始 evidence ID 或 source_ref。
   - 先调用 `logs.get_thread_context` 并绑定正确假设；工具调用绑定 hypothesis/requirement；assessment 用 source_ref 解析。
   - remediation 用 `evidence_source_refs` 或 evidence IDs。
   - 确保正确原因被支持、另外两个被 refute；离线脚本优先用代码/DB 证据反驳替代假设；若语义相同，同一工具事实可以多绑定复用。
   - 正确假设的 requirements 覆盖同线程上下文、代码、工具三类来源，且全部被 assess；否则确认门槛无法通过。
   - 脚本先跑通 runtime，再写断言。

4. **实现 pytest harness**
   - `tests/eval/helpers.py`：加载 case、构建 runtime/report、提取指标。
   - `tests/eval/test_v03_cases.py`：参数化断言。
   - 断言 Top-1 的同线程上下文（线程号/消息/无跨线程标记）与代码证据。
   - 失败信息包含 case_id + 断言名。
   - 不访问网络、不依赖实时模型。

5. **负向与安全测试**
   - `tests/eval/test_v03_negative.py`：
     - 未接地/伪造证据/无效 assessment/无证据修复。
     - 开放替代不确认。
     - DB 未知表/列。
     - 恶意日志/DB 内容。
     - 缺同线程上下文 → 不 confirmed + repair；未绑定上下文 assessment 拒绝；跨线程事件被排除。
   - `tests/eval/test_no_case_overfit.py`：扫描 runtime/prompt 源码。

6. **回归与回填**
   - 更新受影响的 E2E/旧 fixture 测试。
   - 运行 T6 验证命令，记录三 case 指标。
   - 回填 task/spec 验证结果，未达标如实记录。

## 2. 交付物

- [x] `fixtures/logs/v03-c1-missing-row/incident.log`
- [x] `fixtures/logs/v03-c2-duplicate-callback/incident.log`
- [x] `fixtures/logs/v03-c3-mapper-stub/incident.log`
- [x] `fixtures/repos/minimal-order-service-fixed/**`
- [x] `fixtures/repos/minimal-order-service/**`（C3 保留/校验）
- [x] `fixtures/verification/v03-c1-missing-row.json`
- [x] `fixtures/verification/v03-c2-duplicate-callback.json`
- [x] `fixtures/verification/v03-c3-mapper-stub.json`
- [x] `fixtures/mock/v03-c1-missing-row.json`
- [x] `fixtures/mock/v03-c2-duplicate-callback.json`
- [x] `fixtures/mock/v03-c3-mapper-stub.json`
- [x] `fixtures/expected/v03-c1-missing-row.yaml`
- [x] `fixtures/expected/v03-c2-duplicate-callback.yaml`
- [x] `fixtures/expected/v03-c3-mapper-stub.yaml`
- [x] `tests/eval/helpers.py`
- [x] `tests/eval/test_v03_cases.py`
- [x] `tests/eval/test_v03_negative.py`
- [x] `tests/eval/test_no_case_overfit.py`
- [x] E2E/回归测试：全量回归通过，现有 E2E 无需额外迁移

## 3. Definition of Done

- [x] AC-T6-01 至 AC-T6-16 全部满足。
- [x] 三 case 日志一致（含跨线程噪声）；fixed/stub 差异仅在 Mapper。
- [x] 离线 Top-1 3/3、同线程上下文 3/3、代码证据 3/3、覆盖 3/3、引用 100%、接地 100%、越权 0。
- [x] 负向/安全/防过拟合测试通过。
- [x] 三 case 报告均为 schema 0.3，fixture 标注正确。
- [x] 默认 pytest 完全离线、确定性；无网络/Key 依赖。
- [x] 全量测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py tests/eval/test_no_case_overfit.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **Mock 过拟合**：runtime 无 case 分支；overfit 扫描；T7 live 验证真实模型。
- **日志/行号漂移**：共享 Service/Controller 不改；测试校验栈行号。
- **证据引用**：脚本用 source_ref 而非硬编码 ID，减少 runtime 顺序耦合。
- **关键词脆弱**：Mock 用明确短语；live 以证据/结构为主。
- **Fixture 真实性**：合成数据只验证协议，不代表生产；T7/README 声明。
- **上下文绑定**：同一上下文证据可绑定多个 requirement/假设；离线 Mock 仍用代码/DB 证据区分替代假设，避免仅凭共享上下文排除。
- **跨线程噪声**：日志必须保持三 case 逐字节一致；新增噪声后同步校验主事件选择和上下文行范围。
- **测试时间**：离线 Mock/小预算；如变慢，按 case 分组但仍默认全跑。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | T6 实施 | `uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py tests/eval/test_no_case_overfit.py -q` | PASS | 49 passed |
| 2026-10-22 | T6 实施 | `uv run pytest -q` | PASS | 374 passed, 2 skipped（仅 live 测试跳过） |
| 2026-10-22 | T6 实施 | `uv run ruff check .` | PASS | All checks passed |
| 2026-10-22 | T6 实施 | `uv run mypy src` | PASS | 48 source files |
| 2026-10-22 | T7 回归 | 最终全量 `uv run pytest -q` | PASS | 385 passed, 6 skipped；live opt-in |
| 2026-10-22 | T7 回归 | 多绑定/修订回归 | PASS | 共享事实/评估修订未改变三 case 离线指标 |

### 6.1 三 case 指标

| 指标 | 目标 | 实际 |
|---|---|---|
| Top-1 正确 | 3/3 | 3/3 |
| Top-3 含正确原因 | 3/3 | 3/3 |
| 已评估同线程上下文 | 3/3 | 3/3 |
| 已评估代码/工具证据 | 3/3 | 3/3 |
| requirements 全覆盖 | 3/3 | 3/3 |
| 引用有效 | 100% | 18/18 |
| remediation 接地 | 100% | 6/6 |
| DB 越权 | 0 | 0 |
| schema 0.3 + fixture 标注 | 3/3 | 3/3 |

每个 case 均走完 4 次 LLM 调用、11 次工具调用、5 次 assessment、3 个假设（1 confirmed + 2 contradicted）、2 条 remediation action（code + test）；报告 sources 6 条且全部 verified，所有 validation flag 为 true。

### 6.2 负向与安全覆盖

- 未接地假设、伪造 evidence ID/source_ref、未绑定证据 assessment、无证据 remediation 均被拒绝。
- 开放替代假设、单假设运行均不得 confirmed。
- 未知表/未知列/非法表名、未知写工具/shell 工具均拒绝；DB 仅 `db.get_row` / `db.describe_table`。
- 恶意日志与 DB 行内容不进入报告、不改变工具策略与确认结果。
- 缺 `logs.get_thread_context` 或使用跨线程上下文时触发 `missing_thread_context` repair，且不 confirmed。
- `test_no_case_overfit.py` 扫描 diagnosis/tools/indexing/log_analysis/verification，未发现 case ID、fixture 路径或期望答案。

### 6.3 备注

- 三份 Mock 脚本是测试编排，不代表 live LLM 的规划能力；真实模型结构验证在 T7。
- `pyyaml` 已作为 dev 依赖加入，仅用于测试读取 expected YAML，runtime 不依赖。
- 三 case 日志逐字节一致，根因差异只来自仓库变体与 fixture 数据。
