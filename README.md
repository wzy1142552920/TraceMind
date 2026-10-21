# TraceMind

**本地优先、证据驱动的 Java 故障定位 Agent（v0.2 真实 DeepSeek 最小循环）。**

TraceMind 读取一份 Java 应用日志和本地源码，解析异常堆栈、索引类/方法，由一个受控 Agent 运行时规划只读工具调用，收集证据，定位到源码行号，并输出带引用校验的 Markdown/JSON 诊断报告。

LLM 只负责规划、假设和解释；预算、工具权限、停止条件、证据状态和引用校验由确定性代码负责。

> 项目定位：面向 **AI Agent（主）+ Java** 方向的工程作品。用 Python 构建 Agent，用 Java/Spring 真实源码和故障模式作为诊断领域。

## 最小诊断循环

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

v0.1 完成可离线复现的最小循环；v0.2 让同一循环真实调用 DeepSeek，并补齐配置、重试、使用量记录和有界计划修复。

## v0.2 新增

- **项目根 `.env`**：`DEEPSEEK_API_KEY` 可放在 `.env`，无需每次 `export`；`.env` 已被忽略，只提交占位符 `.env.example`。
- **配置优先级**：CLI 参数 > 真实环境变量 > `.env` > 默认值；Key 缺失时在解析日志/索引仓库/创建产物前退出 `2`。
- **DeepSeek 默认值**：`deepseek-flash`，Planner 默认关闭 thinking；模型可用 `--model` / `TRACEMIND_LLM_MODEL` 覆盖。
- **受控重试**：只重试 429、5xx、timeout、connection、空响应；最多 2 次，固定 0.5s/1.0s 退避；auth/参数错误不重试。
- **有界计划修复**：把上一轮工具结果/错误/新证据反馈给模型；text-only、未知工具、非法参数、无新证据、`finish_reason=length` 可在最多 2 轮内修复，仍受迭代/工具/LLM 预算约束。
- **Usage / latency / provenance**：每次 LLM 调用记录 provider/model/request ID/attempts/tokens/latency/finish reason；报告 schema 升到 `0.2`。
- **Opt-in live 验证**：默认测试完全离线；显式打开 gate 后跑真实 DeepSeek adapter + CLI 测试，并扫描产物中的 secret。

## 快速开始

要求：

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync
uv run tracemind --help
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
- 终端显示状态、根因候选、证据数、工具调用数、LLM 使用量和报告路径
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

## 真实 DeepSeek

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider deepseek \
  --output-dir /tmp/tracemind-live \
  --max-iterations 4 --max-tool-calls 6 --llm-max-tokens 800
```

建议用较小的迭代/工具/token 预算控制成本。真实输出具有非确定性，合法工具路径可能不同；成功标准是结构、证据和引用校验，而不是唯一措辞。

没有配置 Key 时：

```text
DEEPSEEK_API_KEY is not set. Put it in .env or export it, or use --provider mock.
```

命令在日志解析、仓库索引和创建输出目录之前退出 `2`。

### Live 测试（opt-in）

live 测试需要 `--run-live`、`TRACEMIND_LIVE_TESTS=1` 和非空 Key（环境变量或 `.env`）三者同时满足：

```bash
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q
```

默认 `uv run pytest` 会跳过 live 测试，不访问网络、不产生费用。未满足 gate 时 live 验收只能标记 `BLOCKED`，不能写成通过。

## CLI

| 参数 | 说明 |
|---|---|
| `--log PATH` | 输入日志文件（必填） |
| `--repo PATH` | 本地 Java 仓库根目录（必填） |
| `--service NAME` | 服务名（必填） |
| `--provider mock\|deepseek` | Provider，默认 `mock` |
| `--mock-script PATH` | Mock 响应脚本，默认 `fixtures/mock/basic_plan.json` |
| `--output-dir PATH` | 运行产物目录，默认 `.tracemind/runs` |
| `--max-iterations N` | 最大规划轮数，默认 `6` |
| `--max-tool-calls N` | 最大工具调用数，默认 `8` |
| `--model NAME` | 模型覆盖，默认 `deepseek-flash` |
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
  run.json        # schema 0.2：provider/model/state/stop/budget/log/repo/index + LLM 配置/usage/逐次调用
  events.jsonl    # 状态转换、LLM、工具、证据、修复、停止事件
  audit.jsonl     # 工具调用、参数 hash、结果、耗时
  report.md       # Jinja2 模板渲染的人类可读报告
  report.json     # report schema 0.2（含 llm_usage / llm_calls）
```

报告中的源码/日志引用会被校验：

- `repo://<relative_path>#Lx-Ly`
- `log://<event_id>` 或 `log://<log_file>#Lx-Ly`

校验失败会降级为 `insufficient_data`，不会伪造“confirmed”。

## 可靠性与可观测性

- **证据门槛不变**：`stack_frame + log_event + source_code` 三类证据齐全后，只有 Evaluator 能把假设标记为 `confirmed`；模型文本不能直接确认。
- **传输重试**：OpenAI SDK 隐式重试关闭（`max_retries=0`），由 TraceMind 记录 `attempts` 并做有界退避；401/403、400/404/422 和非法工具参数不重试。
- **计划修复**：修复轮会收到上一轮观察（文本、工具结果、错误码、新证据数、缺失证据、剩余预算）；修复次数和总预算同时受限，耗尽后以 `no_progress`/`insufficient_data` 停止。
- **使用量**：`run.json`、`report.json` 和终端摘要包含 calls/failed/retries、input/output/total tokens 和累计 latency；provider 未返回的 token 字段保持 `null`，不虚构。
- **Secret 安全**：live 测试扫描 run 产物，确认不包含 Key 或 `sk-` 前缀。

## 架构

```text
CLI (Typer)
  -> LogParser (文本日志 + Java 堆栈)
  -> TreeSitterJavaIndex (类/方法/行号/源码范围)
  -> DiagnosisRuntime (确定性状态机/预算/停止/修复)
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
  llm/            # Provider 抽象、配置、Mock、DeepSeek
  diagnosis/      # Runtime/Evidence/Evaluator/Report + 报告模板
  storage/        # RunStore
  observability/  # 事件 JSONL
```

## Agent 设计取舍

- **自研薄运行时**：状态机、预算、审批边界、证据门槛和停止条件由确定性代码控制；不引入 LangGraph/PydanticAI。框架适合开放式自主循环，本项目的核心是可审计的诊断流程。
- **Provider 中立**：DeepSeek 通过 OpenAI 兼容接口接入；Claude 预留 Anthropic 适配器。
- **LLM 不确认根因**：LLM 规划工具；三类证据齐全后由 Evaluator 确认。
- **只读工具**：日志搜索、事件上下文、符号查找、源码范围读取；所有调用经过 `ToolExecutor`。
- **证据优先**：报告引用必须可解析；引用/证据 ID/状态不一致时降级。
- **Mock 优先**：Demo、默认测试和 CI 不依赖实时模型；Mock 脚本确定性可重放。真实 DeepSeek 验证是显式 opt-in。

## Java 定位能力

当前 fixture 展示：

- 异常堆栈 → `OrderService.updateStatus` 源码位置
- 类/方法/重载/嵌套类索引
- `repo://` 源码行范围引用
- `log://` 日志事件引用
- 根因候选、证据 ID、缺失证据和限制说明

v0.2 仍使用 **单个合成 Spring 风格仓库 + 单个日志 fixture**，用于验证定位流程与证据链，不代表生产验证。

## 评估与验收

当前 checkout 的验证结果（2026-10-21）：

| 检查 | 结果 |
|---|---|
| 默认离线测试 | **146 passed, 2 skipped**（live 测试跳过，不访问网络） |
| Live DeepSeek 测试 | **2 passed**（adapter + CLI，实际调用 `deepseek-flash`） |
| `ruff check .` | 通过 |
| `mypy src` | 通过（36 个源文件） |
| Mock CLI Demo | 退出码 0，5 类产物，报告 `confirmed`，schema 0.2 |
| Live CLI Demo | 退出码 0，报告 `confirmed`，三类证据，usage/latency 有值，产物无 secret |

详细记录：

- [v0.2 验收矩阵](specs/002-live-deepseek/ACCEPTANCE.md)
- [v0.1 验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)

说明：

- 只有单个合成 fixture，不宣称统计意义上的准确率。
- DeepSeek 输出具有非确定性；live 通过只证明当前环境下最小循环可运行，不代表生产准确率。
- 6 个 Java fixture、LLM-only ablation、远程工具尚未实现。

## v0.1 → v0.2

| 能力 | v0.1 | v0.2 |
|---|---|---|
| DeepSeek 接入 | Adapter + fake-client 测试 | 真实 `deepseek-flash` live adapter + CLI 验证 |
| Key 配置 | 环境变量 | 环境变量或项目 `.env`，带 preflight |
| 重试 | SDK 默认行为 | 关闭 SDK 重试，自定义分类/退避/attempts |
| Runtime 反馈 | 不反馈上一轮观察 | 上一轮工具/错误/证据 + 有界 repair |
| Usage | 解析后丢弃 | 逐次调用 + run 级汇总，进入报告 |
| 报告 schema | `0.1` | `0.2` |
| 测试 | 全离线 | 全离线默认 + opt-in live gate |

## 已知限制

- 只支持一种文本日志 pattern；不支持 JSON 日志、多文件轮转、跨文件时间线。
- 单仓库、内存索引；没有 SQLite/FTS5、增量索引、多仓库消歧。
- tree-sitter 是静态语法分析；Lombok、Spring AOP/代理、反射和运行时分派不可见。
- 本地只读工具；没有远程 MCP/SSH/DB/Redis、审批和完整 Policy Engine。
- 没有 OTel/OTLP、长期保留、Web UI。
- 只有一个合成 fixture；没有 6 个 Java fixture 和 LLM-only ablation。
- 合成数据不代表生产验证；源码版本与线上部署版本一致性未验证。
- 无 streaming/async、prompt caching、总运行 deadline、价格估算。
- Live 验证依赖外部 Key/网络，结果可能随模型版本变化。

## 文档

- [v2.0 系统设计](docs/TraceMind_Agent_System_Design_v2.md)
- [v0.2 SDD 索引](specs/002-live-deepseek/README.md)
- [v0.2 验收矩阵](specs/002-live-deepseek/ACCEPTANCE.md)
- [v0.2 T1–T6 specs/tasks](specs/002-live-deepseek/)
- [v0.1 SDD 索引](specs/001-minimal-loop/README.md)
- [v0.1 验收矩阵](specs/001-minimal-loop/ACCEPTANCE.md)

## 下一步

- 补齐 6 个 Java fixture：事务自调用、MyBatis N+1、连接池、Redis、异步/MDC、死锁。
- 增加 LLM-only ablation 和证据覆盖率指标。
- 接入一个 MySQL 只读 MCP 工具（stretch）。
- 引入 SQLite FTS5、JDT sidecar、OTel。
- 扩展 Java 知识 catalog 与更多日志格式。

## 诚实边界

本项目仍是原型，不是生产系统：

- 不自动修复代码或配置。
- 不执行生产写操作、任意 Shell/SQL/Redis 命令。
- 不宣称生产准确率或替代 APM/SRE。
- 远程工具、审批和 OTel 留在后续版本。
