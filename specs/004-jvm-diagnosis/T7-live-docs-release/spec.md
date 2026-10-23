# T7 — Live、文档与发布 Spec

- **任务 ID**：T7
- **状态**：implemented
- **依赖**：T6
- **下游**：无
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §9–§11](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T6 完成后，离线 mock 只能证明协议闭环，不能证明真实 DeepSeek 会按 JVM 证据规划工具、正确 refute 备选假设。v0.4 仍坚持 live opt-in、有界预算、如实记录，不把 Mock 当 live，也不宣称生产准确率。

T7 增加两个 JVM case 的 opt-in live 测试、CLI 冒烟、文档和 0.4.0 发布检查。若 Key/网络不可用或结果不达标，必须记录 BLOCKED/FAIL，不能改写为通过。

**用户故事**：作为维护者，我能在有 Key 的环境显式开启 live，验证两个 case 的报告结构、Top-1/Top-3、JVM 证据、artifact 引用和快照限制；默认测试完全不访问网络。发布文档如实记录能力、命令、限制和 live 结果。

## 2. In scope

- `tests/live/test_live_v04_cases.py`：两个 case 参数化，复用 gate。
- live 预算：18 iterations / 20 LLM calls / 28 tool calls / 2200 output tokens。
- live CLI 冒烟（至少一个 case）。
- 根 README v0.4 更新。
- `specs/004-jvm-diagnosis/README.md`、`DESIGN.md`、`ACCEPTANCE.md` 与 T1–T7 回填。
- 版本 `0.4.0`（pyproject/`__init__`/lock）。
- secret/link/protected docs 检查。

## 3. Out of scope

- 新增问题域/MCP/真实 JVM attach。
- 修改 v2 设计、001/002/003 specs。
- 生产准确率声明。
- 自动修复/补丁。
- 网络采集、持续监听。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T7-01 | 默认 pytest 跳过 live，不访问网络 | must |
| FR-T7-02 | live 三条件（--run-live、TRACEMIND_LIVE_TESTS=1、Key）同时满足才运行 | must |
| FR-T7-03 | 两 case live 报告结构合法（schema 0.4） | must |
| FR-T7-04 | Top-1 ≥1/2（目标 2/2）、Top-3 2/2 | must |
| FR-T7-05 | JVM 证据来源、artifact 引用、标注、接地校验 | must |
| FR-T7-06 | 不得把 supported 伪造成 confirmed；状态与 evidence 一致 | must |
| FR-T7-07 | live CLI 冒烟生成完整产物、无 secret | must |
| FR-T7-08 | prompt/runtime 无 case 硬编码 | must |
| FR-T7-09 | README 记录 v0.4 能力/命令/限制/live 结果 | must |
| FR-T7-10 | ACCEPTANCE/T1–T7 按实际结果回填 | must |
| FR-T7-11 | 版本 0.4.0 一致 | must |
| FR-T7-12 | 旧 docs/specs 未修改；链接有效 | must |
| FR-T7-13 | 无 Key/`sk-`/密码泄露 | must |

## 5. Live 设计

- 参数化两个 case，复用 `tests/live/conftest.py` 的 gate/fixture。
- 每个 case 使用 Fake verification（无 DB 时为空）和 T6 artifacts。
- 断言：
  - `report.schema_version == "0.4"`。
  - `artifacts` 数量/类型/标注。
  - Top-1 宽关键词命中；Top-3 至少包含正确方向。
  - 至少一个 JVM symptom kind + 至少一个 mechanism kind。
  - 所有 artifact 引用有效。
  - remediation 接地，或明确无有效方案（不得伪造）。
  - 无禁止工具/失败工具。
- 记录 model/usage/latency/stop reason。
- 预算 18/20/28/2200；若预算耗尽，如实记录 STOPPED_BUDGET，不扩大预算掩盖。
- live 失败先定位通用协议/格式/prompt 问题；不得按 case 写死路径/答案。
- 无 Key/网络时记 BLOCKED，不执行测试。

## 6. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T7-01 | 默认 pytest 无网络、live 全 skip |
| AC-T7-02 | gate 三条件测试正确 |
| AC-T7-03 | live 两 case 结构 2/2 |
| AC-T7-04 | Top-1 ≥1/2、Top-3 2/2（实际结果回填） |
| AC-T7-05 | JVM 证据/artifact 引用/标注/接地通过 |
| AC-T7-06 | 状态与证据一致；无伪造 confirmed |
| AC-T7-07 | live CLI 冒烟 exit 0、schema 0.4、无 secret |
| AC-T7-08 | overfit 扫描通过 |
| AC-T7-09 | README 记录能力/命令/限制 |
| AC-T7-10 | ACCEPTANCE/T1–T7 回填，未达标如实记录 |
| AC-T7-11 | `tracemind 0.4.0` 一致 |
| AC-T7-12 | 链接有效；001/002/003/docs 未修改 |
| AC-T7-13 | secret scan 通过 |

## 7. 测试计划

- `tests/live/test_live_v04_cases.py`：参数化、预算、断言、记录。
- live CLI 冒烟：CPU case 至少一次。
- 文档/链接/secret/旧文档检查。
- 默认离线全量回归。

## 8. 风险与开放问题

- **live 非确定性**：如实记录；Top-1 不达标写 FAIL，不调 fixture 迎合模型。
- **预算**：2200 output tokens 可能限制 remediation；失败可记录，不无限加预算。
- **case 答案泄露**：live 断言只用宽关键词/证据来源；prompt 无类名。
- **Fake 标注**：report 仍标注 user_provided artifact；无 DB 时不要出现 fixture 假数据。
- **发布**：lock 文件、版本、文档一致；不提交运行产物/Key。

## 9. 验证命令

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v04_cases.py -q -s
uv run tracemind --version
git status --short
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T7 spec：live 两 case、预算、文档、0.4.0 发布检查 |
| 2026-10-23 | 实现并回填：live 两 case 2/2 confirmed、Top-1/Top-3 2/2；live CPU CLI 冒烟退出码 0；版本 0.4.0；默认离线 571 passed/9 skipped。首次 live CPU case 因跨线程假设/首轮候选缺失失败，改用通用 JVM 提示后通过；未按 case 特判。 |
