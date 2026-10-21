# T2 — DeepSeek Transport Hardening Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T2
- **状态**：draft
- **依赖**：T1
- **下游**：T3、T4、T5、T6

## 1. 实施顺序

> 当前阶段只生成文档；以下步骤供实现会话执行。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T2 spec、T1 settings 契约和现有 DeepSeek adapter/fake tests。
   - 确认错误码/重试矩阵。

2. **先写 retry 测试**
   - `tests/unit/test_deepseek_retry.py`：429/5xx/timeout/connection/empty、auth/bad/invalid、attempts、sleep 序列、client 构造参数。
   - 用 fake client 和注入 sleep，不访问网络。
   - 测试先失败。

3. **扩展错误模型**
   - `LLMProviderError` 增加 retryable/attempts/status_code/request_id。
   - 保持现有 `.code`/`.message` 兼容。

4. **实现分类/重试**
   - 在 DeepSeek adapter 内分类异常。
   - 关闭 SDK 隐式重试；构造 client 时传 timeout 和 `max_retries=0`。
   - 最多 2 次重试，固定 0.5/1.0s；最终失败抛最新错误。
   - 成功响应带 attempts。
   - 缺 Key 仍为 missing_api_key（防御性）。

5. **验证并回填**
   - 运行 T2 验证命令；回填 task §6 和 spec 变更记录。

## 2. 交付物

- [ ] `src/tracemind/llm/provider.py` 扩展 `LLMProviderError`
- [ ] `src/tracemind/llm/messages.py` `LLMResponse.attempts`
- [ ] `src/tracemind/llm/deepseek.py` 错误分类/重试/client 配置
- [ ] `tests/unit/test_deepseek_retry.py`
- [ ] 更新 `tests/unit/test_deepseek_provider.py`

## 3. Definition of Done

- [ ] AC-T2-01 至 AC-T2-07 全部满足。
- [ ] 429/5xx/timeout/connection/empty 可重试；auth/bad/invalid 不重试。
- [ ] 最多 2 次重试，sleep 0.5/1.0，attempts 正确。
- [ ] SDK `max_retries=0`，timeout 配置生效。
- [ ] 全部测试离线；无真实网络调用。
- [ ] 现有 provider 契约/Mock 测试不回归。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_deepseek_retry.py tests/unit/test_deepseek_provider.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **SDK 异常**：openai 版本变化；用 status_code/类名分类，fake 不依赖内部实现。
- **双重重试**：显式 `max_retries=0`，测试断言构造参数。
- **sleep 测试**：注入 sleep，避免测试变慢。
- **错误信息**：不包含 Key；request_id 可记录。
- **重试边界**：只重试 LLM 调用，不重试工具执行。
- **非重试错误**：认证/参数错误必须立即失败。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | — | 未执行 | 文档阶段 |
