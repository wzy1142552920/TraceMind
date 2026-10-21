# T1 — Provider 配置、`.env` 与 preflight Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T1
- **状态**：implemented
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6

## 1. 实施顺序

> T1 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T1 spec 和 v0.2 README，确认 `.env` 优先级、preflight 时点和配置字段。
   - 确认不修改 v0.1 的 Mock 行为或 001 docs。

2. **先写配置/CLI 测试**
   - `tests/unit/test_llm_config.py`：`.env` 加载、env 覆盖、CLI 覆盖、默认值/校验。
   - `tests/e2e/test_live_preflight.py`：缺 Key exit 2、无输出目录、错误提示；Mock 不受影响。
   - 测试先失败。

3. **实现配置层**
   - 新增 `src/tracemind/llm/config.py`：`LLMSettings`、`load_project_env()`、`resolve_settings()`、`require_api_key()`。
   - 添加 `python-dotenv` 依赖。
   - 所有数值校验；CLI 参数默认 `None` 以区分“未指定”。
   - 不提供 `--api-key`。

4. **接入 CLI/provider**
   - CLI 增加 `--model`、`--base-url`、`--llm-timeout`、`--llm-max-retries`、`--llm-max-tokens`、`--max-repair-attempts`。
   - 选择 deepseek 后立即 `load_project_env()` + preflight；失败打印明确信息并 exit 2。
   - 用 settings 构造 `DeepSeekProvider`；Mock 分支不要求 Key。
   - run.json 写入脱敏 LLM 配置。

5. **`.env` 文件**
   - 新增 `.env.example`（占位符）。
   - `.gitignore` 增加 `!.env.example`，确保 `.env` 仍被忽略。
   - 不在任何文档中写入真实 Key。

6. **验证并回填**
   - 运行 T1 验证命令；回填 task §6 和 spec 变更记录。

## 2. 交付物

- [x] `src/tracemind/llm/config.py`
- [x] `src/tracemind/llm/deepseek.py` 使用 settings
- [x] `src/tracemind/cli/main.py` 新参数 + preflight
- [x] `src/tracemind/storage/run_store.py` / CLI run_meta 脱敏配置
- [x] `.env.example`
- [x] `.gitignore` 例外
- [x] `tests/unit/test_llm_config.py`
- [x] `tests/e2e/test_live_preflight.py`
- [x] 相关 provider/CLI/run-store 测试更新

## 3. Definition of Done

- [x] AC-T1-01 至 AC-T1-08 全部满足。
- [x] `.env` 可用，真实 env 优先，CLI 覆盖，默认值可预测。
- [x] 缺 Key 在解析/索引/建目录前退出 2，不创建 run 目录。
- [x] run.json 有脱敏配置，无 Key/`sk-`。
- [x] Mock 全量测试与 E2E 不变。
- [x] 不修改 001 specs / docs 设计文档。

## 4. 验证命令

```bash
uv sync
uv run pytest tests/unit/test_llm_config.py tests/e2e/test_live_preflight.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **CLI 默认值**：参数默认必须为 `None`，否则无法区分“未指定”和默认值。
- **`.env` 搜索**：使用 `find_dotenv()`；文档要求从项目根运行。
- **preflight 顺序**：必须在 `LogParser`/`TreeSitterJavaIndex`/`RunStore` 之前。
- **Secret**：只保存配置名，不保存 Key；测试扫描 run.json/events/report/audit。
- **Mock**：`--provider mock` 不读取 Key，不要求 `.env`。
- **数值校验**：timeout > 0、max_tokens > 0、retries/repair 0..5。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | T1 专项 pytest | 21 passed | config/preflight/provider |
| 2026-10-21 | Claude | `uv run pytest -q` | 126 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 36 source files | — |
| 2026-10-21 | Claude | 无 Key deepseek CLI | 退出 2；无输出目录 | 提示 `.env`/环境变量 |
| 2026-10-21 | Claude | `.env` ignore 检查 | `.env` ignored；`.env.example` unignored | 提交后 tracked |
| 2026-10-21 | Claude | 默认模型/thinking | `deepseek-flash` + thinking disabled | provider tests |
