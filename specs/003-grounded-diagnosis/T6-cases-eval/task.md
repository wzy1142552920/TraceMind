# T6 — 三 case 与 pytest 评测 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T6
- **状态**：planned
- **依赖**：T1、T2、T3、T4、T5
- **下游**：T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T6 spec、[DESIGN §13](../DESIGN.md)、T1–T5 的工具/证据/报告契约。
   - 确认只做 pytest，不新增 `tracemind eval` CLI。
   - 确认三 case 的 expected 只在测试数据，不进入 runtime/prompt。
   - 确认同线程上下文与代码证据都要被评测。

2. **准备 fixtures**
   - 复制现有 order-service 为 `minimal-order-service-fixed`，只改 `OrderMapper.updateStatus` 为抽象 `@Update`。
   - 保留 `minimal-order-service` 作为 C3 stub 变体。
   - 创建三份内容一致的日志：同线程 INFO/WARN/ERROR + 两条跨线程 DEBUG 噪声。
   - 创建三份验证数据。
   - 创建三份 expected YAML（线程、上下文消息、禁止标记、证据种类）。
   - 校验行号：日志栈指向 `OrderService.java:24`、`OrderService.java:14`、`OrderController.java:16`。

3. **编写 Mock 脚本**
   - 三份 JSON 脚本按 T6 spec 的轮次编排。
   - 假设 basis 用初始 evidence ID 或 source_ref。
   - 先调用 `logs.get_thread_context` 并绑定正确假设；工具调用绑定 hypothesis/requirement；assessment 用 source_ref 解析。
   - remediation 用 `evidence_source_refs` 或 evidence IDs。
   - 确保正确原因被支持、另外两个被 refute；替代假设用代码/DB 证据反驳，不复用上下文绑定。
   - 正确假设的 requirements 覆盖同线程上下文、代码、工具三类来源，且全部被 assess；否则确认门槛无法通过。
   - 脚本先跑通 runtime，再写断言。

4. **实现 pytest harness**
   - `tests/eval/helpers.py`：加载 case、构建 runtime/report、提取指标。
   - `tests/eval/test_v03_cases.py`：参数化断言。
   - 断言 Top-1 的同线程上下文（线程号/消息/无跨线程标记）与代码证据。
   - 失败信息包含 case_id + 断言名。
   - 不访问网络、不依赖实时模型。

5. **负向与安全测试**
   - `tests/eval/test_v03_negative.py`：
     - 未接地/伪造证据/无效 assessment/无证据修复。
     - 开放替代不确认。
     - DB 未知表/列。
     - 恶意日志/DB 内容。
     - 缺同线程上下文 → 不 confirmed + repair；未绑定上下文 assessment 拒绝；跨线程事件被排除。
   - `tests/eval/test_no_case_overfit.py`：扫描 runtime/prompt 源码。

6. **回归与回填**
   - 更新受影响的 E2E/旧 fixture 测试。
   - 运行 T6 验证命令，记录三 case 指标。
   - 回填 task/spec 验证结果，未达标如实记录。

## 2. 交付物

- [ ] `fixtures/logs/v03-c1-missing-row/incident.log`
- [ ] `fixtures/logs/v03-c2-duplicate-callback/incident.log`
- [ ] `fixtures/logs/v03-c3-mapper-stub/incident.log`
- [ ] `fixtures/repos/minimal-order-service-fixed/**`
- [ ] `fixtures/repos/minimal-order-service/**`（C3 保留/校验）
- [ ] `fixtures/verification/v03-c1-missing-row.json`
- [ ] `fixtures/verification/v03-c2-duplicate-callback.json`
- [ ] `fixtures/verification/v03-c3-mapper-stub.json`
- [ ] `fixtures/mock/v03-c1-missing-row.json`
- [ ] `fixtures/mock/v03-c2-duplicate-callback.json`
- [ ] `fixtures/mock/v03-c3-mapper-stub.json`
- [ ] `fixtures/expected/v03-c1-missing-row.yaml`
- [ ] `fixtures/expected/v03-c2-duplicate-callback.yaml`
- [ ] `fixtures/expected/v03-c3-mapper-stub.yaml`
- [ ] `tests/eval/helpers.py`
- [ ] `tests/eval/test_v03_cases.py`
- [ ] `tests/eval/test_v03_negative.py`
- [ ] `tests/eval/test_no_case_overfit.py`
- [ ] 更新的 E2E/回归测试

## 3. Definition of Done

- [ ] AC-T6-01 至 AC-T6-16 全部满足。
- [ ] 三 case 日志一致（含跨线程噪声）；fixed/stub 差异仅在 Mapper。
- [ ] 离线 Top-1 3/3、同线程上下文 3/3、代码证据 3/3、覆盖 3/3、引用 100%、接地 100%、越权 0。
- [ ] 负向/安全/防过拟合测试通过。
- [ ] 三 case 报告均为 schema 0.3，fixture 标注正确。
- [ ] 默认 pytest 完全离线、确定性；无网络/Key 依赖。
- [ ] 全量测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py tests/eval/test_no_case_overfit.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **Mock 过拟合**：runtime 无 case 分支；overfit 扫描；T7 live 验证真实模型。
- **日志/行号漂移**：共享 Service/Controller 不改；测试校验栈行号。
- **证据引用**：脚本用 source_ref 而非硬编码 ID，减少 runtime 顺序耦合。
- **关键词脆弱**：Mock 用明确短语；live 以证据/结构为主。
- **Fixture 真实性**：合成数据只验证协议，不代表生产；T7/README 声明。
- **上下文绑定**：同一上下文证据只能绑定一个 requirement；替代假设必须靠代码/DB 证据反驳，Mock 脚本需避免重复绑定。
- **跨线程噪声**：日志必须保持三 case 逐字节一致；新增噪声后同步校验主事件选择和上下文行范围。
- **测试时间**：离线 Mock/小预算；如变慢，按 case 分组但仍默认全跑。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | 待实现 | PLANNED | — |
