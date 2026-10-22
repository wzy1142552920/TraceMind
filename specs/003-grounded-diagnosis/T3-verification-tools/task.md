# T3 — 只读验证工具契约 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T3
- **状态**：implemented
- **依赖**：T1
- **下游**：T4、T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T3 spec、[DESIGN §7.2–§7.3、§11](../DESIGN.md) 和 T1 绑定元数据。
   - 确认 v0.3 只有 Fake backend；不引入数据库驱动/凭据/网络。
   - 确认 DB 工具只在 `--verification-data` 提供时注册。

2. **先写 backend/工具测试**
   - `tests/unit/test_fake_verification.py`：数据加载/校验/拒绝。
   - `tests/unit/test_db_tools.py`：describe/get_row/白名单/脱敏/source_ref。
   - `tests/e2e/test_cli_verification.py`：CLI 参数与退出码。
   - 测试先失败。

3. **实现验证数据加载**
   - 新增 `verification/data.py`（或等价模块）：
     - `VerificationDataError`。
     - `load_verification_data(path) -> FakeVerificationBackend`。
     - schema/标识符/大小/标量值校验。
   - 文件读取使用 UTF-8；错误信息包含路径/字段，不回显整行数据。

4. **实现 Fake backend**
   - `FakeVerificationBackend(environment="fixture")`。
   - `describe_table`、`get_row`（主键单行、columns 子集、敏感列脱敏）。
   - 生成 `source_ref=db://<table>/<pk>=<value>`。
   - 不提供任意 SQL/多行/写方法。

5. **实现 DB 工具**
   - 新增 `db.describe_table`、`db.get_row`，参数继承 T1 `EvidenceToolMeta`。
   - 工具描述明确只读/fixture/非生产/主键单行。
   - 未知表/列 → `TARGET_DENIED`；key 类型错误 → `INVALID_ARGUMENTS`。
   - 输出截断、审计、绑定元数据传递。

6. **接入 CLI/registry**
   - CLI 增加 `--verification-data`（默认 `None`；存在/可读校验）。
   - 在日志解析/索引/建目录前加载并校验；失败退出 2。
   - 有 backend 时注册 db 工具；无 backend 时不注册。
   - run.json 增加 verification 元数据，不含敏感值。

7. **接线与回归**
   - 更新 registry/executor/CLI 测试。
   - 运行 T3 验证命令并回填。

## 2. 交付物

- [x] `src/tracemind/verification/`（协议、Fake backend、数据加载）
- [x] `src/tracemind/tools/verification.py`（db 工具）
- [x] `src/tracemind/cli/main.py` `--verification-data`
- [x] run_meta verification 元数据
- [x] `tests/unit/test_fake_verification.py`
- [x] `tests/unit/test_db_tools.py`
- [x] `tests/e2e/test_cli_verification.py`
- [x] 受影响的 registry/executor/CLI 测试适配

## 3. Definition of Done

- [x] AC-T3-01 至 AC-T3-12 全部满足。
- [x] 只有 `describe_table` 和主键 `get_row`，无任意 SQL/写入口。
- [x] 未知表/列/非法 key 拒绝；敏感列脱敏。
- [x] 无 backend 时 db 工具不出现在工具目录。
- [x] 非法 `--verification-data` 在解析/索引前退出 2，不创建 run 目录。
- [x] 所有 DB 调用可审计，结果环境为 fixture。
- [x] 全量离线测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_fake_verification.py tests/unit/test_db_tools.py tests/e2e/test_cli_verification.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **Fake 偏差**：fixture 不代表真实 DB 行为；报告必须标注环境（T5）。
- **数据校验**：表/列标识符白名单；拒绝嵌套值；文件大小上限。
- **敏感数据**：v0.3 只用合成数据；敏感列仍支持脱敏，避免后续真实 adapter 遗忘。
- **工具暴露**：无 backend 时不注册，避免 LLM 调用不存在的工具。
- **连接信息**：v0.3 数据文件不包含 DSN/凭据；真实 backend 另立 spec。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-22 | Claude | T3 定向 pytest | 57 passed | 数据加载、DB 工具、CLI |
| 2026-10-22 | Claude | 绑定/DB 定向 pytest | 27 passed | 含 DB 绑定元数据 |
| 2026-10-22 | Claude | `uv run pytest -q` | 279 passed, 2 skipped | live 测试保持 opt-in |
| 2026-10-22 | Claude | `uv run ruff check .` | passed | — |
| 2026-10-22 | Claude | `uv run mypy src` | passed | 45 source files |
