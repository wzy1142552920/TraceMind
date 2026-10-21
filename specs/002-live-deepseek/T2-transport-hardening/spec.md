# T2 — DeepSeek Transport Hardening Spec

- **任务 ID**：T2
- **状态**：implemented
- **依赖**：T1
- **下游**：T3、T4、T5、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

真实 DeepSeek API 会遇到 429、5xx、超时和连接失败。v0.1 把所有异常都折叠为 `provider_error`，并依赖 OpenAI SDK 的隐式重试；重试次数、状态码和可重试性都不可观测。

**用户故事**：作为运行时，我能区分可重试与不可重试错误，在有限次数内自动重试临时故障，并把 attempts/status/request ID 带进错误和可观测数据；认证/参数错误立即失败。

## 2. In scope

- 扩展 `LLMProviderError` 元数据：`code`、`retryable`、`attempts`、`status_code`、`request_id`。
- 错误分类：missing key/auth/bad request/rate limit/timeout/connection/server/empty response/invalid tool arguments/provider error。
- 有界重试：仅 429/5xx/timeout/connection/empty response；最多 2 次，固定 0.5s/1.0s。
- 关闭 OpenAI SDK 隐式重试（`max_retries=0`）；传入配置 timeout。
- `LLMResponse.attempts` 记录成功调用实际 attempts。
- Fake-client 单元测试；不访问网络。

## 3. Out of scope

- live 网络测试（T5）。
- usage/latency 持久化（T3）。
- 计划修复（T4）。
- jitter/Retry-After、总运行 deadline、价格估算。
- 多 Provider 通用重试框架；只实现 DeepSeek adapter。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T2-01 | `LLMProviderError` 携带 code/retryable/attempts/status_code/request_id | must |
| FR-T2-02 | 429/5xx/timeout/connection/empty response 可重试 | must |
| FR-T2-03 | auth/bad request/invalid tool arguments/missing key 不重试 | must |
| FR-T2-04 | 最多 2 次重试，退避 0.5s/1.0s | must |
| FR-T2-05 | OpenAI SDK max_retries=0；请求 timeout 来自配置 | must |
| FR-T2-06 | 成功响应记录 attempts | must |
| FR-T2-07 | 测试通过 fake client/注入 sleep，不访问网络 | must |

## 5. 接口/数据契约

### `LLMProviderError`

```python
class LLMProviderError(Exception):
    code: str
    message: str
    retryable: bool = False
    attempts: int = 1
    status_code: int | None = None
    request_id: str | None = None
```

错误码：

`missing_api_key`、`auth_error`、`bad_request`、`rate_limit`、`timeout`、`connection_error`、`server_error`、`empty_response`、`invalid_tool_arguments`、`provider_error`。

### 重试策略

| 条件 | 重试 | 说明 |
|---|---|---|
| HTTP 429 | 是 | rate_limit |
| HTTP 5xx | 是 | server_error |
| timeout | 是 | timeout |
| connection error | 是 | connection_error |
| empty choices | 是 | empty_response |
| 401/403 | 否 | auth_error |
| 400/404/422 | 否 | bad_request |
| invalid tool args JSON | 否 | invalid_tool_arguments |
| missing key | 否 | missing_api_key |

- 最多 2 次重试（总 attempts 最多 3）。
- 延迟 `[0.5, 1.0]` 秒；测试可注入 sleep。
- 不重试非幂等业务调用之外的工具；只重试 LLM 请求。

### `DeepSeekProvider`

- 构造 `OpenAI(api_key=..., base_url=..., timeout=settings.timeout, max_retries=0)`。
- `complete()` 内部循环；成功返回 `LLMResponse(..., attempts=n)`。
- 最终失败抛最新 `LLMProviderError`，保留 attempts/status/request_id。
- 缺 Key 由 T1 preflight 保证；provider 仍保留 missing_api_key 防御。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T2-01 | 429/5xx 重试最多 2 次，sleep 0.5/1.0 | `tests/unit/test_deepseek_retry.py` |
| AC-T2-02 | timeout/connection 重试；连续失败明确失败 | `test_retry_timeout_exhausts` |
| AC-T2-03 | auth/bad request/invalid args 不重试 | `test_auth_not_retried` 等 |
| AC-T2-04 | 错误含 code/retryable/attempts/status/request_id | provider error tests |
| AC-T2-05 | SDK `max_retries=0`，timeout 配置生效 | `test_openai_client_configured` |
| AC-T2-06 | fake-client 测试无网络 | 注入 client + sleep |
| AC-T2-07 | 成功响应 attempts 正确 | `test_success_records_attempts` |

## 7. 测试计划

### 单元

- `tests/unit/test_deepseek_retry.py`
  - rate limit → success；server error → success。
  - timeout/connection → success / exhaust。
  - auth/bad request/invalid args → 一次调用，无 sleep。
  - empty choices → retry / exhaust。
  - sleep 序列、attempts、request ID、status code。
  - 构造 OpenAI client 参数断言。
- 更新 `tests/unit/test_deepseek_provider.py` 的错误断言。

### 集成

- 使用注入 client 的 provider；不启动网络。
- 现有 Mock 测试不变。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| SDK 异常形态 | openai 版本异常类/字段变化 | 优先按 status_code/类名分类；fake 不依赖 SDK 内部 |
| 双重重试 | SDK 隐式重试 + 我们的重试 | 显式 `max_retries=0`；测试断言 |
| 重试耗时 | 测试真实 sleep | 注入 sleep 函数；生产固定短退避 |
| 重试放大成本 | 429/5xx 多次请求 | 最多 2 次；记录 attempts/tokens |
| 非重试错误被重试 | 认证/参数问题 | 分类测试 |
| 部分响应/半截工具 | 5xx/流式碎片 | v0.2 不启用流式；空 choices 可重试 |

**开放问题**

- 是否尊重 `Retry-After`？v0.2 不做，固定退避。
- 是否记录每次 attempt 的 latency？v0.2 只记录总 attempts；per-call latency 在 T3 记录整体。
- 是否统一 OpenAI/Anthropic 重试层？v0.2 只做 DeepSeek。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_deepseek_retry.py tests/unit/test_deepseek_provider.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| 2026-10-21 | T2 专项 `pytest`（retry/provider） | 21 passed |
| 2026-10-21 | 全量 `pytest` | 137 passed |
| 2026-10-21 | `ruff check .` / `mypy src` | 通过；36 个源文件 |
| 2026-10-21 | 重试/错误分类 | 429/5xx/timeout/connection/empty 可重试；auth/bad/invalid 不重试 |
| 2026-10-21 | SDK 配置 | `max_retries=0`；timeout 来自配置 |
| 2026-10-21 | 测试网络 | fake client + 注入 sleep；无真实网络 |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T2 spec；定义错误分类、有限重试、SDK 重试控制和测试 |
| 2026-10-21 | T2 实现完成；错误元数据、有限重试、attempts、SDK 重试关闭测试通过 |
