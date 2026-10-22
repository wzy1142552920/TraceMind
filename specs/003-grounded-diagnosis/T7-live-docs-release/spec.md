# T7 — Live 验证、文档与发布 Spec

- **任务 ID**：T7
- **状态**：planned
- **依赖**：T6
- **下游**：无
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T6 用 Mock 脚本证明运行时和协议，但不能证明真实 DeepSeek 能在无 catalog 的情况下自主完成“多假设 → 代码流 → 只读验证 → 修复建议”。T7 用 opt-in live 测试验证真实模型，并把 v0.3 的能力、限制、命令和验收结果写清楚。

**用户故事**：作为项目作者，我可以显式打开 live gate，让真实 DeepSeek 跑三个 case，得到 schema 0.3 报告；我能看到 Top-1/同线程上下文/代码证据/接地结果，未达标时文档如实记录，而不是把 Mock 结果当成 live 结果。

## 2. In scope

- opt-in live 测试：
  - 三 case 真实 DeepSeek 运行。
  - 断言 schema 0.3、引用、证据来源、同线程上下文与代码证据、requirements 覆盖、remediation 接地、fixture 标注、无 secret。
  - 目标：报告结构 3/3；同线程上下文 3/3；代码证据 3/3；Top-1 ≥ 2/3；Top-3 3/3。
- 至少一个 live CLI 冒烟（生成产物、终端/JSON 摘要）。
- 有界 prompt/repair 调优：只修复协议/格式/上下文问题，不针对 case 硬编码答案。
- README v0.3 更新：
  - 新能力（含同线程日志上下文 + 代码流协同）、三个 case、Fake 验证边界、命令、限制、测试统计。
- SDD 文档回填：README/ACCEPTANCE/T1–T7 状态与验证结果。
- 版本 `0.3.0`：`pyproject.toml`、`__init__.py`、锁文件同步。
- 链接检查、secret scan、未修改 001/002/docs 设计文档。

## 3. Out of scope

- 真实 MySQL/Redis/MCP、审批 UI。
- catalog/skill、LLM-only ablation。
- 自动修复/diff/执行。
- Web UI/OTel/SQLite。
- 统计意义上的准确率或生产验证。
- 修改 v2 设计文档或旧版本 SDD。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T7-01 | live gate 沿用 `--run-live` + `TRACEMIND_LIVE_TESTS=1` + Key | must |
| FR-T7-02 | 三 case live 测试，默认 skip、不访问网络 | must |
| FR-T7-03 | live 断言 schema 0.3/证据/引用/接地/fixture 标注 | must |
| FR-T7-04 | live Top-1 ≥2/3、Top-3 3/3；未达标如实记录 | must |
| FR-T7-05 | 至少一个 live CLI 冒烟，产物无 secret | must |
| FR-T7-06 | prompt/repair 只做通用修复，不硬编码 case 答案 | must |
| FR-T7-07 | README 更新 v0.3 能力/命令/限制/测试统计 | must |
| FR-T7-08 | ACCEPTANCE 和 T1–T7 验证结果回填 | must |
| FR-T7-09 | 版本升到 0.3.0，锁文件/CLI 版本一致 | must |
| FR-T7-10 | 链接有效；001/002/docs 设计文档未修改 | must |
| FR-T7-11 | live 结果依赖外部 Key/网络；无 Key 时 BLOCKED | must |
| FR-T7-12 | 报告/终端/产物无 Key/`sk-` | must |
| FR-T7-13 | live Top-1 同时具备同线程上下文与代码证据；无上下文时不得 confirmed | must |

## 5. 接口/数据契约

### 5.1 live gate

沿用 v0.2：

```bash
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q
```

- 需同时满足：`--run-live`、`TRACEMIND_LIVE_TESTS=1`、非空 `DEEPSEEK_API_KEY`（env 或 `.env`）。
- 默认 `uv run pytest` 跳过 live，不访问网络。
- 未满足 gate 时，AC 标 `BLOCKED`，不得写 PASS。

### 5.2 live 测试

新增 `tests/live/test_live_v03_cases.py`：

- 参数化三 case（可先跑 C1/C2/C3 全部；若成本过高，至少 C1+C2+C3 各一次）。
- 使用真实 `DeepSeekProvider`、Fake verification backend、较小预算：
  - `max_iterations=8`、`max_tool_calls=12`、`max_llm_calls=10`（均低于默认预算）。
  - `max_hypotheses=4`。
  - `llm_max_tokens` 控制成本。
- 断言：
  1. report schema 0.3。
  2. 报告状态 ∈ {confirmed, probable}；结构合法。
  3. 至少一个假设含预期证据来源（C1/C2 的 `db://orders/id=10086`；C3 的 `OrderMapper.java`）。
  4. Top-1 至少一条 satisfied requirement 使用 `log_thread_context`，source_ref 指向主事件线程，messages/claim 不含跨线程噪声。
  5. Top-1 至少一条 satisfied requirement 使用代码证据（`source_code`/`call_path`/`sql`）。
  6. requirements 覆盖达到预期；remediation action 有证据绑定。
  7. `verification.environment=fixture` 且 note 存在。
  8. validation 关键字段 true。
  9. 产物扫描无 Key/`sk-`。
- 若 Top-1 缺同线程上下文或代码证据，最多记为 probable，不得记为 confirmed。
- 不硬编码唯一自然语言句子；Top-1 用 expected 关键词（宽集合）或证据来源判定。
- 记录实际模型、usage、latency、stop reason。

### 5.3 live CLI 冒烟

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v03-c1-missing-row/incident.log \
  --repo fixtures/repos/minimal-order-service-fixed \
  --verification-data fixtures/verification/v03-c1-missing-row.json \
  --service order-service \
  --provider deepseek \
  --output-dir /tmp/tracemind-v03-live \
  --max-iterations 8 --max-tool-calls 12 --llm-max-tokens 1200
```

- 退出码 0（confirmed/probable）或 3/4，按实际结果记录。
- 生成 5 类产物；schema 0.3；fixture 标注；无 secret。

### 5.4 文档

README 增加/更新：

- v0.3 新增：自主鉴别诊断、同线程日志上下文分析、代码流工具、Fake 只读验证、结构化修复、报告 0.3。
- 说明日志上下文只取用户提供的日志文件中的同一线程事件；不做持续监听/采集。
- 三个 case 表格与运行命令。
- `--verification-data` 参数。
- Fake 验证边界：不是生产 DB 验证；confirmed 仅对 fixture 数据成立。
- 测试：默认离线；`tests/eval/...`；live 命令与 gate。
- 已知限制：只分析用户提供的日志文件（无持续监听/采集）、代码流启发式、无 catalog、无真实 DB、无自动修复。
- 验收统计与实际 live 结果。
- 文档链接：003 README/DESIGN/ACCEPTANCE/T1–T7。

### 5.5 发布

- `pyproject.toml` version `0.3.0`。
- `src/tracemind/__init__.py` `__version__ = "0.3.0"`。
- `uv lock` 同步（如有变化）。
- `uv run tracemind --version` → `tracemind 0.3.0`。
- 不修改 001/002 specs 和 docs 设计文档。
- 不提交 `.env`/Key/真实运行产物。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T7-01 | 默认 pytest 跳过 live，不访问网络 | 全量离线测试 |
| AC-T7-02 | live gate 三条件同时满足才运行 | conftest/gate 测试 |
| AC-T7-03 | 三 case live 报告结构 3/3 | live 测试 |
| AC-T7-04 | live Top-1 ≥2/3、Top-3 3/3 | live 断言/结果表 |
| AC-T7-05 | live 证据来源/接地/fixture 标注校验 | live 断言 |
| AC-T7-06 | live CLI 冒烟生成产物、无 secret | CLI E2E |
| AC-T7-07 | prompt/repair 无 case 硬编码 | 代码审查/overfit 扫描 |
| AC-T7-08 | README 记录 v0.3 能力/命令/限制 | 文档检查 |
| AC-T7-09 | ACCEPTANCE/T1–T7 回填，未达标如实记录 | 文档检查 |
| AC-T7-10 | 版本 0.3.0 一致 | `tracemind --version`/pyproject/lock |
| AC-T7-11 | 链接有效；旧 docs/specs 未修改 | 链接检查/git status |
| AC-T7-12 | 无 Key/`sk-` 泄露 | secret scan |
| AC-T7-13 | live Top-1 具备同线程上下文与代码证据；缺任一项不 confirmed | live 断言/结果表 |

## 7. 测试计划

### live

- 新增 `tests/live/test_live_v03_cases.py`（`@pytest.mark.live`）。
- 复用 `tests/conftest.py` 的 gate/fixtures。
- 必要时新增 live 辅助函数，但不改变默认测试行为。

### CLI

- `tests/e2e/test_live_preflight.py` 确认无 Key preflight 不变。
- live CLI 冒烟人工执行并记录。

### 文档/发布检查

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q
uv run tracemind --version
git status --short
```

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| live 非确定性 | 模型可能漏假设/漏绑定 | 有界 repair；如实记录；不伪造 PASS |
| 成本/延迟 | 多假设+多工具+修复 | 小预算/小 token；限制 case 数 |
| 模型版本变化 | 结果随版本变化 | 记录 model/usage；文档声明 |
| 过度调 prompt | 变成 case 特判 | 只修协议/格式；overfit 扫描；expected 不进 prompt |
| Fake 验证误读 | live 仍是 fixture 数据 | 报告/README 明确 environment=fixture |
| 漏用同线程上下文 | 模型只看栈/异常行 | prompt 规则 + 确认门槛 + live 断言；缺上下文不 confirmed |
| Secret 泄漏 | live 产物/日志 | secret scan；不打印 Key |
| 无 Key 环境 | CI/本地不可跑 | BLOCKED 标记；默认测试不受影响 |

**开放问题**

- live 是否必须三 case 全跑？目标是；若成本/稳定性不足，至少每 case 一次并记录。
- 是否保留 live 失败样本？可以保存脱敏报告摘要，不提交 Key/完整日志。
- 是否需要成本估算？v0.3 只记录 tokens/latency，不估算价格。

## 9. 验证命令

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q
uv run tracemind --version
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| — | 待实现后回填 | PLANNED |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-22 | 创建 T7 spec：live 三 case、CLI 冒烟、文档、验收回填与 0.3.0 发布 |
| 2026-10-22 | live/文档增加同线程上下文与代码证据断言；新增 AC-T7-13 |
