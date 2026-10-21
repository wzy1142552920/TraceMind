# T5 — Opt-in Live Verification Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T5
- **状态**：implemented（live BLOCKED：无 Key）
- **依赖**：T1–T4
- **下游**：T6

## 1. 实施顺序

> T5 已实现；真实 live 仍 BLOCKED（当前无 Key）。以下步骤保留作为复现指南。

1. **确认 spec**
   - 阅读 T5 spec、T1 `.env` loader、T4 repair、T3 usage。
   - 确认默认测试无网络。

2. **先写 gate 测试**
   - conftest `--run-live`/skip 行为。
   - 无 Key、未设 `TRACEMIND_LIVE_TESTS`、未加 `--run-live` 三种 skip。
   - 测试先失败（参数尚不存在）。

3. **实现 gate**
   - `pyproject.toml` 注册 `live` marker。
   - `tests/conftest.py` 增加参数与 collection skip；加载 `.env` 但不打印 Key。
   - 默认 pytest 不收集/运行 live 网络调用（skip）。

4. **写 live 测试**
   - `tests/live/test_live_deepseek.py`：adapter smoke + CLI fixture。
   - 断言 5 产物、schema 0.2、三类证据、tool call、usage/latency、无 secret。
   - 失败保留 artifacts 并给排查路径。
   - 不硬编码自然语言答案。

5. **验证 live 状态**
   - 无 Key：运行 gate 命令，记录 skip/BLOCKED；不写 PASS。
   - 有 Key：运行 live，记录实际结果；失败如实报告。

6. **回填**
   - 更新 task §6 与 ACCEPTANCE 的 live 状态。

## 2. 交付物

- [x] `pyproject.toml` live marker
- [x] `tests/conftest.py` `--run-live`/gate
- [x] `tests/live/test_live_deepseek.py`
- [x] gate 测试
- [x] 验收文档 live 状态

## 3. Definition of Done

- [x] AC-T5-01 至 AC-T5-05 满足；无 Key 的 AC 为 BLOCKED。
- [x] 默认 pytest 不访问网络。
- [x] live gate 三重条件有效。
- [x] live adapter/CLI 断言结构/证据/报告/usage。
- [x] 产物无 Key/`sk-`。
- [x] 失败/跳过输出清晰，不伪造 PASS。

## 4. 验证命令

```bash
uv run pytest -q
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q
```

## 5. 风险与开放问题

- **费用/网络**：只人工运行；默认 skip；限制 tokens/iterations。
- **Key 来源**：环境变量或项目 `.env`；不在聊天中贴 Key。
- **模型非确定性**：T4 repair；测试允许多种合法工具路径，但要求证据/报告结构。
- **无 Key**：live AC 标 BLOCKED；不能写成 PASS。
- **CI**：不默认跑 live；后续可手动 workflow。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | `uv run pytest -q` | 145 passed；2 skipped | live 默认 skip |
| 2026-10-21 | Claude | `TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live -q` | 2 skipped；145 deselected | 无 Key；无网络 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 36 source files | — |
| 2026-10-21 | Claude | live adapter/CLI | BLOCKED | 当前无 `DEEPSEEK_API_KEY` |
