# T1 — 工程骨架 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T1
- **状态**：implemented
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6、T7、T8

## 1. 实施顺序

> T1 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T1 `spec.md` 和 v2 设计文档 §4.3–§4.4。
   - 确认依赖列表和包结构没有遗漏 T2–T7 所需模块。

2. **更新 `pyproject.toml`**
   - 设置项目元数据、`requires-python`、依赖、开发依赖。
   - 添加 console script：`tracemind = "tracemind.cli.main:app"`。
   - 添加 pytest/ruff/mypy 配置。
   - 使用 `uv lock`/`uv sync` 生成锁文件。

3. **创建包骨架**
   - 创建 `src/tracemind/__init__.py` 和 T1 spec 中列出的子包。
   - 每个子包只放 `__init__.py`，不写业务逻辑。
   - 创建 `tests/conftest.py`、`tests/unit/`、`tests/integration/`、`tests/e2e/`。

4. **创建 CLI 入口**
   - `src/tracemind/cli/main.py`：Typer app、`--version`、`diagnose` 占位命令。
   - `diagnose --help` 显示 T7 会实现的参数占位；T1 不实现业务逻辑。
   - 占位命令运行时返回明确的“not implemented”错误，不伪造结果。

5. **写 smoke tests**
   - `tests/unit/test_cli.py`：`--help`、`--version`、`diagnose --help`。
   - `tests/unit/test_package.py`：包可导入、版本存在。

6. **验证**
   - 执行 T1 spec 的验证命令；把结果回填到本文档。

## 2. 交付物

- [x] `pyproject.toml` 更新（依赖、脚本、工具配置）
- [x] `uv.lock`（由 `uv sync` 生成）
- [x] `src/tracemind/__init__.py`
- [x] `src/tracemind/cli/main.py`
- [x] 子包 `__init__.py`（`core`、`log_analysis`、`indexing`、`tools`、`llm`、`diagnosis`、`workspace`、`observability`、`storage`）
- [x] `tests/conftest.py`、`tests/unit/test_cli.py`、`tests/unit/test_package.py`
- [x] `tests/integration/`、`tests/e2e/` 目录
- [x] T1–T8 spec/task 目录和 README 链接（文档阶段已完成）

## 3. Definition of Done

- [x] T1 spec 的 AC-T1-01 至 AC-T1-08 全部满足。
- [x] `uv sync`、`tracemind --help`、`tracemind --version`、`pytest --collect-only`、`ruff check`、`mypy src` 均通过。
- [x] 包结构可被 T2–T7 直接扩展，无需移动目录。
- [x] 没有业务逻辑进入 T1；`diagnose` 占位不返回假报告。
- [x] 原始设计文档未被修改。

## 4. 验证命令

```bash
uv sync
uv run tracemind --help
uv run tracemind --version
uv run pytest --collect-only -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **tree-sitter-java 安装**：已验证 `tree-sitter 0.26.0` + `tree-sitter-java 0.23.5` 可导入并解析 Java；T3 仍保留同接口 fallback。
- **typer 入口**：确认 `app` 可直接作为 console script；若 Typer 版本要求包装函数，改用 `main()`。
- **版本号**：从 `tracemind.__version__` 读取；避免在 CLI 和 pyproject 重复维护。
- **是否引入 `pydantic-settings`**：v0.1 不引入；配置由 CLI 参数传入。
- **是否创建 `configs/`**：暂不创建；T7 再评估。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | `uv sync` | 成功 | 安装 36 个包，生成 `uv.lock` |
| 2026-10-21 | Claude | `uv run tracemind --help` | 退出码 0 | 输出包含 `diagnose` |
| 2026-10-21 | Claude | `uv run tracemind --version` | `tracemind 0.1.0` | — |
| 2026-10-21 | Claude | `uv run pytest --collect-only -q` | 14 tests collected | — |
| 2026-10-21 | Claude | `uv run pytest -q` | 14 passed | — |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 12 source files | — |
| 2026-10-21 | Claude | tree-sitter-java import check | 成功 | `tree-sitter 0.26.0` / `tree-sitter-java 0.23.5` |
