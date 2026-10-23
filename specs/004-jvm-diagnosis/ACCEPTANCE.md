# TraceMind v0.4 验收矩阵

- **日期**：2026-10-23
- **状态**：COMPLETE（T1–T7 已回填，v0.4.0）
- **范围**：T1–T7
- **AC 总数**：92
- **live 状态**：PASS（两 case 各一次实际运行）
- **原则**：结果按实际测试/live 输出回填；未达标必须记录 FAIL/BLOCKED，不得伪造

> 本矩阵逐项回填自实际执行结果。live 是非确定性单次样本，只代表本次端到端验证。

## 1. T1 — Artifact 输入契约

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T1-01 | 合法四类 manifest 加载成功，bundle 顺序、records、by_kind/document/has_kind 正确 | `test_artifact_manifest.py` | PASS |
| AC-T1-02 | manifest 缺失/非 JSON/数组/未知字段/错误 schema_version 被拒绝 | 同上 | PASS |
| AC-T1-03 | 未知 kind、重复 id、非法 id、空 artifacts、>8 条被拒绝 | 同上 | PASS |
| AC-T1-04 | service 不匹配、空 service 被拒绝；instance/captured_at 可选 | 同上 | PASS |
| AC-T1-05 | 绝对路径、`..`、`.`、空段、反斜杠、NUL 路径被拒绝 | `test_artifact_safety.py` | PASS |
| AC-T1-06 | symlink 文件、symlink 路径组件、指向根外的真实路径被拒绝 | 同上 | PASS |
| AC-T1-07 | 单文件字节/行数超限、总字节/总行数超限被拒绝 | `test_artifact_manifest.py` | PASS |
| AC-T1-08 | 非 UTF-8、空文件、目录冒充文件、不可读文件被拒绝 | 同上 | PASS（不可读路径由 OSError 分支覆盖，未单独 chmod 测试） |
| AC-T1-09 | 记录不含绝对路径；source_name 为 basename；source_environment=user_provided | 同上 | PASS |
| AC-T1-10 | `redact_text` 对常见 key=value、Bearer、JSON 字符串脱敏并返回类别 | `test_artifact_redaction.py` | PASS |
| AC-T1-11 | CLI 合法 artifacts 可继续诊断；非法 artifacts 退出 2 且不创建 run 目录 | `test_cli_artifacts.py` | PASS |
| AC-T1-12 | 无 `--artifacts` 时 CLI/旧测试行为不变 | 全量回归 | PASS |

## 2. T2 — JVM 文本解析器

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T2-01 | 解析典型 JDK 17 jstack：线程名/id/nid/状态/帧/锁正确 | `test_jvm_thread_dump.py` | PASS |
| AC-T2-02 | 解析 JDK 8 jstack 正确 | 同上 | PASS（头部状态回退） |
| AC-T2-03 | 可识别 JVM 死锁与线程/锁；无线程信息时 warning | 同上 | PASS（含空死锁段 warning） |
| AC-T2-04 | 线程数/帧数/锁事件超限时有 truncated/warning，行号不乱 | 同上 | PASS（线程/帧/锁上限均有测试） |
| AC-T2-05 | top -H 与 ps -L 均能解析 TID/%CPU；十六进制 nid 正确 | `test_jvm_thread_cpu.py` | PASS |
| AC-T2-06 | CPU 排序稳定；表头/非数字行被忽略且 warning 有界 | 同上 | PASS |
| AC-T2-07 | JDK 9+ GC 日志解析 Young/Full、heap、pause | `test_jvm_gc_log.py` | PASS（含 `System.gc()` 嵌套 cause） |
| AC-T2-08 | JDK 8 GC 日志解析 Full GC、单位 K/M/G、pause | 同上 | PASS |
| AC-T2-09 | GC 空输入/无 GC 行返回 warning，不抛异常 | 同上 | PASS |
| AC-T2-10 | heap histogram 解析 Total、live 标记、类名模块后缀 | `test_jvm_heap_histogram.py` | PASS |
| AC-T2-11 | 非 :live 产生固定 warning；空表返回 warning | 同上 | PASS |
| AC-T2-12 | 四个解析器相同输入结果完全一致 | 四测试 | PASS（四解析器均有确定性断言） |
| AC-T2-13 | 输出字符串 ≤512 字符；不包含完整文件内容 | 四测试 | PASS（长值截断测试；ID ≤64、命令 ≤128） |

## 3. T3 — JVM 工具与证据映射

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T3-01 | 无 artifacts 时 registry 不含任何 jvm.* 工具 | `test_jvm_tools.py` | PASS |
| AC-T3-02 | 只有 thread_dump 时注册 thread_dump/deadlocks，不注册 hot_threads/gc/heap | 同上 | PASS |
| AC-T3-03 | 只有 thread_cpu 时不注册 hot_threads（需要两者） | 同上 | PASS |
| AC-T3-04 | 六工具参数范围/额外字段/非法 pattern 被拒绝 | 同上 | PASS（15 组非法参数覆盖六工具） |
| AC-T3-05 | thread dump 过滤/limit/死锁正确；无匹配返回空 + warning | 同上 | PASS（名称/状态/limit/deadlock_only） |
| AC-T3-06 | hot threads 正确映射 nid、排序、未匹配 TID 有 warning | 同上 | PASS（nid 0x1a2c → TID 6700；TID 99 unmatched） |
| AC-T3-07 | deadlocks 返回 JVM 报告段；无死锁返回空但不是错误 | 同上 | PASS（含 lock id 与 absent warning） |
| AC-T3-08 | GC summary/events、heap histogram 输出与解析器一致 | 同上 | PASS（young/full、pause 精度、heap 过滤） |
| AC-T3-09 | 工具结果 ≤32 KiB，列表/字符串上限生效 | 同上/executor | PASS（80 线程输出 ≤32768 且 `truncated=true`） |
| AC-T3-10 | 所有调用进入 ToolExecutor 审计，绑定元数据进入 result/audit | 同上 | PASS（绑定 hot threads 调用） |
| AC-T3-11 | 映射产生正确 kind/provenance/source_ref；行号在范围内 | `test_jvm_evidence_mapping.py` | PASS（六工具、单行/区间引用、USER_ARTIFACT） |
| AC-T3-12 | 未绑定 JVM 证据不能覆盖 requirement | workspace 测试 | PASS（沿用 `test_grounded_evaluator.py`/`test_tool_binding.py` 的未绑定规则） |
| AC-T3-13 | 映射遇到非法 artifact/行号跳过并 warning | `test_jvm_evidence_mapping.py` | PASS（未知 id、越界行、非 artifact scheme） |
| AC-T3-14 | 工具无网络/subprocess/任意路径参数；静态扫描通过 | `test_jvm_tools.py` | PASS（AST import 扫描 + 无 `open(`/`Popen`） |
| AC-T3-15 | 工具描述含只读/用户快照/非实时提示 | `test_jvm_tools.py` | PASS（六工具统一 `_SNAPSHOT_NOTE`） |

## 4. T4 — 覆盖模型与运行时

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T4-01 | symptom/mechanism 集合与 DESIGN 一致，旧 kind 映射正确 | `test_evidence_categories.py` | PASS（15 kind 互斥全覆盖；旧 log/sql/context 组合仍 confirmed） |
| AC-T4-02 | 只有 symptom 无 mechanism 时不能 confirmed，warning 明确 | `test_evaluator_v04.py` | PASS（supported + `missing_mechanism_evidence`） |
| AC-T4-03 | 只有 mechanism 无 symptom 时不能 confirmed | 同上 | PASS（supported + `missing_symptom_evidence`） |
| AC-T4-04 | 完整 symptom+mechanism+工具证据+替代排除+discriminating 时可 confirmed | 同上 | PASS（无 artifacts 的 JVM 场景 confirmed） |
| AC-T4-05 | v0.3 refute/替代假设/单假设规则未放松 | 同上 | PASS（refute 终态、单假设不确认、开放替代不确认、双满足歧义） |
| AC-T4-06 | 有 artifacts 时主线程存在也不要求同线程上下文，repair 不再误报 | 集成测试 | PASS（确认路径无 `agent.repair`） |
| AC-T4-07 | 无 artifacts 时主线程存在仍强制同线程上下文 | v0.3 回归 | PASS（`test_grounded_evaluator.py`、`test_v03_runtime.py`、v0.3 eval） |
| AC-T4-08 | RunResult 携带 artifact records，无绝对路径 | 集成测试 | PASS（顺序/id/`user_provided`，序列化无 tmp 根路径） |
| AC-T4-09 | prompt 含 artifact 摘要/工具，无 artifacts 时不含 artifact 段 | `test_prompt_v04.py` | PASS（≤8 条、≤3 warnings、160 字符截断） |
| AC-T4-10 | prompt 含 JVM 通用指导，不含 case 名称/期望答案 | 同上/overfit | PASS（base/JVM 两版均扫描 case/类名/expected；T7 新增首轮候选/跨线程/上下文绑定断言，`test_prompt_v04.py` 6 passed） |
| AC-T4-11 | cause chain 被展示，cause 帧可用于 seed 匹配 | 同上/运行时 | PASS（5 层/3 帧上限；主栈未命中时 cause 帧匹配源码） |
| AC-T4-12 | JVM 工具调用计入预算/审计，可见性遵循协议阶段 | 集成测试 | PASS（propose → assess → investigate；3 次证据调用有审计/预算） |
| AC-T4-13 | 旧 v0.3 三 case 集成/eval 全部通过 | 全量回归 | PASS（v0.3 eval 15 通过；全量 498 通过） |

## 5. T5 — 报告 0.4 与 CLI

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T5-01 | 报告/run_meta schema 0.4 | `test_report_v04.py`/E2E | PASS（报告与 run.json 均断言 0.4；旧 eval/live schema 断言已迁移） |
| AC-T5-02 | artifacts[] 字段/顺序/basename/标注正确 | 同上 | PASS（manifest 顺序、7 字段、basename、user_provided；warnings ≤10/≤256） |
| AC-T5-03 | 无 artifacts 时 artifacts=[]，无 JVM 限制 | 同上 | PASS（空列表、无四条 JVM 文案、artifact 校验为 true） |
| AC-T5-04 | artifact 引用合法时 citations/artifact_citations 为 true | `test_citation_v04.py` | PASS（区间/单点/边界行均通过） |
| AC-T5-05 | 不存在 id/越界/反向/零行引用使校验失败 | 同上 | PASS（5 类非法引用均 false 并降级） |
| AC-T5-06 | 单点 `#Lx` 合法；其他 scheme 行为不变 | 同上 | PASS（`#L3` 合法；artifacts 存在时 repo 越界仍按旧规则失败） |
| AC-T5-07 | artifacts_labeled 正确；非 user_provided 时 false | `test_report_v04.py` | PASS（改为 live 后 false 且只记错误、不降级） |
| AC-T5-08 | JVM limitations 自动追加且不重复；无 artifacts 不追加 | 同上 | PASS（快照/二进制/同线程/JVM-only；预置文案不重复） |
| AC-T5-09 | Markdown 展示 artifacts/JVM 证据，无绝对路径/完整 dump | 同上 | PASS（快照与 JVM 证据段；路径剥离、dump 不出现） |
| AC-T5-10 | CLI 摘要/JSON 字段正确；无 artifacts 时旧字段不变 | `test_cli_v04.py` | PASS（Snapshots/JVM evidence；JSON 3 字段；无 artifacts 不显示新文本行） |
| AC-T5-11 | 退出码不变 | CLI 测试 | PASS（0/2/3/4 旧测试全绿，`_exit_code` 未改） |
| AC-T5-12 | 报告/产物无 secret；旧 0.3 断言已迁移 | secret scan/全量 | PASS（E2E 断言无 `sk-`/artifact 绝对路径；报告、eval、live 断言迁移） |

## 6. T6 — 两个 JVM Case 与离线评测

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T6-01 | 两个 manifest 通过加载；service/kind/line_count 正确 | `test_v04_cases.py` | PASS（CPU 18/6/2 行、OOM 4/9 行；expected artifact id/kind/name/line_count 与 manifest/报告一致） |
| AC-T6-02 | CPU case Top-1、confirmed、THREAD_CPU/THREAD_DUMP/代码证据齐全 | 同上 | PASS（Top-1 confirmed；THREAD_CPU `#L4`、THREAD_DUMP `#L4-L8`、SOURCE_CODE `PricingService.java#L9-L15`、同线程上下文齐全） |
| AC-T6-03 | CPU case GC 压力假设被 refute，无死锁误判 | 同上 | PASS（GC 假设被 `gc-log#L1-L2` contradicted；锁假设被 WAITING dump `#L10-L14` contradicted；deadlock 工具无命中） |
| AC-T6-04 | OOM case Top-1、confirmed、GC_SUMMARY/HEAP_SUMMARY/代码证据齐全 | 同上 | PASS（Top-1 confirmed；GC_SUMMARY `#L1-L4`、HEAP_SUMMARY `#L1-L9`、SOURCE_CODE `ReportCache.java#L12-L20`） |
| AC-T6-05 | OOM case 堆太小/单次大对象被 refute | 同上 | PASS（堆过小被 `gc-log#L4` contradicted；单次大对象被 `heap-histo#L1-L9` contradicted） |
| AC-T6-06 | 两 case artifact 引用 100% 有效、标注 100% | 同上 | PASS（全部 artifact ref 在行数内；`artifact_citations_valid`/`artifacts_labeled` 为 true；source_environment 全为 user_provided） |
| AC-T6-07 | 两 case remediation 接地 100% | 同上 | PASS（2/2 code+test；每条 action 的 evidence_ids 均属于 Top-1，CPU/OOM 关键 artifact+源码 ref 均出现） |
| AC-T6-08 | 无失败/禁止工具；工具参数在范围内 | 同上 | PASS（expected JVM 工具全部调用且 ok；无 db/shell/attach；全部 tool_calls.ok） |
| AC-T6-09 | 负向快照不足/GC 正常/无机制全部符合预期 | `test_v04_negative.py` | PASS（dump-only、gc-only、heap-only 均不得 confirmed；仅快照无 mechanism 为 supported 且记录 `missing_mechanism_evidence`；正常 GC 假设 contradicted） |
| AC-T6-10 | 路径/symlink/service/超大/畸形 artifacts 被拒绝 | 同上 | PASS（父目录逃逸/绝对路径/symlink/service 不匹配/10MiB+1/非法 JSON 均抛 `ArtifactError`） |
| AC-T6-11 | injection 不改变策略/不越权 | 同上 | PASS（快照内 marker 不进入报告/source claim；run 仍 confirmed；无 shell/attach 调用） |
| AC-T6-12 | overfit 扫描通过 | `test_no_case_overfit.py` | PASS（扫描目录加入 `artifacts`；v04 case id、仓库/类/线程名、数字与 expected 字段均未进入 runtime） |
| AC-T6-13 | 离线 pytest 确定性通过，无网络/exec | `test_no_remote_or_exec.py` | PASS（T6 专项 69 passed；v0.3 eval 29 passed；T6 时全量 570 passed/6 skipped，T7 发布时 571 passed/9 skipped；静态扫描无 subprocess/socket/网络客户端/JVM 采集命令） |
| AC-T6-14 | 失败信息可定位 case/断言 | 代码审查 | PASS（case 参数化带 case id，断言 f-string 前缀 case_id；负向测试按场景命名） |

## 7. T7 — Live、文档与发布

| AC | 验收标准 | 计划验证 | 状态 |
|---|---|---|---|
| AC-T7-01 | 默认 pytest 无网络、live 全 skip | 全量离线测试 | PASS（571 passed, 9 skipped；9 个 live 测试全部 skip） |
| AC-T7-02 | gate 三条件测试正确 | `test_live_v04_cases.py` | PASS（缺省运行 skip；`--run-live` + `TRACEMIND_LIVE_TESTS=1` + Key 同时满足才执行，实际 3 passed） |
| AC-T7-03 | live 两 case 结构 2/2 | live 测试 | PASS（CPU/OOM 均 schema 0.4、状态合法、artifact/validation 完整） |
| AC-T7-04 | Top-1 ≥1/2、Top-3 2/2 | live 测试/结果表 | PASS（Top-1 2/2、Top-3 2/2；见 §10） |
| AC-T7-05 | JVM 证据/artifact 引用/标注/接地通过 | live 断言 | PASS（两 case 均含 JVM symptom + mechanism、artifact 引用在范围内、`user_provided` 标注、remediation 证据绑定） |
| AC-T7-06 | 状态与证据一致；无伪造 confirmed | live 断言 | PASS（confirmed 时 requirements 全覆盖、无 refute、替代均 contradicted；OOM 一次控制调用被修复，未伪造状态） |
| AC-T7-07 | live CLI 冒烟 exit 0、schema 0.4、无 secret | CLI E2E | PASS（CPU case exit 0；3 artifacts；JVM 证据 5；remediation 3；report/产物无 Key/`sk-`/绝对路径） |
| AC-T7-08 | overfit 扫描通过 | 代码审查 | PASS（`test_no_case_overfit.py` 在全量中通过；prompt 仅含通用 JVM 规则） |
| AC-T7-09 | README 记录能力/命令/限制 | 文档检查 | PASS（v0.4 能力、`--artifacts`、两 case、mock/live 命令、限制、结果与调试记录） |
| AC-T7-10 | ACCEPTANCE/T1–T7 回填，未达标如实记录 | 文档检查 | PASS（T1–T7 spec/task 已回填；live 调试失败记录于 T7 task §6.2 与 §10） |
| AC-T7-11 | `tracemind 0.4.0` 一致 | `--version`/pyproject/lock | PASS（CLI、import、pyproject、uv.lock 均为 0.4.0） |
| AC-T7-12 | 链接有效；001/002/003/docs 未修改 | 链接/git status | PASS（README + 004 specs：18 文件、66 链接、0 失效；`git status` 对 001/002/003 与 design docs 无输出；只改 README/specs 004/src/tests/fixtures/pyproject/lock） |
| AC-T7-13 | secret scan 通过 | secret scan | PASS（28 文件；实际 Key/`sk-`/用户主目录路径 0 命中；T1 spec 的 `Authorization: Bearer ...` 是脱敏文档占位符；`.env` 已忽略且未跟踪） |

## 8. 验证命令

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src

uv run pytest tests/unit/test_artifact_manifest.py tests/unit/test_artifact_safety.py tests/unit/test_artifact_redaction.py tests/e2e/test_cli_artifacts.py -q
uv run pytest tests/unit/test_jvm_thread_dump.py tests/unit/test_jvm_thread_cpu.py tests/unit/test_jvm_gc_log.py tests/unit/test_jvm_heap_histogram.py -q
uv run pytest tests/unit/test_jvm_tools.py tests/unit/test_jvm_evidence_mapping.py -q
uv run pytest tests/unit/test_evidence_categories.py tests/unit/test_evaluator_v04.py tests/unit/test_prompt_v04.py -q
uv run pytest tests/integration/test_v04_runtime.py -q
uv run pytest tests/unit/test_report_v04.py tests/unit/test_citation_v04.py tests/e2e/test_cli_v04.py -q
uv run pytest tests/eval/test_v04_cases.py tests/eval/test_v04_negative.py tests/eval/test_no_remote_or_exec.py -q

TRACEMIND_LIVE_TESTS=1 uv run pytest --run-live -m live tests/live/test_live_v04_cases.py -q -s
```

## 9. 最终验证与限制

| 检查 | 结果 |
|---|---|
| 默认离线 `uv run pytest -q` | PASS（571 passed, 9 skipped） |
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS（59 source files） |
| live 两 case | PASS（3 passed, 39.41s；2/2 confirmed，Top-1/Top-3 2/2） |
| live CLI 冒烟（CPU） | PASS（exit 0；schema 0.4；3 artifacts；JVM 证据 5；remediation 3；无 secret） |
| Mock CLI（CPU/OOM） | PASS（均 exit 0；schema 0.4；confirmed；引用/校验有效） |
| 版本 | PASS（`tracemind 0.4.0`，pyproject/`__init__`/lock 一致） |
| 链接检查 | PASS（18 文件 / 66 链接 / 0 失效） |
| secret scan | PASS（28 文件；实际 Key/`sk-`/用户主目录路径 0 命中） |
| 受保护 docs/specs | PASS（001/002/003 与 v1/v2 设计文档无变更） |

限制：

- 只支持用户提供的 JVM 文本快照；不 attach、不采集、不执行命令。
- 不解析 `.hprof`/JFR；CPU/内存结论受快照时点限制，单个快照不能证明泄漏。
- 不接 MCP/真实 DB/Redis；没有实时指标。
- 两个 case 是合成 fixture，不代表生产准确率。
- live 依赖外部 Key/网络/模型版本，具有非确定性。
- 修复建议只展示，不自动应用。

## 10. Live 实际记录与调试

预算：18 iterations / 20 LLM calls / 28 tool calls / 2200 output tokens；模型 `deepseek-flash`。

| Case | 报告状态 | Top-1 | Top-3 | LLM calls | Tools | Total tokens | Latency | Stop |
|---|---|---|---|---|---|---|---|---|
| `v04-j1-cpu-high` | confirmed | hit | hit | 6 | 9 | 38,430 | 16,726 ms | `evidence_sufficient` |
| `v04-j2-memory-oom` | confirmed | hit | hit | 7 | 12 | 38,478 | 22,594 ms | `evidence_sufficient` |

live CLI CPU 冒烟：exit 0；6 LLM calls；11 tool calls；38,977 tokens；25,416 ms；3 artifacts；5 条 JVM 证据；3 条 remediation。

调试记录：

1. 首次 live CPU run 为 `insufficient_data`：首轮把阻塞与 JVM 压力合并为一个候选，遗漏 CPU-bound 机制。改成通用首轮差分候选指导后修复。
2. 第二次 CPU run 把日志线程误当作热点线程，证据正确 refute；补充“请求线程不一定等于热点线程”后通过。
3. OOM run 出现一次未绑定 `logs.get_thread_context` 的 `INVALID_ASSESSMENT`，补充工具绑定规则后通过。
4. CPU run 的 `jvm.get_gc_summary` 曾命中 `DUPLICATE_CALL`；这是去重拒绝，不是只读工具失败。测试仍对其它工具错误失败，只单独记录 dedupe。
5. 所有修复均为通用 prompt/测试改动，未加入 case id、类/线程名或答案；overfit 扫描通过。live 是单次非确定性结果，不能外推为生产准确率。
