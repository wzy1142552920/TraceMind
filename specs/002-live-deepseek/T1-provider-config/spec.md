# T1 — Provider 配置、`.env` 与 preflight Spec

- **任务 ID**：T1
- **状态**：implemented
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.1 的 `DeepSeekProvider` 使用硬编码默认值，CLI 没有 Key preflight；缺少 Key 时只会得到 runtime FAILED 和泛化报告。v0.2 需要让用户把本地开发 Key 放在项目根 `.env`，同时保持真实环境变量和 CLI 覆盖的明确优先级，并在开始解析/索引前给出清晰错误。

**用户故事**：作为开发者，我把 `DEEPSEEK_API_KEY` 放在项目根 `.env`，运行 `--provider deepseek`；配置模型/超时/重试可以 CLI 覆盖；没有 Key 时立即得到明确提示，而不是跑完索引后才失败。

## 2. In scope

- 新增 `LLMSettings` 配置模型和解析函数。
- 使用 `python-dotenv` 加载项目根 `.env`，`override=False`。
- 配置优先级：CLI > 真实环境变量 > `.env` > 默认值。
- CLI 参数：`--model`、`--base-url`、`--llm-timeout`、`--llm-max-retries`、`--llm-max-tokens`、`--max-repair-attempts`。
- `DEEPSEEK_API_KEY` preflight：在日志解析/仓库索引/输出目录创建之前检查。
- `DeepSeekProvider` 使用 settings；run.json 记录脱敏后的 LLM 配置。
- `.env.example` 和 `.gitignore` 例外。
- Mock 路径不要求 Key，行为不变。

## 3. Out of scope

- 重试实现/错误分类（T2）。
- usage/latency（T3）。
- 计划修复（T4）。
- live 测试 gate（T5）。
- YAML 配置文件、`--api-key`、Key 持久化、Key 加密。
- 修改 v0.1 的 Mock 行为。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T1-01 | 定义 `LLMSettings`（model/base_url/timeout/max_tokens/max_retries/repair_attempts） | must |
| FR-T1-02 | 项目根 `.env` 可加载 `DEEPSEEK_API_KEY`；真实环境变量优先 | must |
| FR-T1-03 | CLI 参数覆盖环境/`.env`/默认值 | must |
| FR-T1-04 | 缺 Key 在解析/索引/建目录前失败，退出 2，提示 `.env`/环境变量 | must |
| FR-T1-05 | DeepSeekProvider 使用配置值构造请求 | must |
| FR-T1-06 | run.json 记录 model/base_url/timeout/max_tokens/max_retries，不含 Key | must |
| FR-T1-07 | `.env` 被忽略；`.env.example` 被跟踪 | must |
| FR-T1-08 | Mock provider 不需要 Key，现有行为不变 | must |

## 5. 接口/数据契约

### `LLMSettings`

| 字段 | 默认 | 环境变量 | CLI |
|---|---|---|---|
| `model` | `deepseek-flash` | `TRACEMIND_LLM_MODEL` | `--model` |
| `base_url` | `https://api.deepseek.com` | `TRACEMIND_LLM_BASE_URL` | `--base-url` |
| `timeout_seconds` | `60` | `TRACEMIND_LLM_TIMEOUT` | `--llm-timeout` |
| `max_tokens` | `4000` | `TRACEMIND_LLM_MAX_TOKENS` | `--llm-max-tokens` |
| `max_retries` | `2` | `TRACEMIND_LLM_MAX_RETRIES` | `--llm-max-retries` |
| `repair_attempts` | `2` | `TRACEMIND_MAX_REPAIR_ATTEMPTS` | `--max-repair-attempts` |
| `api_key_env` | `DEEPSEEK_API_KEY` | 固定 | 不暴露 |

- 数值校验：timeout > 0；max_tokens > 0；max_retries 0..2；repair_attempts 0..5。
- `resolve_settings(cli_overrides)`：CLI 显式值优先；否则读环境变量；`.env` 已合并到环境；否则默认。

### `.env` 加载

```python
def load_project_env() -> None:
    """Load .env from cwd or a parent directory without overriding real env."""
```

- 使用 `python-dotenv` 的 `find_dotenv/load_dotenv(override=False)`。
- 不打印 `.env` 内容或 Key。
- `.env.example` 只包含 `DEEPSEEK_API_KEY=` 占位符和可选 `TRACEMIND_LLM_MODEL=deepseek-flash`。
- `.gitignore` 保留 `.env`/`.env.*`，增加 `!.env.example`。

### preflight

- 选择 `--provider deepseek` 后立即执行 Key preflight。
- Key 取 `os.environ.get("DEEPSEEK_API_KEY")`；为空/全空白视为缺失。
- 失败信息包含：

```text
DEEPSEEK_API_KEY is not set. Put it in .env or export it, or use --provider mock.
```

- 失败时退出码 2，不解析日志、不索引仓库、不创建 run 目录、不构造 OpenAI client。
- Mock provider 跳过 preflight。

### 运行元数据

run.json 增加脱敏配置：

```json
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "timeout_seconds": 60,
    "max_tokens": 4000,
    "max_retries": 2
  }
}
```

不得包含 `api_key`、`DEEPSEEK_API_KEY` 的值或 `sk-` 字符串。

### Thinking

v0.2 的 Planner 默认关闭 DeepSeek thinking，请求体带：

```json
{"extra_body": {"thinking": {"type": "disabled"}}}
```

- 默认模型 `deepseek-flash`；可通过 `--model`/`TRACEMIND_LLM_MODEL` 覆盖。
- `DeepSeekProvider(thinking_enabled=False)` 为默认；`thinking_enabled=True` 保留给未来/测试，不暴露 CLI。
- thinking 模式下的 `reasoning_content` 不进入证据或报告。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T1-01 | `.env` 中 Key 被加载 | `tests/unit/test_llm_config.py` |
| AC-T1-02 | 真实 env 覆盖 `.env` | `test_real_env_wins_over_dotenv` |
| AC-T1-03 | CLI 覆盖 env/`.env` | `test_cli_overrides_env` |
| AC-T1-04 | 缺 Key 退出 2，无 run 目录，提示 `.env`/环境变量 | CLI preflight E2E |
| AC-T1-05 | DeepSeek provider 使用配置值 | fake client construction test |
| AC-T1-06 | run.json 记录脱敏配置，无 Key/`sk-` | run store/secret scan |
| AC-T1-07 | Mock 路径行为不变 | 全量离线测试 / E2E |
| AC-T1-08 | `.env` ignored、`.env.example` tracked | `git check-ignore` / `git ls-files` |

## 7. 测试计划

### 单元

- `tests/unit/test_llm_config.py`
  - `.env` 加载 Key。
  - 真实 env 优先于 `.env`。
  - CLI 覆盖环境。
  - 数值校验/默认值。
- `tests/unit/test_deepseek_provider.py`
  - 配置传入 model/base URL/timeout/max tokens/max retries。
  - 无 Key preflight 不构造 client。

### 集成/E2E

- `tests/e2e/test_live_preflight.py`
  - `--provider deepseek` 无 Key → exit 2；输出目录不存在。
  - 有假 Key（monkeypatch）→ preflight 通过，进入后续阶段（不实际网络）。
- 现有 `tests/e2e/test_minimal_loop.py` 的 Mock happy path 不变。

### 安全检查

- run.json/events/report/audit 不含 Key 或 `sk-`。
- `.env` 不被 git 跟踪；`.env.example` 被跟踪。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| `.env` 查找位置 | cwd 不在项目根时找不到 | 文档要求从项目根运行；`find_dotenv` 向上查找；测试覆盖 |
| 优先级实现错误 | `.env` 覆盖真实 env | `override=False`；显式测试 |
| Secret 泄漏 | 配置对象/日志/run.json 记录 Key | 只保存 key env 名/不保存值；secret scan |
| CLI 默认值掩盖环境 | 默认 `None` 才能区分未指定 | CLI 参数默认 `None`，解析后回填默认 |
| 缺 Key 错误码 | 与 usage error 冲突 | 明确约定 exit 2；文档/测试 |
| Mock 回归 | 新配置要求影响 Mock | Mock 分支不加载 Key/preflight |

**开放问题**

- 是否支持从 `.env.local`/多环境文件加载？v0.2 只支持项目根 `.env`。
- 是否把 `.env.example` 放在项目根？是。
- 是否显示实际 base URL？run.json 显示脱敏 URL；不显示 Key。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_llm_config.py tests/e2e/test_live_preflight.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| 2026-10-21 | T1 专项 `pytest`（config/preflight/provider） | 21 passed |
| 2026-10-21 | 全量 `pytest` | 126 passed |
| 2026-10-21 | `ruff check .` / `mypy src` | 通过；36 个源文件 |
| 2026-10-21 | `--provider deepseek` 无 Key | 退出 2；无输出目录；提示 `.env`/环境变量 |
| 2026-10-21 | `.env`/`.env.example` | `.env` ignored；`.env.example` unignored（提交后 tracked） |
| 2026-10-21 | run.json | Mock E2E 含脱敏 `llm` 块；无 Key/`sk-` |
| 2026-10-21 | 默认模型/thinking | `deepseek-flash`；请求带 `thinking: disabled`；thinking 可显式启用 |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T1 spec；定义 `.env`/配置优先级/preflight/元数据 |
| 2026-10-21 | T1 实现完成；配置层、`.env`、preflight、CLI 参数和测试落地 |
