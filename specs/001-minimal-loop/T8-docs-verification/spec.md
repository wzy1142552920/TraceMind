# T8 — 文档、Demo 与最终验证 Spec

- **任务 ID**：T8
- **状态**：draft
- **依赖**：T1–T7
- **下游**：无（v0.1 交付）
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T7 完成后，需要让项目对外可理解、可演示、可复核：README 能快速启动，Demo 能复现，验收矩阵能把每个 AC 映射到测试/命令，已知限制写清楚，原始设计文档保持不动。

**用户故事**：作为评审者，我可以按 README 在几分钟内跑通 Demo，看到报告、证据和运行产物，并知道 v0.1 不包含什么。

## 2. In scope

- 根目录 `README.md`：定位、最小循环图、快速开始、Demo、产物、限制、v0.1 与 v2 差异。
- 验收矩阵：T1–T7 的 AC 对应测试/命令/证据。
- Demo 脚本与演示步骤。
- 文档一致性检查：8 个 spec/task、链接、术语、契约一致。
- 已知限制与后续迭代说明。
- 原始设计文档未被修改的检查。

## 3. Out of scope

- 新增功能/代码（T8 只做文档与最终验证）。
- v2 全量功能（SQLite/FTS5、OTel、远程 MCP、6 fixture、ablation、Web UI）。
- 发布、CI/Docker。
- 真实生产环境验证。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T8-01 | README 包含快速开始、Demo 命令、产物说明、限制 | must |
| FR-T8-02 | README 说明 v0.1 与 v2 设计的差异/deferred 列表 | must |
| FR-T8-03 | 建立 T1–T7 AC → 测试/命令/证据的验收矩阵 | must |
| FR-T8-04 | 8 个 spec/task 文档齐全、链接有效、术语一致 | must |
| FR-T8-05 | Demo 可离线运行（MockProvider） | must |
| FR-T8-06 | 记录已知限制：单日志 pattern、tree-sitter、本地单仓库、无远程/OTel | must |
| FR-T8-07 | 原始 `docs/TraceMind_Agent_System_Design*.md` 未被修改 | must |
| FR-T8-08 | 不伪造测试结果；未执行项明确标注 | must |

## 5. 接口/数据契约

### README 结构

```text
# TraceMind
1. 项目定位
2. v0.1 最小循环
3. 快速开始
4. Demo
5. 运行产物
6. 架构/目录
7. 评估与验收
8. 已知限制
9. v0.1 vs v2
10. 后续计划
```

### 验收矩阵

| AC | 测试/命令 | 证据 |
|---|---|---|
| T1-AC-... | `pytest ...` / 命令 | 测试输出/运行产物 |
| ... | ... | ... |

- 每个 T1–T7 的 AC 必须有一行。
- 不能只写“见测试”；写具体测试文件/命令。
- 未执行项标注“未执行”，不能写“通过”。

### Demo

主命令：

```bash
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

可选 live：

```bash
export DEEPSEEK_API_KEY=...
uv run tracemind diagnose ... --provider deepseek
```

### 已知限制（至少包含）

- 单文本日志 pattern；不支持 JSON 日志/多文件。
- 单仓库内存索引；无 SQLite/FTS5/增量索引。
- tree-sitter 静态分析；Lombok/AOP/反射不可见。
- 本地只读；无远程 MCP/审批。
- 无 OTel/长期保留；产物为本地 JSONL/JSON/Markdown。
- 6 个 Java fixture、LLM-only ablation 未在 v0.1 实现。
- 合成 fixture，不代表生产验证。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T8-01 | README 快速开始命令可复制执行（mock 路径） | 手动/文档检查 |
| AC-T8-02 | README 的 Demo 命令与 T7 CLI 参数一致 | 文档/CLI 对照 |
| AC-T8-03 | 验收矩阵覆盖 T1–T7 全部 AC | 脚本/人工检查 |
| AC-T8-04 | 8 个 spec.md + 8 个 task.md 存在且链接有效 | `find`/链接检查 |
| AC-T8-05 | 每个 spec 含 FR/AC/测试计划/风险；每个 task 含依赖/步骤/DoD/验证 | 人工检查 |
| AC-T8-06 | Mock Demo 可离线运行并生成报告 | E2E 命令 |
| AC-T8-07 | 已知限制与 v0.1/v2 差异写清楚 | README 检查 |
| AC-T8-08 | 原始设计文档未修改；未执行项没有写成“通过” | 文件检查/人工检查 |

## 7. 测试计划

### 文档检查

- 链接检查：README ↔ 8 个 spec/task ↔ 父设计文档。
- 术语检查：`tracemind` CLI/包名、`TraceMind` 产品名、状态/工具名/报告 schema 一致。
- 验收矩阵覆盖率：T1–T7 AC 数 vs 矩阵行数。
- 占位符检查：无 `TODO`/`TBD`/空章节；未执行项明确标注。

### 命令检查

- `uv run tracemind diagnose ... --provider mock` 退出 0。
- 运行产物 5 类齐全。
- 报告引用校验通过。
- `uv run pytest -q`、`ruff check`、`mypy src` 通过（实现阶段）。

### 文件检查

- `docs/TraceMind_Agent_System_Design.md` 与 v2 文档的 mtime/大小未变化（文档阶段）。
- 没有修改 `pyproject.toml`（文档阶段）。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 文档与实现漂移 | README/AC 与代码不完全一致 | T8 最终验证；每个 task 回填结果 |
| Demo 依赖网络/API Key | live DeepSeek 不可用 | 默认 Mock；live 可选 |
| 验收矩阵形式化 | 只写“见测试” | 要求具体测试文件/命令/输出 |
| 样本量小 | v0.1 只跑通一个 fixture | 明确回归/演示定位，不宣称生产准确率 |
| 原始文档误改 | 文档阶段要求不变 | 文件检查 |

**开放问题**

- README 是否需要截图/GIF？v0.1 用文字/命令；后续可选。
- 是否把验收矩阵放在 README 还是单独文档？建议 README 摘要 + `specs/001-minimal-loop/ACCEPTANCE.md` 详细矩阵。
- 是否需要 CI？v0.1 不做；后续补 GitHub Actions。

## 9. 验证命令

```bash
find specs/001-minimal-loop -name spec.md | wc -l
find specs/001-minimal-loop -name task.md | wc -l
uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T8 spec；定义 README、验收矩阵、Demo、限制和最终验证 |
