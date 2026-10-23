# T7 — Live、文档与发布 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T7
- **状态**：implemented
- **依赖**：T6
- **下游**：无

## 1. 实施顺序

1. **确认契约**
   - 阅读 T7 spec、[DESIGN §9–§11](../DESIGN.md)、T6 expected。
   - 确认 live 仍 opt-in；默认 pytest 完全离线。
   - 确认不因 live 失败放宽断言/增加 case 特判。

2. **先写 live 测试骨架**
   - `tests/live/test_live_v04_cases.py` 参数化两 case。
   - 复用 live gate/fixtures；预算 18/20/28/2200。
   - 断言结构/artifact/Top-1/Top-3/JVM 证据/引用/接地/无禁止工具。
   - 默认 skip；测试先失败/跳过。

3. **跑 live（如 Key 可用）**
   - 先 CPU case，再 OOM case。
   - 记录 model/usage/latency/stop reason/Top-1/Top-3/证据。
   - 失败先定位通用协议/格式/上下文问题，修 prompt/repair/工具描述。
   - 不按 case 写死路径/关键词/答案；不无限扩预算。
   - 无 Key/网络记 BLOCKED。

4. **CLI 冒烟**
   - 用 CPU case 跑 `--provider mock` + `--artifacts`。
   - 检查退出码 0、5 类产物、schema 0.4、artifacts 段、引用有效、无 secret。
   - 如 Key 可用，再跑一次 deepseek 冒烟并记录实际结果。

5. **文档回填**
   - 根 README：v0.4 能力（JVM 快照/CPU/内存/OOM）、`--artifacts`、两 case、命令、限制（仅用户提供文本快照/无 hprof/JFR/无 MCP/无实时采集）、测试统计、live 结果。
   - 004 README/ACCEPTANCE：状态/结果回填。
   - T1–T7 spec/task：验证结果、变更记录；未达标写 FAIL/BLOCKED。
   - 链接检查；不修改 001/002/003 与 docs 设计文档。

6. **发布**
   - `pyproject.toml` / `__init__.py` 版本 0.4.0。
   - 如有依赖变化，`uv lock`；本版本预期无新增运行时依赖。
   - `uv run tracemind --version` 校验。
   - `git status` 确认未修改禁止文件；不提交 `.env`/Key/产物。

7. **最终验证**
   - 全量离线测试、ruff、mypy。
   - live gate（如可用）。
   - secret scan、链接检查、旧文档检查。
   - 回填最终结果。

## 2. 交付物

- [x] `tests/live/test_live_v04_cases.py`
- [x] live/CLI 冒烟记录
- [x] 根 README v0.4 更新
- [x] 004 README/DESIGN/ACCEPTANCE 回填
- [x] T1–T7 验证结果回填
- [x] `pyproject.toml` / `__init__.py` 0.4.0
- [x] `uv.lock` 同步（如需要）
- [x] 链接/secret/旧文档检查结果

## 3. Definition of Done

- [x] AC-T7-01 至 AC-T7-13 全部满足；未达标如实记录。
- [x] 默认 pytest 离线、无网络；live 需显式 gate。
- [x] live 两 case 结构合法；Top-1 2/2、Top-3 2/2。
- [x] live/CLI 产物 schema 0.4、引用有效、artifact 标注、无 secret。
- [x] README/ACCEPTANCE/T1–T7 文档一致，链接有效。
- [x] 版本 0.4.0 一致。
- [x] 未修改 001/002/003 specs/docs 设计文档；未提交 Key/`.env`/运行产物。

## 4. 验证命令

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v04_cases.py -q -s
uv run tracemind --version
git status --short
```

## 5. 风险与开放问题

- **live 不稳定**：如实记录；不把 Mock 当 live；必要时记 FAIL，不掩盖。
- **成本**：小预算、小 token；失败及时停止。
- **prompt 过拟合**：expected 不进 prompt；overfit 扫描；live 只看证据/结构。
- **artifact 标注**：user_provided 不是 live；README/报告必须说明。
- **快照不足**：真实模型可能只看 CPU/GC 就下结论；无代码机制不得 confirmed，live 结果如实降级。
- **发布版本**：pyproject/`__init__`/锁文件/CLI 保持一致。
- **旧文档**：只在 004 和根 README 回填。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（571 passed, 9 skipped） | 默认离线；9 个 live 测试全部 skip，不访问网络 |
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_prompt_v04.py -q` | PASS（6 passed） | T7 补充的通用 JVM 提示断言 |
| 2026-10-23 | Claude | `uv run ruff check .` | PASS | 全仓无告警 |
| 2026-10-23 | Claude | `uv run mypy src` | PASS（59 source files） | 无类型错误 |
| 2026-10-23 | Claude | `TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v04_cases.py -q -s` | PASS（3 passed, 39.41s） | 两 case confirmed；Top-1/Top-3 2/2；详见 §6.1 |
| 2026-10-23 | Claude | live CLI（CPU case, deepseek） | PASS（exit 0） | schema 0.4；3 artifacts；JVM 证据 5；remediation 3；6 LLM calls；11 tool calls；38,977 tokens；25,416 ms；无 secret/绝对路径 |
| 2026-10-23 | Claude | Mock CLI（CPU + OOM） | PASS（均 exit 0） | schema 0.4；confirmed；artifact refs/validation 全部有效；5 类产物 |
| 2026-10-23 | Claude | `uv run tracemind --version` / pyproject / `__init__.py` / lock | PASS | 均为 `0.4.0` |
| 2026-10-23 | Claude | live gate 缺省运行 | PASS | 未带 `--run-live`/env/Key 时 live 测试 skip |
| 2026-10-23 | Claude | 根 README + 004 specs 相对链接检查 | PASS（18 文件 / 66 链接 / 0 失效） | 锚点与外链跳过 |
| 2026-10-23 | Claude | secret scan（README、004 specs、`.tracemind`、live 产物） | PASS（28 文件） | 实际 Key 0 命中、`sk-` token 0 命中、无用户主目录绝对路径；T1 spec 的 `Authorization: Bearer ...` 为脱敏文档占位符 |
| 2026-10-23 | Claude | 受保护 docs/specs `git status` | PASS | `docs/TraceMind_Agent_System_Design*.md`、`specs/001/002/003` 无变更；`.env` 被 `.gitignore` 忽略且未跟踪 |

### 6.1 Live 实际记录

预算：18 iterations / 20 LLM calls / 28 tool calls / 2200 output tokens；模型 `deepseek-flash`。

| Case | 报告状态 | Top-1 | Top-3 | LLM calls | Tools | Total tokens | Latency | Stop |
|---|---|---|---|---|---|---|---|---|
| `v04-j1-cpu-high` | confirmed | hit | hit | 6 | 9 | 38,430 | 16,726 ms | `evidence_sufficient` |
| `v04-j2-memory-oom` | confirmed | hit | hit | 7 | 12 | 38,478 | 22,594 ms | `evidence_sufficient` |

- 两 case 的 Top-1 均为 `hyp_001/confirmed`；artifact 引用、标注、sources verified、validation flags、remediation 证据绑定全部通过 live 断言。
- OOM case 出现一次 `HYPOTHESIS_NOT_GROUNDED` 控制调用，被有界修复后继续；未发生失败的只读工具调用。
- CPU case 未出现 dedupe rejection；测试仍将 `DUPLICATE_CALL` 视为确定性去重拒绝而非工具失败，并单独打印。
- live 报告不含 Key、`sk-`、`DEEPSEEK_API_KEY` 或用户主目录绝对路径。

### 6.2 调试记录（如实保留）

1. 首次 live CPU run 为 `insufficient_data`：模型把“远程阻塞”和“JVM 压力”合并为一个候选，首轮遗漏 CPU-bound 应用代码机制。补充通用 JVM 首轮差分候选指导后，模型开始提出独立 CPU 假设。
2. 第二次 CPU run 仍失败：模型假设日志线程 `http-nio-8080-exec-7` 是热点线程，而快照中热点是 `pricing-exec-1`，证据正确 refute 了错误假设。补充“请求线程不一定等于热点线程”的通用说明后通过。
3. OOM run 出现一次直接评估 seeded 日志上下文（未绑定 `logs.get_thread_context`）导致的 `INVALID_ASSESSMENT`。补充“日志上下文必须工具获取并绑定”的通用规则后通过。
4. CPU run 还遇到 `jvm.get_gc_summary` 的 `DUPLICATE_CALL`；这是确定性去重拒绝，不是只读工具执行失败。live 测试仍对其它工具错误失败，仅将 `DUPLICATE_CALL` 单独记录。
5. 所有修复都在通用 prompt/测试边界内，没有加入 case id、仓库/类/线程名或期望答案；overfit 扫描继续通过。
6. mock CLI 首次 exit 3 是冒烟命令漏了 `--mock-script`，使用了默认基础脚本；补上 case mock 后两 case 均 exit 0，不是产品缺陷。

### 6.3 未执行/限制

- live 结果是单次非确定性样本，不代表生产准确率或统计显著性。
- 发布检查（链接/secret/旧文档）已执行并回填到 [ACCEPTANCE §7–§9](../ACCEPTANCE.md)。
- 未提交/推送；提交动作等待用户明确要求。
