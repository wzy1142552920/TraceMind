# TraceMind v0.2 — 真实 DeepSeek Live 集成 SDD

- **状态**：implementation in progress（T1 implemented；T2–T6 pending）
- **父设计**：[TraceMind v2.0](../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.1 基线**：[v0.1 SDD](../001-minimal-loop/README.md)
- **目标**：让 `--provider deepseek` 真实完成现有最小诊断循环，并补齐配置、`.env`、重试、usage/latency、计划修复和 opt-in live 验收
- **当前 live 状态**：规划时未配置 `DEEPSEEK_API_KEY`；live AC 在真实运行前不得标记 PASS

## 1. 目标与范围

v0.2 不扩展平台，只把 v0.1 的 live 路径做扎实：

1. `--provider deepseek` 在现有 fixture 上真实调用 DeepSeek，规划本地工具，收集 `stack_frame + log_event + source_code`，由 Evaluator 确认并生成可校验报告。
2. 支持项目根目录 `.env` 配置 `DEEPSEEK_API_KEY`，同时保留真实环境变量和 CLI 覆盖。
3. 增加 Key preflight、配置元数据、受控重试、token/latency 记录。
4. 增加有界计划修复，让真实模型在 text-only、unknown tool、invalid args、duplicate、length 等情况下仍能在预算内恢复或明确停止。
5. 增加 opt-in live pytest marker 和真实 CLI 验收；无 Key 时明确 BLOCKED。
6. 按 SDD 为 T1–T6 各生成 `spec.md`/`task.md`。

**不包含**：

- 新工具、新 fixture、6-case eval、LLM-only ablation。
- 远程 MCP/SSH/DB/Redis、OTel、JDT、SQLite/FTS5、Web UI。
- streaming/async、完整 conversation replay、prompt caching。
- 总运行 deadline、jitter/Retry-After、价格估算。
- v0.1 报告 schema 兼容 shim。

## 2. 任务索引

| ID | 任务 | 依赖 | 状态 | Spec | Task |
|---|---|---|---|---|---|
| T1 | Provider 配置、`.env` 与 preflight | — | implemented | [spec](./T1-provider-config/spec.md) | [task](./T1-provider-config/task.md) |
| T2 | DeepSeek transport hardening | T1 | draft | [spec](./T2-transport-hardening/spec.md) | [task](./T2-transport-hardening/task.md) |
| T3 | LLM usage / latency / provenance | T1、T2 | draft | [spec](./T3-usage-observability/spec.md) | [task](./T3-usage-observability/task.md) |
| T4 | Live-plan resilience | T2、T3 | draft | [spec](./T4-live-plan-resilience/spec.md) | [task](./T4-live-plan-resilience/task.md) |
| T5 | Opt-in live verification | T1–T4 | draft | [spec](./T5-live-verification/spec.md) | [task](./T5-live-verification/task.md) |
| T6 | 文档、验收与发布 | T1–T5 | draft | [spec](./T6-docs-release/spec.md) | [task](./T6-docs-release/task.md) |

执行顺序：`T1 -> T2 -> T3 -> T4 -> T5 -> T6`。T3/T4 都改 runtime，串行实施。

## 3. 共享决策

### 配置优先级

```text
CLI 参数 > 真实环境变量 > 项目根 .env > 默认值
```

- `.env` 使用 `python-dotenv` 加载，`override=False`，不得覆盖真实环境变量。
- 不提供 `--api-key`；Key 只从环境变量或 `.env` 读取。
- `.env` 已被 `.gitignore` 忽略；新增 `.env.example`（占位符）并加 `!.env.example` 例外。
- Key 不进入 run.json、events、report、audit 或普通日志。

### DeepSeek 默认值

| 设置 | 默认 |
|---|---|
| model | `deepseek-chat` |
| base URL | `https://api.deepseek.com` |
| timeout | 60s |
| max tokens | 4000 |
| max retries | 2 |
| repair attempts | 2 |

### 错误与重试

- 只重试：429、5xx、timeout、connection、empty response。
- 最多 2 次，固定 0.5s/1.0s 退避。
- 不重试：401/403、400/404/422、invalid tool arguments、missing key。
- OpenAI SDK `max_retries=0`，TraceMind 自己控制重试并记录 attempts。

### 可观测性

- 每次 LLM 调用记录 provider/model/request_id/latency/attempts/finish_reason/tool_calls/tokens/error。
- `RunResult` 增加 `llm_calls` 和 `llm_usage`；保留 `budget_usage` 的三个原始 key。
- 报告 schema 升级到 `0.2`，增加 usage 信息。
- Mock 仍确定性可重放。

### Live 验收

- `live` marker + `--run-live` + `TRACEMIND_LIVE_TESTS=1` + Key（env 或 `.env`）才运行。
- 默认测试和 CI 完全离线。
- 没有 Key 时 live AC 标 **BLOCKED**，不能写 PASS；离线 AC 仍可通过。
- live 断言结构/证据/报告，不硬编码唯一自然语言答案。

## 4. 验收

详细矩阵：[ACCEPTANCE.md](./ACCEPTANCE.md)。

T1 AC 已通过并回填；T2–T6 仍为 `PLANNED`。live AC 在真实 Key 运行前为 `BLOCKED (no DEEPSEEK_API_KEY)`。

## 5. 复用与不做重写

复用：

- `LogParser`、`TreeSitterJavaIndex`、`ToolExecutor`、`DiagnosisRuntime`、`RunStore`。
- Jinja2 报告模板。
- v0.1 的 Mock/DeepSeek provider 契约和测试结构。

不重写最小循环；v0.2 只增强 live 路径的配置、可靠性、可观测性和验收。

## 6. 文档约定

- 每个 spec 含 Context、In/Out scope、FR、契约、AC、测试计划、风险、验证命令、变更记录。
- 每个 task 含依赖、spec→测试→实现→验证步骤、交付物、DoD、验证命令、风险。
- 未实现项标记 `draft`/`PLANNED`；不伪造测试或 live 结果。
- 不修改 `docs/TraceMind_Agent_System_Design*.md` 和 `specs/001-minimal-loop/**`。

## 7. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 v0.2 SDD 索引与 T1–T6 任务拆分；包含 `.env` 配置和 live BLOCKED 规则 |
