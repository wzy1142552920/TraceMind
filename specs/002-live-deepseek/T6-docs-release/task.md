# T6 — 文档、验收与发布 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T6
- **状态**：implemented
- **依赖**：T1–T5
- **下游**：无（v0.2 交付）

## 1. 实施顺序

> T1–T5 已完成；以下步骤已于 2026-10-21 执行。

1. **确认前置**
   - T1–T5 spec/task 已回填验证结果。
   - 确认默认测试、Mock Demo、live gate 状态。

2. **写根 README v0.2**
   - `.env` 示例/优先级/不提交 Key。
   - 离线 Mock 与 live DeepSeek 命令。
   - live gate 命令、retry/repair/usage、报告 schema 0.2。
   - v0.1 → v0.2 差异、限制、BLOCKED 规则。
   - 不宣称未测得的准确率/生产验证。

3. **回填 002 验收**
   - 更新 `specs/002-live-deepseek/ACCEPTANCE.md` 每项 PASS/FAIL/BLOCKED。
   - live 无 Key 时保持 BLOCKED，附命令和原因。
   - 记录日期/环境（不记录 Key）。

4. **版本**
   - pyproject `0.2.0`；`__version__` fallback `0.2.0`。
   - `uv sync` 更新锁/环境。
   - 验证 `tracemind --version`。

5. **最终检查**
   - 6 spec/task 计数（002 下 6/6）。
   - 链接、术语、README 命令。
   - pytest/ruff/mypy/Mock CLI。
   - secret 扫描。
   - 001 specs/docs mtime/size 未变。

6. **交付**
   - 汇总变更文件、测试结果、live 状态、已知缺陷、下一步。
   - 不 commit；用户要求时提交。

## 2. 交付物

- [x] 根 README v0.2
- [x] 002 ACCEPTANCE 回填
- [x] pyproject/uv.lock/`__version__` 0.2.0
- [x] 最终验证记录
- [x] 001/docs 未修改检查
- [x] live 状态（PASS）

## 3. Definition of Done

- [x] AC-T6-01 至 AC-T6-06 全部满足（live 实际 PASS）。
- [x] 002 文档/链接完整。
- [x] README 能复制执行 `.env`/Mock/live 命令。
- [x] 版本 0.2.0。
- [x] 离线测试/ruff/mypy 通过；live 状态如实。
- [x] 001 specs 和 docs 设计文档未修改。
- [x] live AC 为实际运行 PASS（非 BLOCKED）。

## 4. 验证命令

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

## 5. 风险与开放问题

- **live 状态**：无 Key 必须 BLOCKED；有 Key 但失败必须 FAIL，不写 PASS。
- **版本**：pyproject/uv.lock/fallback/实际安装版本一致。
- **README 命令**：与 `--help`/实际 CLI 参数一致。
- **历史文档**：001 specs/docs 不动；v0.2 文档独立。
- **发布**：不自动 tag/push；由用户决定。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | 002 spec/task 计数 + 相对链接 | 6/6；链接有效 | — |
| 2026-10-21 | Claude | `uv sync` / `tracemind --version` | `tracemind 0.2.0` | `uv.lock` 同步 |
| 2026-10-21 | Claude | `uv run pytest -q` | 146 passed, 2 skipped | live 默认跳过 |
| 2026-10-21 | Claude | `ruff check .` / `mypy src` | 通过 / 36 文件 | — |
| 2026-10-21 | Claude | live pytest gate | 2 passed | 真实 `deepseek-flash` |
| 2026-10-21 | Claude | live CLI | `confirmed`；6 证据；三类证据；tokens 1119/170/1289；latency 1328ms | schema 0.2 |
| 2026-10-21 | Claude | secret 扫描 / 001+docs 状态 | 无 secret；未修改 | `git status` 复核 |
