# T6 — 两个 JVM Case 与离线评测 Spec

- **任务 ID**：T6
- **状态**：implemented
- **依赖**：T2–T5
- **下游**：T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §9](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

T1–T5 提供了 artifact、解析、工具、覆盖和报告能力，但没有任何真实可重复的场景证明这些能力能诊断 JVM 问题。T6 新增两个“症状相似、需要不同证据”的 JVM case：CPU 高（热点业务循环）与内存高/OOM（无界缓存）。每个 case 提供日志、仓库、artifacts、mock 脚本和 expected，用 pytest 做确定性离线评测。

**用户故事**：作为维护者，我能用同一套命令重复跑两个 case，确认报告 Top-1 为正确原因、JVM 证据引用有效、修复建议接地；我也能通过负向 case 确认“只有快照没有代码机制不能确认”“GC 正常不能归因 GC 压力”。case 的答案不会进入 runtime/prompt。

## 2. In scope

- `fixtures/logs/v04-j1-cpu-high/incident.log`
- `fixtures/logs/v04-j2-memory-oom/incident.log`
- `fixtures/repos/v04-jvm-hot-loop/`（CPU case 仓库）
- `fixtures/repos/v04-jvm-unbounded-cache/`（OOM case 仓库）
- `fixtures/artifacts/v04-j1-cpu-high/{manifest.json,thread-dump.txt,thread-cpu.txt,gc.log}`
- `fixtures/artifacts/v04-j2-memory-oom/{manifest.json,gc.log,heap-histo.txt}`
- `fixtures/mock/v04-j1-cpu-high.json`、`v04-j2-memory-oom.json`
- `fixtures/expected/v04-j1-cpu-high.yaml`、`v04-j2-memory-oom.yaml`
- `tests/eval/test_v04_cases.py`、`test_v04_negative.py`、`test_no_remote_or_exec.py`
- `tests/eval/helpers.py` 注册 case/仓库/artifacts。
- overfit 扫描扩展。

## 3. Out of scope

- live（T7）。
- 新问题域（MyBatis/Redis/DB 死锁/事务）。
- 真实 JVM/真实仓库/生产数据。
- 自动生成 fixture/答案。
- 修改运行时以适配 case。

## 4. Case 定义

### 4.1 `v04-j1-cpu-high`

- 日志：`order-service` 请求超时/高延迟错误，栈指向 `PricingController.quote` → `PricingService.recalculate`；主线程有线程号（例如 `http-nio-8080-exec-3`）。
- 仓库：
  - `PricingController.quote` 调 `PricingService.recalculate`。
  - `PricingService.recalculate` 内的高复杂度循环（可被 tree-sitter 索引）。
- artifacts：
  - thread dump：`pricing-exec-1` RUNNABLE，栈顶 `PricingService.recalculate`；其他线程 WAITING；无死锁。
  - thread cpu：`pricing-exec-1` TID 高 CPU（如 92.3%），其余低。
  - gc log：若干 Young GC，无 Full GC/长停顿（用于 refute GC 压力）。
- 真实原因：热点业务计算（CPU 密集循环），不是 GC、锁竞争、下游等待。
- 备选假设：
  1. GC 压力导致停顿。
  2. 锁竞争/死锁。
  3. 下游依赖等待。
- expected Top-1 关键词：`recalculate` / `CPU` / `hot loop` / `PricingService`（宽匹配，不要求精确措辞）。
- 期望证据 kind：`LOG_EVENT`、`THREAD_CPU`、`THREAD_DUMP`、`GC_SUMMARY`（refute）、`SOURCE_CODE`/`CALL_PATH`。
- 期望工具：`jvm.get_hot_threads`、`jvm.get_gc_summary`、`jvm.get_deadlocks`、`jvm.get_thread_dump`、`code.get_symbol`/`code.find_symbol`、`code.get_source_range`/`code.get_callers`。
- 确认条件：有 symptom（CPU/dump/log）+ mechanism（源码/调用路径）+ 工具证据 + 替代假设 contradicted。
- remediation：优化热点计算/限制输入规模/缓存/异步等，绑定假设与证据；不自动修改。

### 4.2 `v04-j2-memory-oom`

- 日志：`java.lang.OutOfMemoryError: Java heap space`，栈指向报告加载/缓存路径（例如 `ReportController.load` → `ReportService.getReport` → `ReportCache.get`）。
- 仓库：
  - `ReportController`/`ReportService` 使用静态 `ReportCache`。
  - `ReportCache` 静态 `ConcurrentHashMap<String, ReportEntry>` 只 put、无淘汰/TTL/上限。
- artifacts：
  - gc log：多次 Full GC，GC 后 heap 仍高，停顿增长（JDK 9+ unified 与/或 JDK 8 格式）。
  - heap histogram：`ReportEntry` 与 `ConcurrentHashMap$Node` 主导实例/字节。
- 真实原因：无界静态缓存导致堆增长/OOM。
- 备选假设：
  1. 堆配置过小（Full GC 后应大幅回落，实际不回落后被证伪）。
  2. 单次大对象/大查询结果（堆直方图应为单个巨大对象，实际为大量小对象后被证伪）。
- expected Top-1 关键词：`ReportCache` / `unbounded` / `cache` / `ConcurrentHashMap`（宽匹配）。
- 期望证据 kind：`LOG_EVENT`、`GC_SUMMARY`、`HEAP_SUMMARY`、`SOURCE_CODE`/`CALL_PATH`。
- 期望工具：`jvm.get_gc_summary`、`jvm.get_gc_events`、`jvm.get_heap_histogram`、`code.get_symbol`/`code.find_symbol`、`code.get_source_range`。
- 确认条件：有机制（静态缓存无界）时才可 confirmed；只有快照的负向场景最多 supported。
- remediation：增加容量上限/淘汰/TTL、缓存指标、避免缓存大对象等；绑定证据。

## 5. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T6-01 | 两个 case 的日志/仓库/artifacts/mock/expected 齐全且可加载 | must |
| FR-T6-02 | artifacts manifest 通过 T1 校验，service 一致 | must |
| FR-T6-03 | mock 脚本按 v0.3 协议 propose → 调查 → assess → remediation | must |
| FR-T6-04 | 两个 case 离线生成 schema 0.4 报告，Top-1 2/2 | must |
| FR-T6-05 | CPU case 期望 THREAD_CPU/THREAD_DUMP + 代码证据；GC 压力被 refute | must |
| FR-T6-06 | OOM case 期望 GC_SUMMARY/HEAP_SUMMARY + 代码证据；缓存假设 confirmed | must |
| FR-T6-07 | artifact 引用 100% 有效、artifact 标注 100% user_provided | must |
| FR-T6-08 | remediation 接地率 100%，绑定 supported/confirmed 假设 | must |
| FR-T6-09 | 无禁止工具/失败工具/越权路径 | must |
| FR-T6-10 | 负向：仅 thread dump 无 CPU → CPU 假设不 confirmed | must |
| FR-T6-11 | 负向：GC 正常时 GC 压力被 refute，不能 confirmed | must |
| FR-T6-12 | 负向：仅 heap/GC 无代码机制 → OOM 最多 supported | must |
| FR-T6-13 | 负向：路径穿越/symlink/service 不匹配/超大/畸形被拒绝 | must |
| FR-T6-14 | artifact prompt injection 不改变策略/不产生越权 | must |
| FR-T6-15 | overfit 扫描：runtime/prompt 无 case id/类名/路径/期望关键词 | must |
| FR-T6-16 | 默认 pytest 离线、确定性；无网络/无 exec | must |
| FR-T6-17 | 失败信息包含 case/断言 | must |

## 6. 期望文件格式

`fixtures/expected/<case>.yaml`（实际契约）：

```yaml
case_id: v04-j1-cpu-high
symptom: "..."
expected_top_cause_keywords: ["hot loop", "recalculate"]
expected_thread: http-nio-8080-exec-7
expected_thread_context_messages: ["..."]
forbidden_thread_context_markers: ["..."]
expected_evidence_kinds: [thread_cpu, thread_dump, source_code, log_thread_context]
expected_evidence_refs: ["artifact://thread-cpu#L4", "repo://..."]
expected_refutations:
  - hypothesis_keywords: ["GC pauses"]
    refs: ["artifact://gc-log#L1-L2"]
expected_artifacts:
  - {artifact_id: thread-cpu, kind: thread_cpu, source_name: thread-cpu.txt, line_count: 6}
expected_status: confirmed
expected_hypothesis_status: confirmed
expected_remediation_types: [code, test]
expected_remediation_target_keywords: ["PricingService"]
expected_remediation_evidence_refs: ["artifact://thread-cpu#L4"]
expected_jvm_tools: ["jvm.get_hot_threads"]
forbidden_tool_calls: ["shell.execute"]
notes: "..."
```

- 期望 artifact 的 `source_name`/`line_count` 与 manifest/实际解析一致。
- expected 只被测试读取；不进入 `DiagnosisRuntime`。
- 关键词大小写不敏感；Top-1/Top-3 与 refutation 都用 statement 宽匹配。
- `forbidden_tool_calls` 默认空；测试仍检查无失败工具/越权。
- 测试同时断言 artifact 引用范围、100% verified 引用、validation 标志与 remediation evidence 归属。

## 7. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T6-01 | 两个 manifest 通过加载；service/kind/line_count 正确 |
| AC-T6-02 | CPU case Top-1、confirmed、THREAD_CPU/THREAD_DUMP/代码证据齐全 |
| AC-T6-03 | CPU case GC 压力假设被 refute，无死锁误判 |
| AC-T6-04 | OOM case Top-1、confirmed、GC_SUMMARY/HEAP_SUMMARY/代码证据齐全 |
| AC-T6-05 | OOM case 堆太小/单次大对象被 refute |
| AC-T6-06 | 两 case artifact 引用 100% 有效、标注 100% |
| AC-T6-07 | 两 case remediation 接地 100% |
| AC-T6-08 | 无失败/禁止工具；工具参数在范围内 |
| AC-T6-09 | 负向快照不足/GC 正常/无机制全部符合预期 |
| AC-T6-10 | 路径/symlink/service/超大/畸形 artifacts 被拒绝 |
| AC-T6-11 | injection 不改变策略/不越权 |
| AC-T6-12 | overfit 扫描通过 |
| AC-T6-13 | 离线 pytest 确定性通过，无网络/exec |
| AC-T6-14 | 失败信息可定位 case/断言 |

## 8. 测试计划

- `tests/eval/test_v04_cases.py`：参数化两个 case，MockProvider，断言 schema/Top-1/Top-3/evidence/kinds/refs/validation/remediation/tools。
- `tests/eval/test_v04_negative.py`：临时 bundle（仅 dump/正常 GC/仅 heap）、安全拒绝、injection、无 mechanism 降级。
- `tests/eval/test_no_remote_or_exec.py`：扫描 src 禁止 subprocess/socket/requests/jstack 执行；允许 llm/deepseek。
- `tests/eval/test_no_case_overfit.py` 扩展：004 目录/case id/类名/期望词不得出现在 src/prompts。
- 复用 helpers 注册 case；不把 expected 传给 runtime。

## 9. 风险与开放问题

- **mock 过度脚本化**：mock 只模拟 LLM 决策，工具/证据仍真实执行；不能预置 evidence/status。
- **case 难度**：备选假设必须有可 refute 的 artifact 事实；避免一个证据同时支持多个假设。
- **OOM 确认**：必须有 mechanism；只有快照的负向必须覆盖。
- **CPU case 同线程**：主日志线程可能不是热点线程；有 artifacts 时同线程规则已放宽。
- **fixture 大小**：控制 artifacts ≤几十 KB；不提交大文件。
- **overfit**：expected 文件名/内容不进 runtime；prompt 只放通用 JVM 指导。

## 10. 验证命令

```bash
uv run pytest tests/eval/test_v04_cases.py tests/eval/test_v04_negative.py tests/eval/test_no_remote_or_exec.py -q
uv run pytest tests/eval/test_no_case_overfit.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T6 spec：CPU/OOM 两 case、expected、负向/安全/overfit、离线评测 |
| 2026-10-23 | 实现并回填：两个 case、69 项 T6 专项测试通过；OOM 备选假设收敛为堆过小/单次大对象；expected 契约按实际字段更新 |
