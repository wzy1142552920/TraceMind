# TraceMind

**本地优先、证据驱动的 Java 故障诊断 Agent（v0.4 JVM 深度诊断）。**

TraceMind 读取一份用户提供的 Java 日志、本地源码，以及可选的 JVM 文本快照（jstack、`top -H`/`ps -L`、GC 日志、`jmap -histo`）。LLM 提出多个候选原因、按需调用只读代码/JVM 工具，确定性 Evaluator 根据真实证据判定状态，最后输出带证据引用的结构化修复建议。

LLM 负责提出假设、规划调查、解释真实证据和生成修复建议；预算、工具权限、证据状态、确认门槛和引用校验由确定性代码负责。

> 项目定位：面向 **AI Agent（主）+ Java** 方向的工程作品。用 Python 构建 Agent，用 Java/Spring 真实源码、日志、JVM 快照和故障模式作为诊断领域。

## 诊断流程

```text
用户提供的日志文件 + 本地源码 + 可选 JVM 文本快照目录
  -> 解析异常/堆栈，选择 primary anomaly
  -> 提取相同线程号的上下文，重建业务步骤
  -> 校验 manifest，加载并解析用户提供的 JVM 快照
  -> LLM 基于日志/代码/artifact 元数据提出至少两个候选原因
  -> 绑定 hypothesis + requirement 调用只读工具
       -> 代码流：符号、调用边、注解 SQL、源码范围
       -> JVM：热点线程、线程转储/死锁、GC 摘要/事件、堆直方图
       -> 数据验证：db.describe_table / db.get_row（Fake backend）
  -> LLM 逐条评估真实证据，确定性 Evaluator 更新状态
  -> confirmed 需要 symptom + mechanism、工具证据、全部 requirements、
     至少一个 discriminating requirement、无 refute，且所有替代被反驳
  -> LLM 生成结构化 remediation plan
  -> 引用/证据/接地/artifact 标注校验 -> 报告 schema 0.4
```

v0.1 完成可离线复现的最小循环；v0.2 接入真实 DeepSeek 并补齐配置、重试、usage/latency 和有界计划修复；v0.3 升级为**多假设鉴别诊断 + 代码/日志互证 + 只读数据验证 + 结构化修复**；v0.4 把**用户提供的 JVM 文本快照**纳入证据协议，覆盖 CPU 高与内存高/OOM。

## v0.4 新增

- **JVM 快照输入**：`--artifacts DIR` + 固定 `manifest.json`，支持 `thread_dump`、`thread_cpu`、`gc_log`、`heap_histogram`。
- **安全加载**：路径穿越/symlink/绝对路径/service 不匹配/超大/畸形/非 UTF-8 全部拒绝；只读、有界、脱敏。
- **四类文本解析器**：兼容 JDK 8/11/17 常见 jstack、`top -H`/`ps -L`、JDK 8/9+ GC 日志和 `jmap -histo[:live]`，行号可追溯、未知行只告警。
- **六个只读 JVM 工具**：`jvm.get_thread_dump`、`get_hot_threads`、`get_deadlocks`、`get_gc_summary`、`get_gc_events`、`get_heap_histogram`，只在对应快照存在时注册。
- **新的证据语义**：`THREAD_DUMP`、`THREAD_CPU`、`GC_EVENT`、`GC_SUMMARY`、`HEAP_SUMMARY`；provenance 为 `user_artifact`，引用为 `artifact://<id>#Lx-Ly`。
- **symptom / mechanism 覆盖**：快照可满足 symptom；代码/SQL/配置/DB schema 才能满足 mechanism。只有 JVM 快照、没有代码机制时最多 `supported`，不能 `confirmed`。
- **条件放宽同线程规则**：提供 JVM artifacts 时，同线程日志上下文可选；没有 artifacts 时保持 v0.3 强制规则。
- **报告 schema 0.4**：`artifacts[]`、artifact 引用校验、快照限制；不出现绝对路径、完整 dump 或秘密。
- **两个新 case**：`v04-j1-cpu-high`、`v04-j2-memory-oom`，离线 mock 确定性评测 + opt-in live 验证。

## 两个 JVM case

| Case | 日志症状 | 关键快照 | 真实原因 | 被排除的替代假设 |
|---|---|---|---|---|
| `v04-j1-cpu-high` | 报价请求 2215ms 超时 | 线程转储、线程 CPU、正常 GC 日志 | `PricingService.recalculate` 中的热点计算循环；`pricing-exec-1` 持续 RUNNABLE 高 CPU | GC 压力（无 Full GC、停顿 <10ms）；锁竞争/死锁（请求线程 WAITING、无死锁） |
| `v04-j2-memory-oom` | `OutOfMemoryError: Java heap space` | 多次 Full GC 日志、live 堆直方图 | `ReportCache` 静态 `ConcurrentHashMap` 无界增长，无淘汰/TTL | 堆配置过小（Full GC 后仍不回落）；单次超大对象（直方图由大量 `ReportEntry` 主导） |

两个 case 的日志、仓库、快照、mock 和 expected 均为合成 fixture；expected 只被测试读取，不进入 runtime prompt。CPU case 的日志线程与热点线程刻意不同，用于验证 artifact 场景下同线程规则的条件放宽。

v0.3 的三个数据状态 case（缺失行、重复回调、Mapper stub）继续保留并回归：

| Case | 仓库 | Fixture DB | 真实原因 |
|---|---|---|---|
| `v03-c1-missing-row` | `minimal-order-service-fixed` | `orders id=10086` 不存在 | 目标订单行缺失，UPDATE 匹配 0 行 |
| `v03-c2-duplicate-callback` | `minimal-order-service-fixed` | `orders id=10086` 状态为 `PAID` | 重复 PAID 回调被 SQL guard 变成 0 行 |
| `v03-c3-mapper-stub` | `minimal-order-service` | `orders id=10086` 状态为 `PENDING` | Mapper `default` 方法体 `return 0;`，注解 SQL 未执行 |

## 快速开始

要求：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync
uv run tracemind --help
uv run tracemind --version   # tracemind 0.4.0
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

基础 v0.1 demo：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

v0.4 CPU 高 case（真实解析快照、真实调用 JVM 工具，仅 LLM 由脚本模拟）：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v04-j1-cpu-high/incident.log \
  --repo fixtures/repos/v04-jvm-hot-loop \
  --artifacts fixtures/artifacts/v04-j1-cpu-high \
  --mock-script fixtures/mock/v04-j1-cpu-high.json \
  --service order-service \
  --provider mock
```

v0.4 OOM case：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v04-j2-memory-oom/incident.log \
  --repo fixtures/repos/v04-jvm-unbounded-cache \
  --artifacts fixtures/artifacts/v04-j2-memory-oom \
  --mock-script fixtures/mock/v04-j2-memory-oom.json \
  --service order-service \
  --provider mock
```

v0.3 带 Fixture 数据库验证的 case：

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
  --log fixtures/logs/v04-j1-cpu-high/incident.log \
  --repo fixtures/repos/v04-jvm-hot-loop \
  --artifacts fixtures/artifacts/v04-j1-cpu-high \
  --service order-service \
  --provider deepseek \
  --output-dir /tmp/tracemind-v04-live \
  --max-iterations 18 --max-tool-calls 28 --llm-max-tokens 2200
```

说明：

- `--max-llm-calls` 不在 CLI 暴露，运行时使用 `max_iterations + 2`，为最终 remediation 留出调用。
- 真实输出具有非确定性，合法工具路径可能不同；成功标准是结构、证据和引用校验，而不是唯一措辞。
- 没有配置 Key 时，命令在日志解析、仓库索引和创建输出目录之前退出 `2`。
- JVM 快照始终标注为用户提供的时间点数据；CLI 不会执行 `jstack`/`jcmd`/`jmap`/`top`，也不会 attach JVM。

### Live 测试（opt-in）

live 测试需要 `--run-live`、`TRACEMIND_LIVE_TESTS=1` 和非空 Key（环境变量或 `.env`）三者同时满足：

```bash
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v04_cases.py -q -s
```

v0.3 live case 仍可单独运行：

```bash
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q -s
```

默认 `uv run pytest` 跳过 live 测试，不访问网络、不产生费用。未满足 gate 时 live 验收只能标记 `BLOCKED`，不能写成通过。

## CLI

| 参数 | 说明 |
|---|---|
| `--log PATH` | 用户提供的日志文件（必填） |
| `--repo PATH` | 本地 Java 仓库根目录（必填） |
| `--artifacts PATH` | JVM 文本快照目录，含 `manifest.json`；缺省时不注册 JVM 工具 |
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
| `2` | CLI 用法、provider 配置、Key 或 artifact 校验错误 |
| `3` | 证据不足（`insufficient_data`） |
| `4` | 预算耗尽 |

退出码 `0` 只表示报告成功生成，不代表“根因绝对正确”。

## 运行产物

```text
.tracemind/runs/<run_id>/
  run.json        # schema 0.4：provider/model/state/stop/budget/log/repo/index + LLM 配置/usage/逐次调用
  events.jsonl    # 状态转换、LLM、工具、证据、评估、修复、停止事件
  audit.jsonl     # 工具调用、参数 hash、结果、耗时
  report.md       # Jinja2 模板渲染的人类可读报告
  report.json     # report schema 0.4，含 artifacts[]/limitations/validation
```

报告引用会被校验：

- `repo://<relative_path>#Lx-Ly`
- `log://<event_id>` 或 `log://<log_file>#thread=<thread>&Lx-Ly`
- `db://<table>/<key>=<value>`
- `artifact://<artifact_id>#Lx-Ly`（单点 `#Lx` 等价；越界/未知 id 校验失败）

校验失败会降级诊断状态或丢弃未接地修复建议，不会伪造 `confirmed`。

## 结论如何被确认

必须同时满足：

1. 至少两个 grounded hypotheses，且只有一个 qualifies。
2. 每个 requirement 由已绑定该 hypothesis/requirement 的真实证据支持。
3. 至少一个 discriminating requirement 被满足，且没有 refuting 证据。
4. 支持证据中至少一项来自工具结果。
5. 至少一个 symptom kind 和至少一个 mechanism kind；JVM 快照属于 symptom，代码/SQL/配置/DB schema 属于 mechanism。
6. 提供 JVM artifacts 时同线程上下文可选；未提供 artifacts 且主事件有线程号时，必须有一条已评估的同线程上下文。
7. 所有替代假设均为 `contradicted`。

LLM 只能提交 assessment（supports/refutes/neutral），不能设置 status、创建证据或修改 evidence ledger。重新评估同一证据会修订此前判断，而不是产生重复证据。

## 可靠性与安全边界

- **只读**：没有 shell、写数据库、文件写入、JVM attach 或自动修复工具；remediation 只展示，不生成 diff/补丁。
- **只接受文本快照**：只解析用户提供的 jstack、线程 CPU、GC 日志和堆直方图；不运行采集命令，不解析 `.hprof`/JFR。
- **有界**：迭代、LLM、工具、假设、requirement、assessment、remediation 数量均有上限；artifact 文件/行数、线程、帧、事件、类、工具输出全部截断。
- **快照标注**：JVM 证据 provenance 为 `user_artifact`，artifact 标记 `source_environment=user_provided`；报告明确不是 live attach/采集。
- **Fake 验证标注**：使用 `--verification-data` 时 `verification.environment=fixture`、`backend=fake`，note 明确不是生产 DB 验证。
- **Secret 安全**：Key 只从 env/.env 读取；live 测试扫描 run 产物，确认不含 Key 或 `sk-` 前缀。
- **日志/代码/快照即不可信输入**：其中的内容只作为数据，不作为指令。

## 评估与验收

当前 checkout 的验证结果（2026-10-23）：

| 检查 | 结果 |
|---|---|
| 默认离线测试 | **571 passed, 9 skipped**（live 测试跳过，不访问网络） |
| `ruff check .` | 通过 |
| `mypy src` | 通过（59 个源文件） |
| v0.4 离线两 case | 报告结构 2/2、Top-1 2/2、artifact 引用/标注/接地 100%、无越权工具 |
| v0.3 eval 回归 | **29 passed**（三 case + 负向） |
| v0.4 live DeepSeek 两 case | **2/2 confirmed**；Top-1 2/2、Top-3 2/2 |
| v0.4 live CLI 冒烟（CPU） | 退出码 0，5 类产物，schema 0.4，3 artifacts，JVM 证据 5，remediation 3 条，无 secret |
| 版本 | `tracemind 0.4.0` |

最近一次 v0.4 live 记录（`deepseek-flash`，预算 18 iterations / 20 LLM calls / 28 tool calls / 2200 output tokens）：

| Case | 报告状态 | Top-1 | Top-3 | LLM calls | Tools | Total tokens | Latency |
|---|---|---|---|---|---|---|---|
| `v04-j1-cpu-high` | confirmed | hit | hit | 6 | 9 | 38,430 | 16.7s |
| `v04-j2-memory-oom` | confirmed | hit | hit | 7 | 12 | 38,478 | 22.6s |

live 结果依赖 DeepSeek 模型版本、网络和 Key；它验证的是端到端可行性和证据链，不代表生产准确率或统计显著性。调试过程中 CPU case 曾出现 `insufficient_data`：模型把日志线程当作热点线程，且首轮候选遗漏 CPU-bound 机制。据此补充了通用 JVM 提示（请求线程不一定等于热点线程、首轮覆盖 artifact 蕴含的鉴别方向、日志上下文必须通过工具绑定），未加入 case 名称或答案；修正后最新一次 live 两 case 均通过。live 仍是非确定性单次结果。

详细记录：

- [v0.4 验收矩阵](specs/004-jvm-diagnosis/ACCEPTANCE.md)
- [v0.4 设计](specs/004-jvm-diagnosis/DESIGN.md)
- [v0.3 验收矩阵](specs/003-grounded-diagnosis/ACCEPTANCE.md)
- [v0.2 验收矩阵](specs/002-live-deepseek/ACCEPTANCE.md)
- [v0.1 验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)

## 已知限制

- 只分析**用户提供的日志文件 + 本地源码 + 可选 JVM 文本快照**；不做持续监听、日志采集、告警平台接入或 JVM attach。
- 不解析 `.hprof`、JFR、async-profiler 输出；没有堆支配树、分配采样或 Native 内存分析。
- CPU/内存结论受快照时点限制；单个快照不能证明泄漏。线程 CPU 与线程转储的关联依赖 TID/nid，匹配失败会给出 warning，不会伪造映射。
- 不接 MCP/真实 MySQL/Redis；数据库验证使用 Fixture + Fake backend 时，`confirmed` 仅对 fixture 数据成立（JVM case 不使用 DB 验证）。
- 代码流是 tree-sitter 启发式候选边，不是运行时调用图；不解析 MyBatis XML、不做完整类型解析。
- 无 catalog/skill；根因覆盖能力依赖模型自主规划。后续根据实际运行记录决定是否增加 catalog 或 skills。
- 修复建议只展示，不自动应用；不生成可执行补丁。
- 两个 JVM case 和 v0.3 三 case 都是合成 fixture，不代表生产准确率。
- live 受外部模型/网络影响，具有非确定性；默认离线测试不访问网络。

## 架构

```text
CLI (Typer)
  -> LogParser (文本日志 + Java 堆栈)
  -> ThreadContext (同线程有序日志)
  -> ArtifactLoader/Parsers (manifest + JVM 文本快照)
  -> TreeSitterJavaIndex (类/方法/注解/调用点/SQL/源码范围)
  -> DiagnosisRuntime (确定性状态机/预算/停止/修复)
       -> LLM Provider (Mock / DeepSeek)
       -> ToolExecutor (参数校验/路径安全/去重/输出限制/审计)
       -> Code/Log/DB/JVM Tools (JVM 工具按 artifact 条件注册)
       -> Evidence Ledger + Assessments
       -> Deterministic Evaluator (symptom + mechanism)
       -> Remediation Validator
       -> Report 0.4 (Jinja2) + RunStore
```

核心目录：

```text
src/tracemind/
  cli/            # 命令入口
  core/           # 领域模型与错误
  log_analysis/   # 日志/堆栈/同线程上下文
  indexing/       # tree-sitter Java 索引
  artifacts/      # manifest、加载、脱敏、JVM 文本解析器
  tools/          # ToolSpec/Registry/Executor + 日志/代码/DB/JVM 工具
  llm/            # Provider 抽象、配置、Mock、DeepSeek
  diagnosis/      # Runtime/Evidence/Evaluator/Remediation/Report
  verification/   # 只读验证后端与 Fixture 加载
  storage/        # RunStore
  observability/  # 事件 JSONL
```

## Agent 设计取舍

- **自研薄运行时**：状态机、预算、证据门槛和停止条件由确定性代码控制；不引入 LangGraph/PydanticAI。
- **LLM 不确认根因**：LLM 提出假设、规划工具和解释证据；Evaluator 决定状态。
- **无 catalog**：case 的期望答案不进入 runtime；用通用协议和证据约束引导模型。
- **日志与代码互证**：同线程上下文用于重建业务步骤，代码流用于确认实际执行路径；artifact 场景下快照与代码机制仍然必须互证。
- **快照不是实时观测**：JVM 工具只查询用户提供的文本文件，不能 attach、执行命令或读取 manifest 之外的路径。
- **同线程规则条件放宽**：只有提供 artifacts 时才允许跨线程 CPU/GC 证据；无 artifacts 的 v0.3 行为不变。
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
- jstack 线程状态/栈/锁与死锁段解析
- `top -H`/`ps -L` 热点线程与 nid/TID 映射
- JDK 8/9+ GC 日志的 Young/Full、heap、pause 解析
- `jmap -histo[:live]` 类/实例/字节统计
- CPU 高与内存高/OOM 的 symptom + mechanism 鉴别
- 结构化修复建议（code/test/ops/data），带证据绑定
