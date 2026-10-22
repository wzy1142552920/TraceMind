# T7 — Live 验证、文档与发布 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T7
- **状态**：implemented（2026-10-22）
- **依赖**：T6
- **下游**：无

## 1. 实施顺序

1. **确认契约**
   - 阅读 T7 spec、[DESIGN §13](../DESIGN.md)、T6 三 case expected。
   - 确认 live 仍是 opt-in；默认 pytest 完全离线。
   - 确认 live 仍使用 Fake verification 数据，报告标注 fixture。
   - 确认 live 断言包含同线程上下文与代码证据，不只检查报告结构。

2. **先写 live 测试骨架**
   - `tests/live/test_live_v03_cases.py` 参数化三 case。
   - 复用现有 live gate/fixtures。
   - 断言结构/同线程上下文/代码证据/接地/fixture 标注/无 secret；Top-1 用宽关键词或证据来源。
   - 缺同线程上下文或代码证据时不得记为 confirmed。
   - 默认 skip；测试先失败/跳过。

3. **跑 live 并调优（只做通用修复）**
   - 使用有界预算（16 iterations / 18 LLM / 24 tools / 2000 output tokens）跑三 case。
   - 若失败，定位是协议/格式/上下文问题，修 prompt/repair/工具描述。
   - 不按 case 写死路径、关键词、答案。
   - 记录实际 model/usage/latency/stop reason、Top-1、同线程上下文和代码证据结果。

4. **CLI 冒烟**
   - 用 T7 spec 命令跑至少一个 case。
   - 检查退出码、5 类产物、schema 0.3、fixture 标注、无 secret。
   - 记录实际结果，不伪造 confirmed。

5. **文档回填**
   - 根 README：v0.3 能力（含同线程日志上下文 + 代码流协同）、三 case、`--verification-data`、命令、限制（仅用户提供日志文件）、测试统计、live 结果。
   - 003 README/ACCEPTANCE：状态/结果回填。
   - T1–T7 spec/task：实现验证结果、变更记录；未达标写 FAIL/BLOCKED。
   - 链接检查。

6. **发布**
   - `pyproject.toml` / `__init__.py` 版本 0.3.0。
   - 如有依赖变化，`uv lock`。
   - `uv run tracemind --version` 校验。
   - `git status` 确认未修改 001/002/docs 设计文档；不提交 `.env`/Key/产物。

7. **最终验证**
   - 离线全量测试、ruff、mypy。
   - live gate（如 Key 可用）。
   - secret scan、链接检查。
   - 回填最终结果。

## 2. 交付物

- [x] `tests/live/test_live_v03_cases.py`
- [x] live CLI 冒烟记录
- [x] 根 README v0.3 更新
- [x] 003 README/ACCEPTANCE 回填
- [x] T1–T7 spec/task 验证结果回填
- [x] `pyproject.toml` / `__init__.py` 0.3.0
- [x] `uv.lock` 同步
- [x] 链接/secret/旧文档检查结果

## 3. Definition of Done

- [x] AC-T7-01 至 AC-T7-13 全部满足；无 BLOCKED/FAIL。
- [x] 默认 pytest 离线、无网络；live 需显式 gate。
- [x] live 三 case 报告结构、同线程上下文、代码证据、fixture 标注、无 secret 通过；Top-1 3/3、Top-3 3/3。
- [x] live CLI 冒烟产物完整、schema 0.3、无 secret。
- [x] README/ACCEPTANCE/T1–T7 文档一致，链接有效。
- [x] 版本 0.3.0 一致。
- [x] 未修改 001/002 specs/docs 设计文档；未提交 Key/`.env`/运行产物。

## 4. 验证命令

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q
uv run tracemind --version
git status --short
```

## 5. 风险与开放问题

- **live 不稳定**：如实记录；不把 Mock 当 live；必要时减少 case/预算并说明。
- **成本**：小预算、小 token；失败及时停止。
- **prompt 过拟合**：expected 不进 prompt；overfit 扫描；live 只看证据/结构。
- **Fake 验证标注**：live 仍是 fixture，README/报告必须说明。
- **上下文漏用**：真实模型可能只看栈；无上下文不得 forced confirmed，live 结果如实降级。
- **发布版本**：pyproject/`__init__`/锁文件/CLI 保持一致。
- **旧文档**：不修改 001/002/docs 设计文档；只在 003 和根 README 回填。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | Claude | `uv run pytest -q` | PASS | 385 passed, 6 skipped |
| 2026-10-22 | Claude | `uv run ruff check .` | PASS | All checks passed |
| 2026-10-22 | Claude | `uv run mypy src` | PASS | 48 source files |
| 2026-10-22 | Claude | `TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v03_cases.py -q -s` | PASS | 4 passed in 65.38s；三 case confirmed，Top-1 3/3、Top-3 3/3 |
| 2026-10-22 | Claude | live CLI 冒烟 | PASS | exit 0；5 类产物；41585 tokens；17308 ms；3 actions；无 secret |
| 2026-10-22 | Claude | `uv run tracemind --version` | PASS | `tracemind 0.3.0` |
| 2026-10-22 | Claude | 链接/secret/旧文档检查 | PASS | 旧 docs/001/002 未修改；产物无 Key/`sk-` |

### 6.1 live 三 case 记录

模型 `deepseek-flash`；Fake verification backend；预算 16/18/24/2000。

| Case | 状态 | Top-1 | Top-3 | LLM calls | Tools | Total tokens | Latency |
|---|---|---|---|---|---|---|---|
| `v03-c1-missing-row` | confirmed | hit | hit | 11 | 15 | 74,918 | 23.8s |
| `v03-c2-duplicate-callback` | confirmed | hit | hit | 7 | 11 | 41,548 | 17.6s |
| `v03-c3-mapper-stub` | confirmed | hit | hit | 11 | 17 | 71,296 | 23.8s |

live 非确定性；上表是 2026-10-22 通过完整 gate 的一次记录，不代表生产准确率。调优只修复通用协议/上下文/接地问题，未按 case 写死路径或答案。
