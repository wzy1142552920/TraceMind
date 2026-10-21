# T5 — LLM Provider 与 Mock/DeepSeek Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T5
- **状态**：implemented
- **依赖**：T1
- **下游**：T6

## 1. 实施顺序

> T5 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T5 `spec.md`，确认 canonical 类型、Mock 脚本格式、DeepSeek 映射规则。
   - 确认 T6 只依赖 `LLMProvider`，不依赖 OpenAI SDK 类型。

2. **定义 canonical 类型**
   - `src/tracemind/llm/messages.py`：Message、ToolDefinition、ToolCall、Usage、LLMResponse、ProviderCapabilities。
   - `src/tracemind/llm/provider.py`：LLMProvider Protocol、LLMProviderError。
   - 所有类型可用 Pydantic 或 dataclass；不要泄漏 Provider 类型。

3. **先写契约测试**
   - `tests/unit/test_llm_contract.py`：统一断言（响应结构、tool call ID、arguments dict）。
   - `tests/unit/test_mock_provider.py`：顺序/确定性/空 tool calls。
   - `tests/unit/test_deepseek_provider.py`：fake client 映射、usage、非法 JSON、缺 Key。
   - 测试先失败。

4. **实现 MockProvider**
   - 读取 JSON 脚本（list[dict]）。
   - 每次 `complete` 按顺序返回；脚本用尽后返回空响应或明确错误（选择一种并测试）。
   - 不读取 fixture 日志/源码；不内置答案。

5. **实现 DeepSeekProvider**
   - 构造 `OpenAI(api_key=os.environ[api_key_env], base_url=base_url)`。
   - 允许注入 fake client（构造器参数）用于测试。
   - 映射 messages/tools；调用 `chat.completions.create`。
   - 解析 response content/tool_calls/usage/finish_reason。
   - 非法 arguments JSON 抛 `LLMProviderError`。
   - 缺 Key 时构造/调用前抛清晰错误。

6. **验证并回填**
   - 运行 T5 spec 的验证命令，回填 §6。
   - 不进行真实网络调用。

## 2. 交付物

- [x] `src/tracemind/llm/__init__.py`
- [x] `src/tracemind/llm/messages.py`
- [x] `src/tracemind/llm/provider.py`
- [x] `src/tracemind/llm/mock.py`
- [x] `src/tracemind/llm/deepseek.py`
- [x] `src/tracemind/llm/schemas.py`（如需要）
- [x] `tests/unit/test_llm_contract.py`
- [x] `tests/unit/test_mock_provider.py`
- [x] `tests/unit/test_deepseek_provider.py`
- [x] `tests/fixtures/mock_responses.json`（测试脚本）

## 3. Definition of Done

- [x] T5 spec 的 AC-T5-01 至 AC-T5-08 全部满足。
- [x] MockProvider 确定性；两次运行结果一致。
- [x] DeepSeek adapter 通过 fake client 契约测试，不依赖真实 Key/网络。
- [x] 领域层只看到 canonical 类型。
- [x] 错误路径（非法 JSON/缺 Key）有清晰错误，不崩溃。
- [x] 不引入异步/流式/Claude 实现。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_llm_contract.py tests/unit/test_mock_provider.py tests/unit/test_deepseek_provider.py -q
```

## 5. 开放问题 / 风险

- **中文 Prompt/响应**：DeepSeek 返回中文内容时，content 按原样保留；不假设英文。
- **tool call arguments**：DeepSeek/OpenAI 可能返回空字符串/None；定义为空 dict 还是错误？建议空字符串→`{}`，非法 JSON→错误。
- **Mock 脚本耗尽**：已实现为返回空响应（`tool_calls=[]`，`finish_reason="stop"`）；测试覆盖。
- **Provider 错误**：v0.1 只抛 `LLMProviderError`，不实现重试；T6 捕获后终止/记录。
- **API Key 检查**：实现为调用前检查；测试通过 fake client 注入，不读取真实 Key。
- **同步调用**：v0.1 已明确同步；后续 MCP/并发时再迁移。
- **usage 字段**：不同 Provider 可能缺失；保持 Optional，不伪造 0。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | `uv run pytest tests/unit/test_mock_provider.py tests/unit/test_deepseek_provider.py tests/unit/test_llm_contract.py -q` | 14 passed | T5 专项 |
| 2026-10-21 | Claude | `uv run pytest -q` | 79 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 27 source files | — |
| 2026-10-21 | Claude | Provider 契约 | Mock/DeepSeek 均满足 canonical 契约 | fake client；无真实网络 |
