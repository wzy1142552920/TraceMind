# TraceMind

**本地优先、证据驱动的 Java 故障诊断 Agent（v0.3 自主鉴别诊断）。**

TraceMind 读取一份用户提供的 Java 应用日志和本地源码，解析异常与同线程上下文，由一个受控 Agent 运行时提出多个候选原因、按需调用代码流和只读数据验证工具，最后由确定性 Evaluator 判定结论，并输出带证据引用的结构化修复建议。

LLM 负责提出假设、规划调查、解释真实证据和生成修复建议；预算、工具权限、证据状态、确认门槛和引用校验由确定性代码负责。

> 项目定位：面向 **AI Agent（主）+ Java** 方向的工程作品。用 Python 构建 Agent，用 Java/Spring 真实源码、日志和故障模式作为诊断领域。

## 诊断流程

```text
用户提供的日志文件
  -> 解析异常/堆栈，选择 primary anomaly
  -> 提取相同线程号的上下文，重建业务步骤
  -> LLM 基于日志/代码证据提出至少两个候选原因
  -> 绑定 hypothesis + requirement 调用只读工具
       -> 代码流：符号、调用边、注解 SQL、源码范围
       -> 数据验证：db.describe_table / db.get_row（Fake backend）
  -> LLM 逐条评估真实证据，确定性 Evaluator 更新状态
  -> confirmed 需要一个假设满足全部 requirements，且所有替代被反驳
  -> LLM 生成结构化 remediation plan
  -> 引用/证据/接地/fixture 标注校验 -> 报告 schema 0.3
```

v0.1 完成可离线复现的最小循环；v0.2 接入真实 DeepSeek 并补齐配置、重试、usage/latency 和有界计划修复；v0.3 升级为**多假设鉴别诊断 + 代码/日志互证 + 只读数据验证 + 结构化修复**。

## v0.3 新增

- **鉴别诊断**：至少两个 grounded hypotheses；LLM 不能直接确认，状态由 Evaluator 根据 requirements、supports/refutes、替代假设和证据来源判定。
- **同线程日志上下文**：异常分析不只看堆栈；从用户日志中提取相同线程号的有序事件，并与代码流程互相印证。
- **代码流工具**：`code.get_symbol/get_callers/get_callees/find_source_range/find_sql`；支持 Mapper 注解 SQL、default 方法体、重载候选。
- **只读数据验证契约**：`--verification-data` 加载 Fixture，经 `FakeVerificationBackend` 提供 `db.describe_table/get_row`；只读、主键单行、表/列白名单、敏感列脱敏。
- **结构化修复方案**：只针对 supported/confirmed 假设；每条 action 绑定证据、目标、风险和验证步骤；不生成补丁、不执行修改。
- **证据多绑定**：一个真实工具事实可同时满足多个 hypothesis/requirement；历史事实可复用，不重复调用工具。
- **可修订评估**：后续事实可重新评估同一证据并覆盖此前 neutral/supports/refutes 判断。
- **报告 schema 0.3**：`hypotheses` + `remediation_plan` + `verification` + `sources` + `validation`。

## 三个诊断 case

三个 case 使用**相同日志症状**（`updateStatus returned rows=0`），但真实原因不同：

| Case | 仓库 | Fixture DB | 真实原因 |
|---|---|---|---|
| `v03-c1-missing-row` | `minimal-order-service-fixed` | `orders id=10086` 不存在 | 目标订单行缺失，UPDATE 匹配 0 行 |
| `v03-c2-duplicate-callback` | `minimal-order-service-fixed` | `orders id=10086` 状态为 `PAID` | 重复 PAID 回调被 `status <> #{status}` SQL guard 变成 0 行 |
| `v03-c3-mapper-stub` | `minimal-order-service` | `orders id=10086` 状态为 `PENDING` | Mapper `default` 方法体 `return 0;`，注解 SQL 未执行 |

三个 case 的日志内容完全相同；仓库差异只在 Mapper / 服务实现，期望答案只存在于测试数据，不进入 runtime prompt 或运行时规则。

## 快速开始

要求：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync
uv run tracemind --help
uv run tracemind --version   # tracemind 0.3.0
```

## 配置（仅 live DeepSeek 需要）

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY；不要提交 .env
```

`.env` 从**当前工作目录**向上查找，建议在项目根目录执行命令。优先级：

```text
CLI 参数 > 真实环境变量 > 项目根 .env > 默认值
```

| 配置 | CLI | 环境变量 | 默认 |
|---|---|---|---|
| 模型 | `--model` | `TRACEMIND_LLM_MODEL` | `deepseek-flash` |
| Base URL | `--base-url` | `TRACEMIND_LLM_BASE_URL` | `https://api.deepseek.com` |
| 超时（秒） | `--llm-timeout` | `TRACEMIND_LLM_TIMEOUT` | `60` |
| 最大输出 tokens | `--llm-max-tokens` | `TRACEMIND_LLM_MAX_TOKENS` | `4000` |
| 传输重试次数 | `--llm-max-retries` | `TRACEMIND_LLM_MAX_RETRIES` | `2` |
| 计划修复次数 | `--max-repair-attempts` | `TRACEMIND_MAX_REPAIR_ATTEMPTS` | `2` |

不提供 `--api-key`；Key 只从环境变量或 `.env` 读取，且不会写入 run 产物、事件、报告、审计或普通日志。

## 离线 Demo（Mock）

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

默认使用 `fixtures/mock/basic_plan.json`，不访问网络、不需要 API Key。

带 Fixture 数据库验证的 v0.3 case：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v03-c1-missing-row/incident.log \
  --repo fixtures/repos/minimal-order-service-fixed \
  --verification-data fixtures/verification/v03-c1-missing-row.json \
  --service order-service \
  --provider mock
```

运行产物默认写入 `.tracemind/runs/<run_id>/`。`--json` 输出机器可读摘要。

## 真实 DeepSeek

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v03-c1-missing-row/incident.log \
  --repo fixtures/repos/minimal-order-service-fixed \
  --verification-data fixtures/verification/v03-c1-missing-row.json \
  --service order-service \
  --provider deepseek \
  --output-dir /tmp/tracemind-v03-live \
  --max-iterations 14 --max-tool-calls 24 --llm-max-tokens 2000
```

说明：

- `--max-llm-calls` 不在 CLI 暴露，运行时使用 `max_iterations + 2`，为最终 remediation 留出调用。
- 真实输出具有非确定性，合法工具路径可能不同；成功标准是结构、证据和引用校验，而不是唯一措辞。
- 没有配置 Key 时，命令在日志解析、仓库索引和创建输出目录之前退出 `2`。

### Live 测试（opt-in）

live 测试需要 `--run-live`、`TRACEMIND_LIVE_TESTS=1` 和非空 Key（环境变量或 `.env`）三者同时满足：

```bash
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q -s
```

默认 `uv run pytest` 跳过 live 测试，不访问网络、不产生费用。未满足 gate 时 live 验收只能标记 `BLOCKED`，不能写成通过。

## CLI

| 参数 | 说明 |
|---|---|
| `--log PATH` | 用户提供的日志文件（必填） |
| `--repo PATH` | 本地 Java 仓库根目录（必填） |
| `--verification-data PATH` | v0.3 Fixture 验证数据；缺省时不注册 DB 工具 |
| `--service NAME` | 服务名（必填） |
| `--provider mock\|deepseek` | Provider，默认 `mock` |
| `--mock-script PATH` | Mock 响应脚本 |
| `--output-dir PATH` | 运行产物目录，默认 `.tracemind/runs` |
| `--max-iterations N` | 最大规划轮数，默认 `10` |
| `--max-tool-calls N` | 最大工具调用数，默认 `16` |
| `--model NAME` | 模型覆盖 |
| `--base-url URL` | OpenAI 兼容 Base URL 覆盖 |
| `--llm-timeout SECONDS` | 单次 LLM 请求超时 |
| `--llm-max-retries N` | 传输重试次数（0–2） |
| `--llm-max-tokens N` | 最大输出 tokens |
| `--max-repair-attempts N` | 计划修复次数（0–5） |
| `--json` | 输出机器可读摘要 |
| `--version` | 显示版本 |

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 报告生成且状态为 `confirmed` / `probable` |
| `1` | 运行时/IO/Provider 错误 |
| `2` | CLI 用法、provider 配置或 Key 错误 |
| `3` | 证据不足（`insufficient_data`） |
| `4` | 预算耗尽 |

退出码 `0` 只表示报告成功生成，不代表“根因绝对正确”。

## 运行产物

```text
.tracemind/runs/<run_id>/
  run.json        # schema 0.3：provider/model/state/stop/budget/log/repo/index + LLM 配置/usage/逐次调用
  events.jsonl    # 状态转换、LLM、工具、证据、评估、修复、停止事件
  audit.jsonl     # 工具调用、参数 hash、结果、耗时
  report.md       # Jinja2 模板渲染的人类可读报告
  report.json     # report schema 0.3
```

报告引用会被校验：

- `repo://<relative_path>#Lx-Ly`
- `log://<event_id>` 或 `log://<log_file>#thread=<thread>&Lx-Ly`
- `db://<table>/<key>=<value>`

校验失败会降级诊断状态或丢弃未接地修复建议，不会伪造 `confirmed`。

## 结论如何被确认

必须同时满足：

1. 至少两个 grounded hypotheses，且只有一个 qualifies。
2. 每个 requirement 由已绑定该 hypothesis/requirement 的真实证据支持。
3. 至少一个 discriminating requirement 被满足，且没有 refuting 证据。
4. 支持证据中至少一项来自工具结果。
5. 覆盖日志、代码、工具结果三类来源。
6. 主事件有线程号时，必须有一条已评估的同线程上下文。
7. 所有替代假设均为 `contradicted`。

LLM 只能提交 assessment（supports/refutes/neutral），不能设置 status、创建证据或修改 evidence ledger。重新评估同一证据会修订此前判断，而不是产生重复评估。

## 可靠性与安全边界

- **只读**：没有 shell、写数据库、文件写入或自动修复工具；remediation 只展示，不生成 diff/补丁。
- **有界**：迭代、LLM、工具、假设、requirement、assessment、remediation 数量均有上限；输出截断。
- **Fake 验证标注**：`verification.environment=fixture`、`backend=fake`，note 明确说明不是生产 DB 验证；报告和证据不会冒充生产结果。
- **Secret 安全**：live 测试扫描 run 产物，确认不包含 Key 或 `sk-` 前缀。
- **日志即不可信输入**：日志/代码/SQL/DB 内容只作为数据，不作为指令。

## 评估与验收

当前 checkout 的验证结果（2026-10-22）：

| 检查 | 结果 |
|---|---|
| 默认离线测试 | **385 passed, 6 skipped**（live 测试跳过，不访问网络） |
| `ruff check .` | 通过 |
| `mypy src` | 通过（48 个源文件） |
| v0.3 离线三 case | 报告结构 3/3、requirements 覆盖 3/3、引用/接地/fixture 标注 100% |
| v0.3 live DeepSeek 三 case | **3/3 confirmed**；Top-1 3/3、Top-3 3/3；同线程上下文与代码证据 3/3 |
| Live CLI 冒烟 | 退出码 0，5 类产物，schema 0.3，remediation 3 条，产物无 secret |
| 版本 | `tracemind 0.3.0` |

最近一次 live gate 实际记录（`deepseek-flash`）：

| Case | 报告状态 | Top-1 | Top-3 | LLM calls | Tools | Total tokens | Latency |
|---|---|---|---|---|---|---|---|
| `v03-c1-missing-row` | confirmed | hit | hit | 11 | 15 | 74,918 | 23.8s |
| `v03-c2-duplicate-callback` | confirmed | hit | hit | 7 | 11 | 41,548 | 17.6s |
| `v03-c3-mapper-stub` | confirmed | hit | hit | 11 | 17 | 71,296 | 23.8s |

live 结果依赖 DeepSeek 模型版本、网络和 Key；它验证的是端到端可行性和证据链，不代表生产准确率或统计显著性。

详细记录：

- [v0.3 验收矩阵](specs/003-grounded-diagnosis/ACCEPTANCE.md)
- [v0.3 设计](specs/003-grounded-diagnosis/DESIGN.md)
- [v0.2 验收矩阵](specs/002-live-deepseek/ACCEPTANCE.md)
- [v0.1 验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)

## 已知限制

- v0.3 只分析**用户提供的日志文件**；不做持续监听、日志采集、告警平台接入。同线程上下文仅限该文件内事件。
- 数据库验证使用 Fixture + Fake backend；**不是生产数据库验证**，`confirmed` 仅对 fixture 数据成立。
- 代码流是 tree-sitter 启发式候选边，不是运行时调用图；不解析 MyBatis XML、不做完整类型解析。
- 无 catalog/skill；根因覆盖能力依赖模型自主规划。后续根据实际运行记录决定是否增加 catalog 或 skills。
- 修复建议只展示，不自动应用；不生成可执行补丁。
- 三 case 是合成 fixture，不代表生产准确率。

## 架构

```text
CLI (Typer)
  -> LogParser (文本日志 + Java 堆栈)
  -> ThreadContext (同线程有序日志)
  -> TreeSitterJavaIndex (类/方法/注解/调用点/SQL/源码范围)
  -> DiagnosisRuntime (确定性状态机/预算/停止/修复)
       -> LLM Provider (Mock / DeepSeek)
       -> ToolExecutor (参数校验/路径安全/去重/输出限制/审计)
       -> Evidence Ledger + Assessments
       -> Deterministic Evaluator
       -> Remediation Validator
       -> Report 0.3 (Jinja2) + RunStore
```

核心目录：

```text
src/tracemind/
  cli/            # 命令入口
  core/           # 领域模型与错误
  log_analysis/   # 日志/堆栈/同线程上下文
  indexing/       # tree-sitter Java 索引
  tools/          # ToolSpec/Registry/Executor + 日志/代码/DB 工具
  llm/            # Provider 抽象、配置、Mock、DeepSeek
  diagnosis/      # Runtime/Evidence/Evaluator/Remediation/Report
  verification/   # 只读验证后端与 Fixture 加载
  storage/        # RunStore
  observability/  # 事件 JSONL
```

## Agent 设计取舍

- **自研薄运行时**：状态机、预算、证据门槛和停止条件由确定性代码控制；不引入 LangGraph/PydanticAI。
- **LLM 不确认根因**：LLM 提出假设、规划工具和解释证据；Evaluator 决定状态。
- **无 catalog**：三个 case 的期望答案不进入 runtime；用通用协议和证据约束引导模型。
- **日志与代码互证**：同线程上下文用于重建业务步骤，代码流用于确认实际执行路径，二者缺一不可。
- **DB 事实必须由工具验证**：依赖数据库数据/状态的假设需要 `db.get_row`，不能仅从日志或代码推断行状态。
- **证据多绑定与可修订评估**：一个真实事实可服务多个 requirement；新事实可修正此前判断。
- **Provider 中立**：DeepSeek 通过 OpenAI 兼容接口接入；Mock 用于确定性测试。

## Java 定位能力

当前 fixture 展示：

- 异常堆栈 → `OrderService.updateStatus` 源码位置
- 类/方法/重载/嵌套类索引
- `@Update` SQL 与表名提取
- 同线程日志上下文与跨线程噪声隔离
- Mapper `default` 方法体检查
- Fixture 数据库按主键单行验证
- 结构化修复建议（code/test/ops/data），带证据绑定
