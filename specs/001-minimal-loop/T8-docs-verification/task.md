# T8 — 文档、Demo 与最终验证 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T8
- **状态**：implemented
- **依赖**：T1–T7
- **下游**：无（v0.1 交付）

## 1. 实施顺序

> T8 已完成；以下步骤保留作为复现指南。T8 在 T1–T7 完成后执行。

1. **确认前置**
   - 确认 T1–T7 的 spec/task 已完成并回填验证结果。
   - 确认 Demo 命令在 mock 模式可运行。

2. **写根目录 README**
   - 项目定位、最小循环图、快速开始、Demo、产物、架构/目录、验收、限制、v0.1 vs v2、后续计划。
   - 所有命令使用 `tracemind`；不写旧命名。
   - 不宣称未测得的指标。

3. **写验收矩阵**
   - 汇总 T1–T7 的 AC。
   - 每行写具体测试文件/命令/证据。
   - 未执行项标注“未执行”，不写“通过”。

4. **写 Demo 脚本**
   - mock 主路径：日志 + repo + service + provider mock。
   - 展示报告路径、根因、证据 ID、引用。
   - 可选 live DeepSeek：说明需要 Key，不进入验收。

5. **写已知限制**
   - 单日志 pattern、单仓库内存索引、tree-sitter 静态分析、本地只读、无远程/OTel、fixture 规模。
   - 与 v2 设计的 deferred 列表对齐。

6. **文档检查**
   - 8 个 spec/task、链接、术语、契约一致。
   - 无 TODO/TBD/空章节；未执行项明确。
   - 原始设计文档未修改。

7. **最终验证**
   - 运行 E2E、pytest、ruff、mypy（实现阶段）。
   - 回填本文档 §6。

8. **交付**
   - 汇总变更文件、测试结果、已知缺陷、下一步。

## 2. 交付物

- [x] 根目录 `README.md`
- [x] `specs/001-minimal-loop/ACCEPTANCE.md`（详细验收矩阵）
- [x] Demo 步骤/命令
- [x] 已知限制/v0.1 vs v2 对照
- [x] 文档检查记录
- [x] 最终验证结果

## 3. Definition of Done

- [x] T8 spec 的 AC-T8-01 至 AC-T8-08 全部满足。
- [x] README 快速开始/Demo 可复制执行。
- [x] 验收矩阵覆盖 T1–T7 全部 AC，证据具体。
- [x] 8 个 spec + 8 个 task 齐全、链接有效。
- [x] 已知限制和 deferred 列表清楚。
- [x] 原始设计文档未修改；没有把未执行写成通过。
- [x] E2E/测试/静态检查结果已记录。

## 4. 验证命令

```bash
find specs/001-minimal-loop -name spec.md | wc -l
find specs/001-minimal-loop -name task.md | wc -l

uv run tracemind diagnose \
  --log fixtures/logs/basic/incident.log \
  --repo fixtures/repos/minimal-order-service \
  --service order-service \
  --provider mock

uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 开放问题 / 风险

- **验收矩阵位置**：README 放摘要，`ACCEPTANCE.md` 放完整矩阵；避免 README 过长。
- **Demo 网络依赖**：默认 Mock；live 只作可选演示。
- **文档漂移**：T8 必须重新对照 CLI/报告 schema，而不是只复制 T1–T7 文档。
- **未执行项**：文档阶段只生成 spec/task；实现结果必须在后续会话回填，不能提前写“通过”。
- **原始文档**：不修改 `docs/` 下 v1/v2 文档；如果发现设计问题，记录到 spec 的开放问题，不直接改设计文档。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | `find specs/001-minimal-loop -name spec.md \| wc -l` | 8 | — |
| 2026-10-21 | Claude | `find specs/001-minimal-loop -name task.md \| wc -l` | 8 | — |
| 2026-10-21 | Claude | `uv run pytest -q` | 112 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 35 source files | — |
| 2026-10-21 | Claude | Mock CLI Demo | 退出码 0；5 类产物；confirmed | 引用校验 true |
| 2026-10-21 | Claude | 链接检查 | 无断链 | README + specs |
| 2026-10-21 | Claude | 原始设计文档检查 | mtime/size 未变化 | 未被修改 |
