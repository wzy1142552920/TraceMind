# T6 — 文档、验收与发布 Spec

- **任务 ID**：T6
- **状态**：draft
- **依赖**：T1–T5
- **下游**：无（v0.2 交付）
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.2 索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T5 完成后，需要让 v0.2 可理解、可复现、可复核：README 解释 `.env`、配置优先级、live 命令、retry/repair/usage；验收矩阵如实记录 live 是否执行；版本号、文档链接和 v0.1 历史文档保持一致。

**用户故事**：作为评审者，我可以从 README 快速配置 `.env` 并看到 live 测试/CLI 的真实状态；没有 Key 时文档明确 BLOCKED；v0.1 文档仍可访问。

## 2. In scope

- `specs/002-live-deepseek/README.md` 和 `ACCEPTANCE.md`（已在文档阶段创建，实施后回填结果）。
- T1–T6 spec/task 完整性检查。
- 根 `README.md` 更新 v0.2：
  - `.env` 配置、优先级、live 命令。
  - retry/repair/usage、报告 schema 0.2。
  - v0.1 → v0.2 差异、已知限制。
- 包版本 `0.2.0`（pyproject + `__version__` fallback）。
- 最终验证：离线测试、ruff、mypy、链接、secret、001/docs 未修改。
- live 状态如实记录（PASS/FAIL/BLOCKED）。

## 3. Out of scope

- 新功能/新工具/新 fixture。
- live CI、发布 PyPI、Docker。
- 修改 001 specs 或 docs 设计文档。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T6-01 | 002 README/ACCEPTANCE/T1–T6 docs 齐全 | must |
| FR-T6-02 | 根 README 记录 `.env`/优先级/live/retry/repair/usage | must |
| FR-T6-03 | 版本升到 0.2.0 | must |
| FR-T6-04 | 离线测试/ruff/mypy 通过，live 状态记录 | must |
| FR-T6-05 | 链接有效，001/docs 设计文档未修改 | must |
| FR-T6-06 | 无 Key 的 live AC 保持 BLOCKED，不伪造 PASS | must |

## 5. 接口/数据契约

### README v0.2 必须包含

- `.env` 示例（占位符）与不提交 Key 的说明。
- 配置优先级 CLI > env > `.env` > 默认。
- 离线 Mock 命令和 live DeepSeek 命令。
- live 测试 gate 命令。
- retry/repair/usage 的简述和限制。
- 报告 schema 0.2 与 5 类 run 产物。
- v0.1 文档链接；v0.2 已知限制。

### 验收状态

- 离线 AC：PASS/FAIL。
- live AC：PASS（实际运行成功）/ FAIL（实际运行失败）/ BLOCKED（无 Key/未开启）。不允许把 skip/BLOCKED 写成 PASS。
- 记录执行日期、命令、环境（是否配置 Key），不记录 Key。

### 版本

- `pyproject.toml` version `0.2.0`。
- `src/tracemind/__init__.py` fallback `0.2.0`（已安装时从 metadata 读取）。
- `uv.lock` 随版本更新。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T6-01 | 002 README + ACCEPTANCE + T1–T6 spec/task 齐全 | `find`/链接检查 |
| AC-T6-02 | 根 README 记录 `.env`/优先级/live/retry/repair/usage | README 检查 |
| AC-T6-03 | 版本 0.2.0 | `tracemind --version` |
| AC-T6-04 | 离线 pytest/ruff/mypy 通过；live 状态如实 | 全量命令 + ACCEPTANCE |
| AC-T6-05 | 链接有效；001/docs 未修改 | 链接检查 + mtime/size |
| AC-T6-06 | 无 Key 时 live AC BLOCKED，不写 PASS | 验收文档审查 |

## 7. 测试计划

- 文档检查：T1–T6 spec/task、README/ACCEPTANCE 链接、术语、状态。
- 命令检查：`uv sync`、pytest、ruff、mypy、CLI mock、live gate skip。
- secret 扫描：run 产物/README 无 Key/`sk-`。
- 文件检查：001 specs 与 docs 设计文档未修改。
- 版本检查：`uv run tracemind --version`。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 文档与实现漂移 | README 与 CLI 参数不一致 | 最终按 `--help`/测试更新 |
| live 结果误报 | 无 Key 仍写通过 | BLOCKED 规则 + 审查 |
| 版本/锁不一致 | pyproject 与 uv.lock/版本 fallback 不同步 | `uv sync`/版本检查 |
| 链接失效 | 002 目录重组 | 链接检查 |
| 001/docs 误改 | 写文档时误改历史 | mtime/size 检查 |

**开放问题**

- README 是否增加截图/GIF？v0.2 用命令/文本。
- 是否发布 PyPI/打 tag？不在 T6；由用户决定。
- live AC 是否允许后续补跑？是，但记录实际状态。

## 9. 验证命令

```bash
find specs/002-live-deepseek -name spec.md | wc -l
find specs/002-live-deepseek -name task.md | wc -l
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run tracemind --version
uv run tracemind diagnose --log fixtures/logs/basic/incident.log --repo fixtures/repos/minimal-order-service --service order-service --provider mock
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T6 spec；定义 README、验收、版本、最终检查与 BLOCKED 规则 |
