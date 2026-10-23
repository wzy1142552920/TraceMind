# T6 — 两个 JVM Case 与离线评测 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T6
- **状态**：implemented
- **依赖**：T2–T5
- **下游**：T7

## 1. 实施顺序

1. **确认约定**
   - 阅读 T6 spec、[DESIGN §9](../DESIGN.md)、v0.3 case helpers/mock 格式。
   - 确认 expected 只在测试/fixtures；runtime 不读取。
   - 确认 artifact fixture 真实通过 T1/T2/T3。

2. **先写 case 数据**
   - 两个日志、两个仓库、两套 artifacts、两个 mock、两个 expected。
   - manifest service 与 CLI 一致；artifact 行号可解析。
   - CPU case：正常 GC、无死锁、热点业务线程。
   - OOM case：多次 Full GC、heap 直方图主导类、静态无界缓存代码。
   - expected 宽关键词，避免绑定具体措辞。

3. **注册与测试**
   - `tests/eval/helpers.py` 增加 case/repo/artifacts 映射。
   - `test_v04_cases.py` 参数化：run → report → 断言。
   - 断言 schema 0.4、status/Top-1/Top-3、evidence kinds、artifact refs、validation、remediation、工具。
   - 测试先失败。

4. **负向与安全**
   - `test_v04_negative.py`：仅 dump、正常 GC、仅 heap、无机制、路径/symlink/service/超大/畸形、injection。
   - `test_no_remote_or_exec.py`：静态禁止执行/网络（LLM 例外）。
   - overfit 扫描扩展。

5. **调试**
   - 若 mock 脚本不符合 v0.3 协议，修脚本而不是 runtime 特判。
   - 若证据映射/覆盖问题，修 T3/T4 通用逻辑，并补单测。
   - 记录实际失败/修复，不伪造 PASS。

6. **回归**
   - v0.3 三 case 全量；两个新 case；全量离线；ruff/mypy；回填。

## 2. 交付物

- [x] 两个 `fixtures/logs/*/incident.log`
- [x] 两个 `fixtures/repos/*`
- [x] 两套 `fixtures/artifacts/*`
- [x] 两个 `fixtures/mock/*.json`
- [x] 两个 `fixtures/expected/*.yaml`
- [x] `tests/eval/test_v04_cases.py`
- [x] `tests/eval/test_v04_negative.py`
- [x] `tests/eval/test_no_remote_or_exec.py`
- [x] `tests/eval/helpers.py` / overfit 扫描更新

## 3. Definition of Done

- [x] AC-T6-01 至 AC-T6-14 全部满足。
- [x] 两 case Top-1 2/2、引用 100%、标注 100%、接地 100%。
- [x] 负向/安全/injection/overfit 全部通过。
- [x] 无失败/越权工具；无网络/exec。
- [x] v0.3 三 case 回归通过（29 passed）。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/eval/test_v04_cases.py tests/eval/test_v04_negative.py tests/eval/test_no_remote_or_exec.py -q
uv run pytest tests/eval/test_no_case_overfit.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **mock 脚本协议**：沿用 v0.3 脚本格式；propose/assess/investigate 顺序必须被 runtime 接受；不要直接写状态。
- **artifact 一致性**：线程 TID/nid、行号、GC 行必须与解析器匹配；否则先修 fixture/解析器。
- **CPU 同线程**：主日志线程与热点线程不同是刻意设计；验证 artifacts 下同线程规则放宽。
- **OOM 只有快照负向**：需要单独临时 bundle，不修改正常 case。
- **expected 泄露**：不要把 expected 内容拼进 prompt/mock；只用于测试断言。
- **fixture 大小**：小而有代表性；不要整份大 dump。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest tests/eval/test_v04_cases.py tests/eval/test_v04_negative.py tests/eval/test_no_remote_or_exec.py tests/eval/test_no_case_overfit.py -q` | PASS（69 passed） | 两 case Top-1 2/2、confirmed；artifact/remediation 引用与 validation 全通过 |
| 2026-10-23 | Claude | `uv run pytest tests/eval/test_v03_cases.py tests/eval/test_v03_negative.py -q` | PASS（29 passed） | v0.3 三 case 与负向回归 |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（570 passed, 6 skipped） | live 默认跳过；离线确定性 |
| 2026-10-23 | Claude | `uv run ruff check .` / `uv run mypy src` | PASS / PASS（59 files） | 无 lint/type 问题 |

调试记录：首次运行负向测试时，自定义 mock 响应误把 tool call 列表直接传给 `MockProvider`；injection 测试向 `gc.log` 追加行导致既有 GC assessment 行号失配。修正测试构造（包装为 `LLMResponse`、只在 dump/CPU 快照注入），未修改 runtime 做 case 特判。修正后全部通过。
