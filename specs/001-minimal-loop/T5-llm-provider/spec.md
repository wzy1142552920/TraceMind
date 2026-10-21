# T5 — LLM Provider 与 Mock/DeepSeek Spec

- **任务 ID**：T5
- **状态**：implemented
- **依赖**：T1
- **下游**：T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

T6 需要一个稳定的 LLM 接口来规划工具调用，但不能把 OpenAI/DeepSeek 的 SDK 类型泄漏到 Agent 领域层。T5 定义 canonical 消息/工具调用契约，提供可脚本化的 MockProvider（测试/离线 demo）和 DeepSeek adapter（真实运行，可选）。

**用户故事**：作为运行时，我调用 `provider.complete(messages, tools)`，拿到统一的 `LLMResponse`（文本 + tool calls + usage），不需要知道底层是 Mock 还是 DeepSeek。

## 2. In scope

- Canonical `Message`、`ToolDefinition`、`ToolCall`、`LLMResponse`、`Usage`。
- 同步 `LLMProvider.complete(messages, tools) -> LLMResponse`。
- `ProviderCapabilities`（最小字段即可）。
- `MockProvider`：从脚本读取响应列表，确定性返回。
- `DeepSeekProvider`：OpenAI 兼容 API、native tool calling、模型/URL/Key 配置。
- Provider 错误模型（最小）。
- 契约测试：不依赖真实网络/API Key。

## 3. Out of scope

- Claude adapter（仅保留接口，v0.1 不实现调用）。
- 异步/流式/Prompt Caching/并行工具调用。
- 完整重试/退避/限流策略。
- Prompt 模板系统；v0.1 的 Prompt 由 T6 内联构造。
- 真实 API 的集成测试。
- Token 成本计算（只记录 usage）。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T5-01 | 定义 canonical `Message`（role/content/tool_call_id）、`ToolDefinition`、`ToolCall`、`LLMResponse`、`Usage` | must |
| FR-T5-02 | `LLMProvider.complete(messages, tools) -> LLMResponse` 同步调用 | must |
| FR-T5-03 | MockProvider 按脚本顺序返回响应，支持文本、tool calls、空响应 | must |
| FR-T5-04 | MockProvider 相同脚本多次运行结果一致 | must |
| FR-T5-05 | DeepSeek adapter 使用 `openai` SDK，支持 `base_url`/`model`/`api_key_env` | must |
| FR-T5-06 | DeepSeek adapter 把 `ToolDefinition` 映射为 OpenAI function tools，并把响应 tool_calls 解析为 canonical `ToolCall` | must |
| FR-T5-07 | ToolCall arguments 解析为 dict；非法 JSON 抛 `LLMProviderError` | must |
| FR-T5-08 | 缺少 API Key 时抛清晰错误，不发起网络请求 | must |
| FR-T5-09 | 记录 usage（input/output tokens）；无 usage 时允许为空 | must |
| FR-T5-10 | 测试通过注入 fake OpenAI client 完成，不读取真实 Key | must |

## 5. 接口/数据契约

### `Message`

| 字段 | 类型 | 说明 |
|---|---|---|
| `role` | `"system" \| "user" \| "assistant" \| "tool"` | 角色 |
| `content` | `str` | 文本内容 |
| `tool_call_id` | `str \| None` | role=tool 时关联调用 |

### `ToolDefinition`

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | 工具名 |
| `description` | `str` | 静态描述 |
| `parameters` | `dict` | JSON Schema（由 T4 的 Pydantic 模型导出） |

### `ToolCall`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | Provider/LLM 返回的调用 ID |
| `name` | `str` | 工具名 |
| `arguments` | `dict` | 已解析参数 |

### `LLMResponse`

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | `str` | 文本内容，可为空 |
| `tool_calls` | `list[ToolCall]` | 可为空 |
| `finish_reason` | `str \| None` | `stop`/`tool_calls` 等 |
| `usage` | `Usage \| None` | token 使用 |
| `raw_provider_id` | `str \| None` | 可选的 Provider 请求 ID |

### `Usage`

| 字段 | 类型 | 说明 |
|---|---|---|
| `input_tokens` | `int \| None` | 输入 token |
| `output_tokens` | `int \| None` | 输出 token |

### `ProviderCapabilities`

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_calling` | `bool` | 是否支持工具调用 |
| `parallel_tool_calls` | `bool` | 是否支持并行工具调用（v0.1 不使用） |
| `context_window` | `int \| None` | 上下文窗口（可为空） |
| `prompt_caching` | `bool` | 是否支持缓存（v0.1 不使用） |

### 接口

```python
class LLMProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...
    def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> LLMResponse: ...
```

### MockProvider 脚本

```json
{
  "responses": [
    {
      "content": "I will inspect the source and logs.",
      "tool_calls": [
        {
          "id": "call_1",
          "name": "code.find_symbol",
          "arguments": {"query": "OrderService.updateStatus"}
        },
        {
          "id": "call_2",
          "name": "logs.search",
          "arguments": {"query": "updateStatus returned rows=0"}
        }
      ],
      "finish_reason": "tool_calls",
      "usage": {"input_tokens": 100, "output_tokens": 30}
    },
    {
      "content": "No further investigation needed.",
      "tool_calls": [],
      "finish_reason": "stop",
      "usage": {"input_tokens": 120, "output_tokens": 10}
    }
  ]
}
```

- 脚本路径由 CLI/env 指定；测试使用 fixture 脚本。
- MockProvider 不读取 fixture 日志/源码，不内置答案；只返回脚本响应。

### DeepSeek 配置

```text
provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
api_key_env: DEEPSEEK_API_KEY
```

- 使用 `openai.OpenAI`（同步）客户端；测试注入 fake client。
- tools 映射为 `{"type": "function", "function": {"name", "description", "parameters"}}`。
- 响应 `tool_calls` 的 `function.arguments` 用 `json.loads` 解析；失败抛 `LLMProviderError("invalid_tool_arguments")`。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T5-01 | MockProvider 返回脚本中的第一个 tool call（ID/name/arguments 正确） | 单元测试 |
| AC-T5-02 | MockProvider 第二次调用返回第二个响应；两次运行结果一致 | 单元测试 |
| AC-T5-03 | 无 tool call 的响应返回空列表 | 单元测试 |
| AC-T5-04 | DeepSeek adapter 用 fake client 正确映射 messages/tools，并解析 tool_calls | 契约测试 |
| AC-T5-05 | usage 被正确映射；缺失 usage 不崩溃 | 契约测试 |
| AC-T5-06 | 非法 tool arguments JSON 抛 `LLMProviderError` | 契约测试 |
| AC-T5-07 | 缺少 `DEEPSEEK_API_KEY` 时抛清晰错误，不发起网络请求 | 单元测试 |
| AC-T5-08 | 两个 Provider 都满足同一个 `LLMProvider` 行为契约 | 契约测试 |

## 7. 测试计划

### 单元/契约

- `tests/unit/test_mock_provider.py`
  - 顺序响应、tool calls、空响应、确定性。
- `tests/unit/test_deepseek_provider.py`
  - fake OpenAI client：messages/tools 映射、tool_calls 解析、usage、非法 JSON、缺 Key。
- `tests/unit/test_llm_contract.py`
  - 对 Mock/DeepSeek 用同一组断言（响应结构、tool call ID、arguments dict）。

### 集成

- T6 用 MockProvider 的 fixture 脚本跑完整循环。
- 不调用真实 DeepSeek。

### 可选 live

- 手动设置 `DEEPSEEK_API_KEY`，运行一次 `provider.complete`；不进入 CI/T8 验收。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| OpenAI SDK API 变化 | `chat.completions.create` 字段可能变化 | 锁定版本；adapter 隔离；契约测试 |
| DeepSeek tool call 格式 | 与 OpenAI 略有差异 | 只依赖标准 `tool_calls` 字段；测试覆盖 |
| 同步调用 | 与 v2 设计的 async 不同 | v0.1 明确同步；后续 MCP/并发时再迁移 |
| 参数 JSON | 模型可能返回非 JSON | 抛清晰错误；T6 作为 Provider 错误处理 |
| 缺 Key | 测试环境无 Key | 测试注入 fake client；live 可选 |

**开放问题**

- 是否在 v0.1 支持 `tool_choice`/强制工具调用？暂不支持；靠 Prompt/脚本。
- 是否记录 raw response？v0.1 只记录 `raw_provider_id`/usage，不保存完整响应。
- DeepSeek `deepseek-reasoner` 是否支持 tool calling？v0.1 只用 `deepseek-chat`。
- MockProvider 脚本格式是否需要 YAML？v0.1 用 JSON，简单可验证。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_mock_provider.py tests/unit/test_deepseek_provider.py tests/unit/test_llm_contract.py -q
```

## 10. 实现验证结果

| 日期 | 命令 | 结果 |
|---|---|---|
| 2026-10-21 | `uv run pytest tests/unit/test_mock_provider.py tests/unit/test_deepseek_provider.py tests/unit/test_llm_contract.py -q` | 14 passed |
| 2026-10-21 | `uv run pytest -q` | 79 passed |
| 2026-10-21 | `uv run ruff check .` | All checks passed |
| 2026-10-21 | `uv run mypy src` | Success: no issues found in 27 source files |
| 2026-10-21 | Provider 契约 | Mock/DeepSeek 均返回 canonical `LLMResponse`/`ToolCall`；DeepSeek 测试使用 fake client，无真实网络/Key |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T5 spec；定义 Provider 契约、Mock 脚本、DeepSeek 适配和验收标准 |
| 2026-10-21 | T5 实现完成；canonical 类型、MockProvider、DeepSeek adapter、契约测试落地 |
