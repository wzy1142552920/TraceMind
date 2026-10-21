# TraceMind

**本地优先、证据驱动的 Java 故障定位 Agent（v0.1 最小循环）。**

TraceMind 读取一份 Java 应用日志和本地源码，解析异常堆栈、索引类/方法，由一个受控 Agent 运行时规划只读工具调用，收集证据，定位到源码行号，并输出带引用校验的 Markdown/JSON 诊断报告。

LLM 只负责规划、假设和解释；预算、工具权限、停止条件、证据状态和引用校验由确定性代码负责。

> 项目定位：面向 **AI Agent（主）+ Java** 方向的工程作品。用 Python 构建 Agent，用 Java/Spring 真实源码和故障模式作为诊断领域。

## v0.1 最小循环

```text
日志输入
  -> 解析文本日志 + Java 堆栈
  -> tree-sitter Java 源码索引
  -> 从最上层 in-project stack frame 生成种子假设
  -> Mock/DeepSeek Provider 规划工具调用
  -> ToolExecutor 执行只读工具
  -> Evidence Store 记录证据
  -> Evaluator 按证据覆盖确认/拒绝
  -> Markdown/JSON 报告 + run 产物
```

v0.1 只实现一个 **可运行、可演示、可复核** 的垂直切片，不实现完整平台。

## 快速开始

要求：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync
uv run tracemind --help
```

## Demo（离线 Mock）

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

默认使用 `fixtures/mock/basic_plan.json`，不访问网络、不需要 API Key。

预期结果：

- 退出码 `0`
- 报告状态 `confirmed`
- 终端显示状态、根因候选、证据数、工具调用数和报告路径
- 运行产物写入 `.tracemind/runs/<run_id>/`

只输出 JSON 摘要：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock \
  --json
```

### 可选：真实 DeepSeek

```bash
export DEEPSEEK_API_KEY=...
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider deepseek
```

默认模型是 `deepseek-flash`，Planner 默认关闭 thinking；可用 `--model` 或 `TRACEMIND_LLM_MODEL` 覆盖。live 运行不进入自动化验收；CI 和 Demo 默认使用 Mock。

## CLI

| 参数 | 说明 |
|---|---|
| `--log PATH` | 输入日志文件（必填） |
| `--repo PATH` | 本地 Java 仓库根目录（必填） |
| `--service NAME` | 服务名（必填） |
| `--provider mock\|deepseek` | Provider，默认 `mock` |
| `--mock-script PATH` | Mock 响应脚本，默认 `fixtures/mock/basic_plan.json` |
| `--output-dir PATH` | 运行产物目录，默认 `.tracemind/runs` |
| `--max-iterations N` | 最大规划轮数 |
| `--max-tool-calls N` | 最大工具调用数 |
| `--json` | 输出机器可读摘要 |
| `--version` | 显示版本 |

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 报告生成且状态为 `confirmed` / `probable` |
| `1` | 运行时/IO/Provider 错误 |
| `2` | CLI 用法或 provider 参数错误 |
| `3` | 证据不足（`insufficient_data`） |
| `4` | 预算耗尽 |

退出码 `0` 只表示报告成功生成，不代表“根因绝对正确”。

## 运行产物

```text
.tracemind/runs/<run_id>/
  run.json        # provider/model/state/stop/budget/service/log/repo/index 摘要
  events.jsonl    # 状态转换、LLM、工具、证据、停止事件
  audit.jsonl     # 工具调用、参数 hash、结果、耗时
  report.md       # Jinja2 模板渲染的人类可读报告
  report.json     # report schema 0.1
```

报告中的源码/日志引用会被校验：

- `repo://<relative_path>#Lx-Ly`
- `log://<event_id>` 或 `log://<log_file>#Lx-Ly`

校验失败会降级为 `insufficient_data`，不会伪造“confirmed”。

## 架构

```text
CLI (Typer)
  -> LogParser (文本日志 + Java 堆栈)
  -> TreeSitterJavaIndex (类/方法/行号/源码范围)
  -> DiagnosisRuntime (确定性状态机/预算/停止)
       -> LLM Provider (Mock / DeepSeek)
       -> ToolExecutor (参数校验/路径安全/去重/输出限制/审计)
       -> Evidence Store + Evaluator
       -> Report (Jinja2) + RunStore
```

核心目录：

```text
src/tracemind/
  cli/            # 命令入口
  core/           # 领域模型与错误
  log_analysis/   # 日志/堆栈解析
  indexing/       # tree-sitter Java 索引
  tools/          # ToolSpec/Registry/Executor + 本地工具
  llm/            # Provider 抽象、Mock、DeepSeek
  diagnosis/      # Runtime/Evidence/Evaluator/Report + 报告模板
  storage/        # RunStore
  observability/  # 事件 JSONL
```

## Agent 设计取舍

- **自研薄运行时**：状态机、预算、审批边界、证据门槛和停止条件由确定性代码控制；不引入 LangGraph/PydanticAI。框架适合开放式自主循环，本项目的核心是可审计的诊断流程。
- **Provider 中立**：DeepSeek 通过 OpenAI 兼容接口接入；Claude 预留 Anthropic 适配器。
- **LLM 不确认根因**：LLM 规划工具；`stack_frame + log_event + source_code` 三类证据齐全后，由 Evaluator 确认。
- **只读工具**：日志搜索、事件上下文、符号查找、源码范围读取；所有调用经过 `ToolExecutor`。
- **证据优先**：报告引用必须可解析；引用/证据 ID/状态不一致时降级。
- **Mock 优先**：Demo、测试和 CI 不依赖实时模型；Mock 脚本确定性可重放。

## Java 定位能力

当前 fixture 展示：

- 异常堆栈 → `OrderService.updateStatus` 源码位置
- 类/方法/重载/嵌套类索引
- `repo://` 源码行范围引用
- `log://` 日志事件引用
- 根因候选、证据 ID、缺失证据和限制说明

v0.1 使用 **单个合成 Spring 风格仓库 + 单个日志 fixture**，用于验证定位流程与证据链，不代表生产验证。

## 评估与验收

当前 checkout 的验证结果：

| 检查 | 结果 |
|---|---|
| 全量测试 | **112 passed** |
| T7 报告/CLI/E2E | 16 passed |
| `ruff check .` | 通过 |
| `mypy src` | 通过（35 个源文件） |
| Mock CLI Demo | 退出码 0，5 类产物，报告 `confirmed` |

详细 AC 映射见 [验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)。

说明：

- v0.1 只有一个合成 fixture，不宣称统计意义上的准确率。
- 6 个 Java fixture、LLM-only ablation、真实远程工具尚未实现。
- 所有数字均来自当前仓库实际命令；未执行的 live 场景不写成通过。

## 已知限制

- 只支持一种文本日志 pattern；不支持 JSON 日志、多文件轮转、跨文件时间线。
- 单仓库、内存索引；没有 SQLite/FTS5、增量索引、多仓库消歧。
- tree-sitter 是静态语法分析；Lombok、Spring AOP/代理、反射和运行时分派不可见。
- 本地只读工具；没有远程 MCP/SSH/DB/Redis、审批和完整 Policy Engine。
- 没有 OTel/OTLP、长期保留、Web UI。
- 只有一个合成 fixture；没有 6 个 Java fixture 和 LLM-only ablation。
- 合成数据不代表生产验证；源码版本与线上部署版本一致性未验证。

## v0.1 与 v2 设计

完整设计见 [TraceMind Agent 系统设计文档 v2.0](docs/TraceMind_Agent_System_Design_v2.md)。

| 能力 | v0.1 | v2 设计 |
|---|---|---|
| Agent Runtime | 确定性最小循环 | 状态机 + Planner/Evaluator/Reflection/审批 |
| Provider | Mock + DeepSeek | DeepSeek 优先、Claude 预留 |
| Java 索引 | tree-sitter 单仓库 | 多仓库、FTS5/SQLite、JDT 精度模式 |
| 工具 | 四个本地只读工具 | 远程 MCP/SSH/DB/Redis |
| 评估 | 单 fixture + 单元/E2E | 6 个 Java fixture + LLM-only ablation |
| 可观测性 | JSONL events/audit | OTel + 长期保留 |
| 报告 | Markdown + JSON + 引用校验 | 同左 + 更多证据/状态 |

## 目录

```text
TraceMind/
├── src/tracemind/             # 实现
├── tests/                     # 单元/集成/E2E
├── fixtures/                  # 日志、仓库、Mock 脚本
├── specs/001-minimal-loop/    # SDD specs/tasks + acceptance
├── docs/                      # v1/v2 设计文档
├── pyproject.toml
└── uv.lock
```

## 文档

- [v2.0 系统设计](docs/TraceMind_Agent_System_Design_v2.md)
- [v0.1 SDD 索引](specs/001-minimal-loop/README.md)
- [v0.1 验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)
- [T1–T8 specs/tasks](specs/001-minimal-loop/)

## 下一步

- 补齐 6 个 Java fixture：事务自调用、MyBatis N+1、连接池、Redis、异步/MDC、死锁。
- 增加 LLM-only ablation 和证据覆盖率指标。
- 接入一个 MySQL 只读 MCP 工具（stretch）。
- 引入 SQLite FTS5、JDT sidecar、OTel。
- 扩展 Java 知识 catalog 与更多日志格式。

## 诚实边界

本项目是 v0.1 原型，不是生产系统：

- 不自动修复代码或配置。
- 不执行生产写操作、任意 Shell/SQL/Redis 命令。
- 不宣称生产准确率或替代 APM/SRE。
- 远程工具、审批和 OTel 留在 post-v0.1。
