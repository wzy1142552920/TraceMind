# T1 — 工程骨架 Spec

- **任务 ID**：T1
- **状态**：implemented
- **依赖**：无
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

仓库目前只有 `pyproject.toml`（`tracemind`，Python >=3.12，无依赖）、`.venv` 和设计文档。需要先建立可安装、可运行、可测试的 Python 工程骨架，为 T2–T7 提供稳定的包结构、CLI 入口和工具链。

**用户故事**：作为开发者，我可以在干净环境中执行 `uv sync`，然后用 `uv run tracemind --help` 看到 CLI 命令，并用 `pytest` 开始写测试。

## 2. In scope

- 更新 `pyproject.toml`：项目元数据、依赖、console script、pytest/ruff/mypy 配置。
- 创建 `src/tracemind/` 包骨架和空模块目录（只放 `__init__.py`，不写业务逻辑）。
- 创建 Typer CLI 入口，至少提供 `--help`、`--version` 和 `diagnose` 命令占位。
- 创建 `tests/unit/`、`tests/integration/`、`tests/e2e/` 和 `tests/conftest.py` 骨架。
- 创建/确认 T1–T8 的 spec/task 目录链接。
- 定义依赖版本策略：使用 `uv.lock` 锁定，不写死未验证的精确版本。

## 3. Out of scope

- 日志解析、源码索引、工具执行、LLM 调用、Agent 循环、报告生成。
- 真实 DeepSeek API 调用。
- 配置文件系统（v0.1 先用 CLI 参数）。
- SQLite、OTel、远程 MCP、审批。
- 打包发布、CI、Docker。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T1-01 | Python 版本 >=3.12；包名 `tracemind`；版本从 `__init__`/包元数据读取 | must |
| FR-T1-02 | 依赖：`typer`、`rich`、`pydantic`、`tree-sitter`、`tree-sitter-java`、`openai` | must |
| FR-T1-03 | 开发依赖：`pytest`、`pytest-cov`、`ruff`、`mypy` | must |
| FR-T1-04 | console script：`tracemind = "tracemind.cli.main:app"`（或等价 Typer 入口） | must |
| FR-T1-05 | `tracemind --help` 显示 `diagnose` 命令；`tracemind --version` 输出版本 | must |
| FR-T1-06 | 包结构包含 `core`、`log_analysis`、`indexing`、`tools`、`llm`、`diagnosis`、`workspace`、`observability`、`storage` 目录 | must |
| FR-T1-07 | pytest、ruff、mypy 配置可在 `pyproject.toml` 中运行 | must |
| FR-T1-08 | T1–T8 的 `spec.md`/`task.md` 存在且互相链接 | must |

**依赖说明**

- v0.1 使用同步调用；不引入 `pytest-asyncio`、`respx`、`tenacity`、`pydantic-settings`。T7 报告模板追加使用 Jinja2。
- DeepSeek adapter 使用官方 `openai` SDK；测试不依赖真实 API Key。
- tree-sitter-java 的 wheel 兼容性需要在 T1 安装时验证；失败则记录风险，T3 使用同接口兜底。

## 5. 接口/数据契约

### CLI

```text
tracemind --help
tracemind --version
tracemind diagnose --help
```

`diagnose` 的具体参数（`--log`、`--repo`、`--service`、`--provider`）在 T7 完整实现；T1 只需命令占位和帮助文本。

### 包结构

```text
src/tracemind/
  __init__.py
  cli/main.py
  core/
  log_analysis/
  indexing/
  tools/
  llm/
  diagnosis/
  workspace/
  observability/
  storage/
tests/
  conftest.py
  unit/
  integration/
  e2e/
```

### pyproject 契约

- `[project].name = "tracemind"`
- `[project].requires-python = ">=3.12"`
- `[project.scripts].tracemind = "tracemind.cli.main:app"`
- 依赖与开发依赖分组；使用 `uv` 生成锁文件。
- `[tool.pytest.ini_options]`：`testpaths = ["tests"]`。
- `[tool.ruff]`：target-version py312；line-length 100。
- `[tool.mypy]`：Python 3.12；允许渐进类型。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T1-01 | `uv sync` 在干净环境成功，生成/使用 `uv.lock` | 命令退出码 0 |
| AC-T1-02 | `uv run tracemind --help` 退出码 0，输出包含 `diagnose` | CLI smoke test |
| AC-T1-03 | `uv run tracemind --version` 输出版本号 | CLI smoke test |
| AC-T1-04 | `uv run pytest --collect-only -q` 退出码 0 | 测试收集 |
| AC-T1-05 | `uv run ruff check .` 无配置错误 | 命令退出码 0 |
| AC-T1-06 | `uv run mypy src` 无配置错误 | 命令退出码 0 |
| AC-T1-07 | T1–T8 的 spec/task 文档齐全、链接可解析 | 文档检查 |
| AC-T1-08 | 原始设计文档未被修改 | 文件检查 |

## 7. 测试计划

### 单元

- `tests/unit/test_cli.py`：使用 Typer `CliRunner` 验证 `--help`、`--version`、`diagnose --help`。
- `tests/unit/test_package.py`：导入 `tracemind`，检查版本和包路径。

### 集成/E2E

- 本任务不涉及业务 E2E；只做 CLI smoke。

### 工具链

- `pytest --collect-only`、`ruff check`、`mypy src` 必须可运行。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| tree-sitter-java wheel 兼容性 | Python 3.12/macOS 可能安装失败 | **已验证**：tree-sitter 0.26.0 + tree-sitter-java 0.23.5 可导入并解析 Java；T3 仍保留同接口 fallback |
| 依赖版本漂移 | OpenAI/Typer/Pydantic 版本变化 | 使用 `uv.lock`；不写死未验证版本 |
| 过早引入业务依赖 | T1 只需要骨架 | 依赖按需添加；Jinja2 仅在 T7 报告模板阶段追加，不引入 Tenacity 等 |

**开放问题**

- 是否需要在 T1 就加入 `pydantic-settings`？v0.1 用 CLI 参数，暂不加入。
- 是否需要 CI 配置？当前阶段不做，T8 可补充。
- tree-sitter-java 的导入 API 需在实现时确认（`tree_sitter_java.language()`）。

## 9. 验证命令

```bash
uv sync
uv run tracemind --help
uv run tracemind --version
uv run pytest --collect-only -q
uv run ruff check .
uv run mypy src
```

## 10. 实现验证结果

| 日期 | 命令 | 结果 |
|---|---|---|
| 2026-10-21 | `uv sync` | 成功；安装 36 个包，生成 `uv.lock` |
| 2026-10-21 | `uv run tracemind --help` | 退出码 0；输出包含 `diagnose` |
| 2026-10-21 | `uv run tracemind --version` | 输出 `tracemind 0.1.0` |
| 2026-10-21 | `uv run pytest --collect-only -q` | 14 tests collected |
| 2026-10-21 | `uv run pytest -q` | 14 passed |
| 2026-10-21 | `uv run ruff check .` | All checks passed |
| 2026-10-21 | `uv run mypy src` | Success: no issues found in 12 source files |
| 2026-10-21 | tree-sitter-java import check | `tree-sitter 0.26.0` + `tree-sitter-java 0.23.5`；Java 解析成功 |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T1 spec；定义工程骨架、依赖、CLI、验收标准 |
| 2026-10-21 | T1 实现完成；pyproject/依赖/CLI/测试骨架落地，所有验收命令通过 |
| 2026-10-21 | T7 追加 Jinja2 依赖用于报告模板；同步更新 T1 依赖说明与风险记录 |
