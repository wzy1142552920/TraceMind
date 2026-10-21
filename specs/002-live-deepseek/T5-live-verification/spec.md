# T5 — Opt-in Live Verification Spec

- **任务 ID**：T5
- **状态**：implemented（live verification BLOCKED：无 Key）
- **依赖**：T1–T4
- **下游**：T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.1 的测试完全离线；DeepSeek adapter 没有真实调用。v0.2 需要 opt-in live 测试验证真实 Key、网络、tool calling、usage、报告和 secret 安全，同时不能让默认测试/CI 依赖网络或产生费用。

**用户故事**：作为维护者，我可以在设置了 Key 的环境显式运行 live 测试；默认 `pytest` 完全离线；没有 Key 时 live AC 明确 BLOCKED，而不是伪造通过。

## 2. In scope

- 注册 pytest `live` marker。
- `tests/conftest.py` 增加 `--run-live` 和 gate：
  - 只有 `--run-live` + `TRACEMIND_LIVE_TESTS=1` + 非空 Key（env 或 `.env`）才运行 live。
  - 否则 skip，并说明原因。
- `tests/live/test_live_deepseek.py`：
  - adapter smoke：真实 `complete`，返回 canonical response + usage。
  - CLI live：fixture → 5 类产物、report schema 0.2、confirmed、三类证据、至少一个 tool call、usage/latency、无 Key/`sk-`。
- 成本控制：建议 `--max-iterations 4 --max-tool-calls 6 --llm-max-tokens 800`。
- 默认 pytest 不访问网络。

## 3. Out of scope

- 把 live 测试放入默认 CI。
- 多 fixture/统计评估。
- 真实远程工具。
- 价格账单/多模型对比。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T5-01 | 注册 `live` marker | must |
| FR-T5-02 | 默认 pytest skip live，不网络 | must |
| FR-T5-03 | `--run-live + TRACEMIND_LIVE_TESTS=1 + Key` 才运行 | must |
| FR-T5-04 | live adapter + CLI 测试与结构断言 | must |
| FR-T5-05 | 无 Key 时明确 skip/BLOCKED | must |
| FR-T5-06 | live 产物无 Key/`sk-` | must |

## 5. 接口/数据契约

### Gate

```text
run_live = --run-live AND TRACEMIND_LIVE_TESTS=1 AND key non-empty
```

- Key 来源：真实环境变量或项目 `.env`（T1 loader）。
- skip 原因包含缺少哪个条件，但不打印 Key。
- marker：`live: requires network and DEEPSEEK_API_KEY`。

### Live 测试

`tests/live/test_live_deepseek.py`：

1. `test_live_adapter`：
   - 构造 DeepSeekProvider（settings）。
   - `complete` 一个简单消息 + 工具 schema。
   - 断言 `LLMResponse`、至少一个 tool call 或文本、usage 存在/可为空、request id/attempts。
2. `test_live_cli_fixture`：
   - 调用 CLI `--provider deepseek`，fixture 日志/仓库，输出临时目录。
   - 断言退出 0、5 产物、schema 0.2、`validation.citations_valid`、confirmed/probable、三类证据、至少一个 tool call、LLM records/tokens/latency。
   - 扫描 run 目录无 `DEEPSEEK_API_KEY` 或 `sk-`。

- live 断言不硬编码唯一自然语言答案；允许模型选择不同合法工具。
- 如果模型在预算内未 confirmed，测试失败并保留 run 目录供排查；不能把失败改成 PASS。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T5-01 | 默认 pytest skip live，不网络 | `uv run pytest -q`；skip 输出 |
| AC-T5-02 | 仅完整 gate 运行 live | conftest gate tests |
| AC-T5-03 | live adapter canonical response + usage | `tests/live/test_live_deepseek.py`；当前无 Key → BLOCKED |
| AC-T5-04 | live CLI 5 产物/schema 0.2/三类证据/usage/无 secret | live CLI test；当前无 Key → BLOCKED |
| AC-T5-05 | 无 Key 时 BLOCKED，不写 PASS | skip 输出 + ACCEPTANCE 记录 |

## 7. 测试计划

- 新增 `tests/live/test_live_deepseek.py`（`pytestmark = pytest.mark.live`）。
- `tests/conftest.py`：参数/gate/collection hook。
- 默认测试中增加 gate 单元测试（不调用 live）。
- live 测试只在显式命令下运行。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 费用/网络 | live 调用产生成本/不稳定 | 默认 skip；预算/小 tokens；仅人工 |
| 模型非确定性 | 可能不调用工具/不 confirmed | T4 repair；失败保留 artifacts；不硬编码答案 |
| Key 泄漏 | 测试输出/artifacts | 不打印 Key；secret scan |
| CI 误跑 | 环境变量误设 | 必须 `--run-live` + `TRACEMIND_LIVE_TESTS=1` |
| 无 Key | 当前规划环境无 Key | 标记 BLOCKED；不得 PASS |

**开放问题**

- 是否在 CI 中跑 live？不做。
- live 失败是否允许重试？由 T2+T4 控制；测试本身不额外重试。
- 是否记录 live 成本？v0.2 记录 tokens；不做价格估算。

## 9. 验证命令

```bash
uv run pytest -q   # live skipped
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| 2026-10-21 | 默认 `uv run pytest -q` | 145 passed；2 live skipped |
| 2026-10-21 | `TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q` | 2 skipped（无 Key）；145 deselected；无网络 |
| 2026-10-21 | `ruff check .` / `mypy src` | 通过；36 个源文件 |
| 2026-10-21 | live adapter/CLI | **BLOCKED**：当前无 `DEEPSEEK_API_KEY` |
| 2026-10-21 | gate | `--run-live` + env flag + Key 三重条件生效 |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T5 spec；定义 live marker/gate、adapter/CLI live 测试和 BLOCKED 规则 |
| 2026-10-21 | T5 实现完成；默认 skip/gate/skip 行为验证；真实 live 待 Key 后运行 |
