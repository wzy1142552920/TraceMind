# T3 — JVM 工具与证据映射 Spec

- **任务 ID**：T3
- **状态**：implemented
- **依赖**：T1、T2
- **下游**：T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §5–§6](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

T2 产出了结构化的 JVM 摘要，但 LLM 无法直接读取 Python 对象，也没有可审计的工具调用。T3 把解析器包装成六个只读、参数受限、条件注册的 JVM 工具，经过现有 ToolExecutor 的参数校验、绑定、去重、截断和审计；同时把工具结果确定性映射为新的 evidence kind，使 JVM 事实能进入假设/requirement 协议。

**用户故事**：作为诊断 Agent，当用户提供了线程转储时，我能查询热点线程、指定线程和死锁；当提供了 GC 日志时，我能查询 GC 摘要与最近 Full GC；当提供了堆直方图时，我能查看主导类。每次调用都能绑定假设/要求，结果能追溯到 artifact 行号；没有对应快照时工具根本不出现；我不能通过工具执行命令或读取任意文件。

## 2. In scope

- `src/tracemind/tools/jvm.py`：六个工具 handler、输入模型、输出模型。
- `ToolContext.artifacts: ArtifactBundle | None`。
- `build_default_registry(..., artifacts=None)` 条件注册。
- `EvidenceKind` 新值与 `EvidenceProvenance.USER_ARTIFACT`（模型部分可在 T4 完成接线，但 T3 需要映射能引用）。
- `evidence_mapping.py` 的 JVM 分支。
- 工具单测、映射单测、绑定/截断/条件注册测试。

## 3. Out of scope

- evaluator symptom/mechanism、同线程规则、runtime 主循环、prompt（T4）。
- 报告 0.4（T5）。
- case/fixture/eval（T6）。
- live（T7）。
- 任意文件读取、任意命令、attach、hprof/JFR、网络。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T3-01 | 六个工具同步、只读、`extra="forbid"`、参数范围受限 | must |
| FR-T3-02 | 工具仅在所需 artifact 存在时注册；无 artifacts 时完全不出现 | must |
| FR-T3-03 | `jvm.get_thread_dump` 支持线程名/状态/死锁过滤和 limit | must |
| FR-T3-04 | `jvm.get_hot_threads` 合并 thread_cpu + thread_dump，按 CPU 排序 | must |
| FR-T3-05 | nid/TID 归一化匹配；未匹配输出 warning，不伪造线程 | must |
| FR-T3-06 | `jvm.get_deadlocks` 返回 JVM 报告的死锁段 | must |
| FR-T3-07 | `jvm.get_gc_summary` 返回次数/Full/停顿/heap/晋升失败 | must |
| FR-T3-08 | `jvm.get_gc_events` 支持 limit/full_only | must |
| FR-T3-09 | `jvm.get_heap_histogram` 支持 limit/class_pattern | must |
| FR-T3-10 | 所有输出 ≤32 KiB；列表/字符串有上限；带 artifact_ids/warnings | must |
| FR-T3-11 | 工具结果经 ToolExecutor 审计、绑定、去重和截断 | must |
| FR-T3-12 | 映射生成 THREAD_DUMP/THREAD_CPU/GC_EVENT/GC_SUMMARY/HEAP_SUMMARY | must |
| FR-T3-13 | evidence source_ref 指向真实 artifact 行；provenance=user_artifact | must |
| FR-T3-14 | 映射对非法 artifact id/行号跳过并 warning，不崩溃 | must |
| FR-T3-15 | 工具描述明确只读、用户快照、非实时 | must |

## 5. 工具契约

```python
class EvidenceToolMeta(BaseModel):
    hypothesis_id: str | None = None
    requirement_id: str | None = None

class GetThreadDumpInput(EvidenceToolMeta):
    thread_name: str | None = Field(None, max_length=128)
    state: str | None = Field(None, max_length=32)
    deadlock_only: bool = False
    limit: int = Field(20, ge=1, le=100)

class GetHotThreadsInput(EvidenceToolMeta):
    limit: int = Field(10, ge=1, le=100)
    min_cpu_percent: float = Field(1.0, ge=0.0, le=100.0)

class GetDeadlocksInput(EvidenceToolMeta):
    pass

class GetGcSummaryInput(EvidenceToolMeta):
    full_only: bool = False

class GetGcEventsInput(EvidenceToolMeta):
    limit: int = Field(20, ge=1, le=100)
    full_only: bool = False

class GetHeapHistogramInput(EvidenceToolMeta):
    limit: int = Field(20, ge=1, le=100)
    class_pattern: str | None = Field(None, max_length=128)
```

- `class_pattern` 只允许字母/数字/`._$*?` 和单空格；`*`/`?` 做简单通配，不接受正则、路径或控制字符。
- 线程名/状态过滤为大小写不敏感子串（线程名）或精确匹配（状态，大小写不敏感）。
- 结果统一包含 `artifact_ids`、`warnings`、`truncated`；工具错误使用既有错误码（TARGET_DENIED/INVALID_ARGS）。

### 5.1 输出形状

```python
class ThreadDumpResult(BaseModel):
    threads: list[dict]
    deadlocks: list[dict]
    artifact_ids: list[str]
    warnings: list[str]
    truncated: bool

class HotThreadsResult(BaseModel):
    samples: list[dict]          # tid/nid/cpu/command/state/thread_name/top_frame
    unmatched_tids: list[int]
    artifact_ids: list[str]
    warnings: list[str]
    truncated: bool

class GcSummaryResult(BaseModel):
    summary: dict
    artifact_ids: list[str]
    warnings: list[str]
    truncated: bool

class GcEventsResult(BaseModel):
    events: list[dict]
    artifact_ids: list[str]
    warnings: list[str]
    truncated: bool

class HeapHistogramResult(BaseModel):
    live: bool
    classes: list[dict]
    total_instances: int | None
    total_bytes: int | None
    artifact_ids: list[str]
    warnings: list[str]
    truncated: bool
```

- 输出通过 `model_dump()` 进入 ToolResult；executor 再做 32 KiB 截断。
- 单线程最多 8 帧；hot threads 最多 limit 条；Top-N 按工具参数。

## 6. 证据映射

| 工具 | 证据 | source_ref | content 关键字段 |
|---|---|---|---|
| get_thread_dump | 每线程 THREAD_DUMP | `artifact://<id>#Lstart-Lend` | name/nid/state/frames/locks |
| get_hot_threads | 每样本 THREAD_CPU | `artifact://<cpu-id>#Lline` | tid/nid/cpu/command |
| get_hot_threads 匹配线程 | THREAD_DUMP | `artifact://<dump-id>#Lstart-Lend` | thread_name/state/top_frames |
| get_deadlocks | 每段 THREAD_DUMP | `artifact://<dump-id>#Lstart-Lend` | threads/lock_ids |
| get_gc_summary | 一条 GC_SUMMARY | `artifact://<gc-id>#L1-LN` | totals/full/max/total pause/promotion |
| get_gc_events | 每事件 GC_EVENT | `artifact://<gc-id>#Lline` | type/cause/heap/pause |
| get_heap_histogram | 一条 HEAP_SUMMARY | `artifact://<heap-id>#L1-LN` | live/top classes/totals |

- `provenance = USER_ARTIFACT`。
- `tool_call_id` 由 `map_tool_result` 现有机制赋值。
- 未绑定 requirement 的 JVM 证据可作为 basis，但不能覆盖 requirement（复用 v0.3 规则）。
- 映射只处理成功结果；工具失败/空结果生成 0 条证据。

## 7. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T3-01 | 无 artifacts 时 registry 不含任何 jvm.* 工具 |
| AC-T3-02 | 只有 thread_dump 时注册 thread_dump/deadlocks，不注册 hot_threads/gc/heap |
| AC-T3-03 | 只有 thread_cpu 时不注册 hot_threads（需要两者） |
| AC-T3-04 | 六工具参数范围/额外字段/非法 pattern 被拒绝 |
| AC-T3-05 | thread dump 过滤/limit/死锁正确；无匹配返回空 + warning |
| AC-T3-06 | hot threads 正确映射 nid、排序、未匹配 TID 有 warning |
| AC-T3-07 | deadlocks 返回 JVM 报告段；无死锁返回空但不是错误 |
| AC-T3-08 | GC summary/events、heap histogram 输出与解析器一致 |
| AC-T3-09 | 工具结果 ≤32 KiB，列表/字符串上限生效 |
| AC-T3-10 | 所有调用进入 ToolExecutor 审计，绑定元数据进入 result/audit |
| AC-T3-11 | 映射产生正确 kind/provenance/source_ref；行号在文档范围内 |
| AC-T3-12 | 未绑定 JVM 证据不能覆盖 requirement（复用 workspace 规则） |
| AC-T3-13 | 映射遇到非法 artifact/行号跳过并 warning |
| AC-T3-14 | 工具无网络/subprocess/任意路径参数；静态扫描通过 |
| AC-T3-15 | 工具描述含只读/用户快照/非实时提示 |

## 8. 测试计划

- `tests/unit/test_jvm_tools.py`：条件注册、参数、过滤、hot threads、deadlocks、GC、heap、截断、绑定、失败结果。
- `tests/unit/test_jvm_evidence_mapping.py`：七种映射、source_ref、kind/provenance、非法行、空结果。
- `tests/unit/test_artifact_guard` 可在 T6 扩展静态无 exec/remote。

## 9. 风险与开放问题

- **TID 映射**：不同 top 版本可能把 COMMAND 放在最后一列；解析器负责取值，工具只做匹配。
- **死锁重复**：get_deadlocks 与 get_thread_dump 可能各生成一条证据；ledger 按 `(kind, source_ref)` 去重，复用现有语义。
- **Top-N 与证据**：映射只对返回的线程/事件生成证据，未返回的不算；这是有界设计，报告限制需说明。
- **工具输出大小**：32 KiB 截断由 executor 统一处理，映射看到的是执行后的结果。
- **错误码**：沿用现有工具错误模型，不新增 LLM 可伪造状态。

## 10. 验证命令

```bash
uv run pytest tests/unit/test_jvm_tools.py tests/unit/test_jvm_evidence_mapping.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T3 spec：六工具、条件注册、证据 kind/source_ref、绑定与截断 |
| 2026-10-23 | 实现并回填：六个只读工具、条件注册、artifact 引用校验、JVM 证据映射；定向 20 测试、全量 479 通过 |
