# TraceMind v0.4 — JVM 深度诊断设计

- **状态**：IMPLEMENTED（v0.4.0）
- **日期**：2026-10-23
- **索引**：[README](./README.md)
- **上一版本**：[v0.3 DESIGN](../003-grounded-diagnosis/DESIGN.md)

## 1. 设计目标

v0.4 在不引入远程工具、MCP、实时采集和二进制堆分析的前提下，把 JVM 文本快照纳入现有证据协议。关键设计原则：

1. **输入可控**：一个 manifest + 若干文本文件；路径、类型、大小、编码、服务名全部确定性校验。
2. **解析有界**：解析器只输出摘要和 Top-N，不把完整 dump 交给 LLM。
3. **证据可追溯**：每条 JVM 事实有 artifact id 和真实行号，报告可校验。
4. **确认不放松**：新增 symptom 覆盖，但 mechanism、替代假设、refute、工具证据规则不变。
5. **条件放宽**：只有提供 artifacts 时，同线程日志上下文才从强制变为可选。
6. **诚实标注**：用户快照不是 live 采集；只有快照没有代码机制时不能 confirmed。

## 2. 架构

```text
CLI --artifacts DIR
  |
  v
ArtifactLoader
  - 读取 manifest.json（严格 JSON）
  - 校验 schema/service/id/kind/path/symlink/size/encoding
  - 读取文本行（有界）
  v
ArtifactBundle                 DiagnosisRuntime
  - manifest                     - logs/code seed evidence
  - records[]                    - prompt artifact summary
  - by_kind(kind)                - same-thread rule
  - document(id)                  - repair/completion
  |                                   |
  v                                   v
Artifact parsers              ToolContext.artifacts
  - thread_dump                 |
  - thread_cpu                  v
  - gc_log                  ToolExecutor
  - heap_histogram             - jvm.* tools (conditional)
  |                            - validation/binding/audit/truncation
  v                                   |
JVM evidence  <---- evidence_mapping ---+
  - THREAD_DUMP / THREAD_CPU
  - GC_EVENT / GC_SUMMARY
  - HEAP_SUMMARY
  | provenance=user_artifact
  | source_ref=artifact://id#Lx-Ly
  v
Evaluator (symptom + mechanism)
  |
  v
Report schema 0.4 (artifacts[], citations, limitations)
```

## 3. Artifact 输入契约

### 3.1 目录与 manifest

```text
<artifacts-dir>/
  manifest.json
  thread-dump.txt
  thread-cpu.txt
  gc.log
  heap-histo.txt
```

`manifest.json`：

```json
{
  "schema_version": "1",
  "service": "order-service",
  "instance": "order-service-1",
  "captured_at": "2026-10-23T10:15:00+08:00",
  "artifacts": [
    {"id": "thread-dump", "kind": "thread_dump", "path": "thread-dump.txt"},
    {"id": "thread-cpu", "kind": "thread_cpu", "path": "thread-cpu.txt"},
    {"id": "gc-log", "kind": "gc_log", "path": "gc.log"},
    {"id": "heap-histo", "kind": "heap_histogram", "path": "heap-histo.txt"}
  ]
}
```

规则：

| 字段 | 规则 |
|---|---|
| `schema_version` | 必须为 `"1"` |
| `service` | 非空、≤128 字符；必须等于 CLI `--service` |
| `instance` | 可选、≤128 字符；只用于展示，不参与匹配 |
| `captured_at` | 可选 ISO-8601；只用于展示，不信任为时钟依据 |
| `artifacts` | 1..8 条；id 唯一；kind 必须是四种之一 |
| `id` | `^[a-z][a-z0-9_-]{0,31}$`；大小写敏感 |
| `path` | 相对路径；非空、≤256 字符；拒绝绝对路径、`..`、`.`、空段、反斜杠、NUL |
| 未知字段 | 拒绝（Pydantic `extra="forbid"`） |

### 3.2 文件安全与上限

- manifest ≤64 KiB；必须是 UTF-8；JSON 解析错误、非对象、数组为空均拒绝。
- artifact 文件必须是普通文件；拒绝 symlink（含路径中任一 symlink 组件）。
- 解析后的真实路径必须位于 artifacts 根目录下。
- 每种 kind 的上限：

| kind | 单文件字节 | 行数 | 说明 |
|---|---:|---:|---|
| `thread_dump` | 10 MiB | 500,000 | jstack 文本 |
| `thread_cpu` | 2 MiB | 100,000 | `top -H` / `ps -L` |
| `gc_log` | 20 MiB | 500,000 | 可能是长时间窗口 |
| `heap_histogram` | 5 MiB | 200,000 | `jmap -histo` |

- 总原始字节 ≤32 MiB；所有 artifact 合计行数 ≤500,000。
- 读取必须严格 UTF-8；解码失败拒绝整个 bundle（不静默替换）。
- 文件行尾统一为 `\n`；保留原始行内容用于解析，不修改文件。
- 允许一行以 `\r` 结尾（解析时去除）；空文件拒绝。
- 超过行数上限时拒绝，不截断文件；解析器输出有独立的 Top-N/帧数上限。

### 3.3 ArtifactBundle

```python
class ArtifactKind(StrEnum):
    THREAD_DUMP = "thread_dump"
    THREAD_CPU = "thread_cpu"
    GC_LOG = "gc_log"
    HEAP_HISTOGRAM = "heap_histogram"

class ArtifactSpec(BaseModel):
    id: str
    kind: ArtifactKind
    path: str

class ArtifactManifest(BaseModel):
    schema_version: Literal["1"]
    service: str
    instance: str | None = None
    captured_at: str | None = None
    artifacts: list[ArtifactSpec]

class ArtifactDocument:
    spec: ArtifactSpec
    source_name: str          # basename, 不含绝对路径
    lines: tuple[str, ...]
    byte_size: int
    line_count: int
    warnings: list[str]

class ArtifactRecord(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    source_name: str
    source_environment: Literal["user_provided"] = "user_provided"
    line_count: int
    byte_size: int
    truncated: bool = False
    warnings: list[str] = []

class ArtifactBundle:
    root: Path
    manifest: ArtifactManifest
    documents: tuple[ArtifactDocument, ...]
    records: tuple[ArtifactRecord, ...]

    def by_kind(self, kind: ArtifactKind) -> tuple[ArtifactDocument, ...]: ...
    def document(self, artifact_id: str) -> ArtifactDocument | None: ...
    def has_kind(self, kind: ArtifactKind) -> bool: ...
```

- `truncated` 当前恒为 `False`：超限直接拒绝；字段为报告契约保留。
- `warnings` 只放文件级提示（例如“heap histogram 非 :live”），解析器级 warnings 进入工具结果。
- `source_name` 只取 basename，报告不得出现绝对路径。

### 3.4 脱敏

`artifacts/redaction.py` 提供 `redact_text(text) -> tuple[str, list[str]]`：

- 命中的模式：`password`、`passwd`、`secret`、`token`、`authorization`、`api_key`、`apikey`、`access_key`、`credential`（大小写不敏感）。
- 支持 `key=value`、`key: value`、`key="value"`、`Bearer <token>`。
- 替换为 `[REDACTED]`，返回命中的字段类别（不返回原值）。
- 用于所有进入 evidence content / 工具输出 / 报告摘录的文本。
- 不修改 artifact 文件本身；不承诺覆盖所有秘密格式，只作为纵深防御。

### 3.5 CLI 行为

- 新增 `--artifacts PATH`，必须是已存在、可读目录。
- 加载发生在 provider 构建/日志解析/索引之前或至少在任何 run 产物创建之前；失败 `exit 2`。
- 错误信息只包含 manifest 相对文件名/artifact id，不输出秘密或完整内容。
- 未提供 `--artifacts` 时完全不注册 JVM 工具，行为与 v0.3 一致。

## 4. 解析器

所有解析器是纯函数：输入 artifact 文本行，输出 Pydantic 模型，不读文件、不访问网络、不调用 LLM。行号从 1 开始，指向原始 artifact。

### 4.1 线程转储 `thread_dump.py`

支持常见 `jstack` 输出：

```text
"pricing-exec-1" #31 prio=5 os_prio=0 tid=0x0000... nid=0x1a2c runnable [0x...]
   java.lang.Thread.State: RUNNABLE
        at com.example.pricing.PricingService.recalculate(PricingService.java:88)
        - locked <0x00000000d001> (a java.lang.Object)
```

解析：

- 线程头：name、Java thread id（`#`）、tid、nid、state（头部 `runnable` 等）、daemon。
- `java.lang.Thread.State:` 优先作为状态；缺失时用头部状态。
- 栈帧：`at fqcn.method(File.java:line)`，支持 native/unknown source；保留最多 8 帧。
- 锁行：`- locked`、`- waiting to lock`、`- parking to wait for`、`- waiting on`，保留最多 4 条。
- JVM 死锁段：从 `Found one Java-level deadlock:` 起，解析 `threadName:` 与 `waiting to lock` 的关系；同时识别 `Found N deadlocks.`。
- 线程数量上限 4096；超过时保留前 4096 并 warning。
- 所有自由文本字段（线程名、锁行、栈帧类名/方法名等）经统一脱敏并截断到 ≤512 字符；ID 类字段截断到 64。
- 线程块的 `line_start` 为线程头行，`line_end` 为该线程最后一个非空行；死锁段行号独立记录。
- 输出：

```python
class ThreadFrame(BaseModel):
    class_name: str
    method: str
    file: str | None
    line: int | None
    frame_index: int

class ThreadSnapshot(BaseModel):
    name: str
    java_id: str | None
    nid: str | None
    state: str | None
    daemon: bool
    line_start: int
    line_end: int
    frames: list[ThreadFrame]
    lock_events: list[str]
    deadlock_related: bool

class DeadlockInfo(BaseModel):
    threads: list[str]
    lock_ids: list[str]
    line_start: int
    line_end: int

class ThreadDumpSummary(BaseModel):
    threads: list[ThreadSnapshot]
    deadlocks: list[DeadlockInfo]
    warnings: list[str]
    thread_count: int
    truncated: bool
```

- 工具结果只返回过滤后的线程和摘要，不返回整个 dump。
- 解析不到线程头时返回空列表 + warning，由工具返回“无可解析线程”的确定性结果。

### 4.2 线程 CPU `thread_cpu.py`

支持：

1. `top -H -p <pid>` 常见列：`PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND`。
2. `ps -L -p <pid> -o lwp,pcpu,comm`：`LWP %CPU COMMAND`。
3. 可选 `ps -eLo pid,tid,pcpu,comm` 变体（含 TID 列）。

输出：

```python
class ThreadCpuSample(BaseModel):
    tid_decimal: int
    tid_hex: str        # nid 形式，如 "0x1a2c"
    cpu_percent: float
    command: str | None
    line_number: int

class ThreadCpuSummary(BaseModel):
    samples: list[ThreadCpuSample]
    warnings: list[str]
    truncated: bool
```

- 按 `%CPU` 降序、同值按 line_number 稳定排序。
- 上限 2048 个样本；只保留有数字 TID 的行。
- `tid_hex` 由十进制 TID 转换（小写、`0x` 前缀）；用于与 jstack `nid` 匹配。
- 无法识别的行只产生一条聚合 warning（避免 warning 爆炸）。

### 4.3 GC 日志 `gc_log.py`

支持两类常见文本：

1. **JDK 9+ unified logging**：
   ```text
   [2026-10-23T10:00:00.123+0800][info][gc] GC(12) Pause Young (Normal) (G1 Evacuation Pause) 512M->256M(1024M) 12.345ms
   ```
2. **JDK 8 常见格式**：
   ```text
   2026-10-23T10:00:00.123+0800: 12.345: [GC (Allocation Failure) [PSYoungGen: 512K->256K(1024K)] 512K->300K(2048K), 0.0123456 secs]
   ```
   以及 Full GC 变体、`[Full GC (Ergonomics) ...]`、`[GC (Metadata GC Threshold) ...]`。

解析字段：

```python
class GcEvent(BaseModel):
    event_type: str          # young/full/other
    cause: str | None
    heap_before_mb: float | None
    heap_after_mb: float | None
    heap_total_mb: float | None
    pause_ms: float | None
    line_number: int
    raw_summary: str         # 脱敏/截断后，不含原始时间戳长文本

class GcSummary(BaseModel):
    events: list[GcEvent]    # 最多 2000 条保留
    total_events: int
    young_events: int
    full_events: int
    max_pause_ms: float | None
    total_pause_ms: float
    promotion_failures: int
    warnings: list[str]
    truncated: bool
```

- `full` 判定：`Pause Full`、`[Full GC`、`Full GC (`。
- heap 字段解析 `before->after(total)`；支持 `K/M/G` 单位，统一换算 MiB。
- 无法识别为 GC 事件的行不报错；若一条事件也解析不到，返回 warning。
- `promotion_failures` 识别 `to-space exhausted`、`Promotion failed`、`Allocation Failure` 中的晋升失败关键字（仅计数，不推断根因）。
- 事件保留上限 2000；summary 统计基于解析到的全部事件（可在上限内）；超过上限时 `truncated=True` 并 warning。
- GC 摘要不是“泄漏证明”：只提供停顿、Full GC 次数、GC 后 heap 是否回落等事实。

### 4.4 堆直方图 `heap_histogram.py`

支持 `jmap -histo:live` 与 `jmap -histo`：

```text
 num     #instances         #bytes  class name (module)
-------------------------------------------------------
   1:       1234567      98765432  [B (java.base@17.0.1)
   2:        234567      12345678  com.example.ReportEntry
```

解析：

```python
class HeapClassStat(BaseModel):
    rank: int
    instances: int
    bytes: int
    class_name: str
    line_number: int

class HeapHistogramSummary(BaseModel):
    live: bool
    classes: list[HeapClassStat]   # 最多 200 条
    total_instances: int | None
    total_bytes: int | None
    warnings: list[str]
    truncated: bool
```

- `live = ":live"` 出现在 `jmap -histo:live` 标题/命令行中；无法判断时 warning。
- 解析表头后的 `rank: instances bytes class`；支持带模块后缀。
- 过滤 `Total` 行并解析总量；只保留前 200 类（按原文件顺序，通常已按 bytes 降序）。
- 非 `:live` 时固定 warning：“heap histogram may include unreachable objects”。

## 5. 证据模型

### 5.1 枚举

```python
class EvidenceKind(StrEnum):
    # v0.3
    LOG_EVENT = "log_event"
    LOG_THREAD_CONTEXT = "log_thread_context"
    STACK_FRAME = "stack_frame"
    SOURCE_CODE = "source_code"
    CALL_PATH = "call_path"
    SQL = "sql"
    ANNOTATION = "annotation"
    CONFIG = "config"
    DB_ROW = "db_row"
    DB_SCHEMA = "db_schema"
    # v0.4
    THREAD_DUMP = "thread_dump"
    THREAD_CPU = "thread_cpu"
    GC_EVENT = "gc_event"
    GC_SUMMARY = "gc_summary"
    HEAP_SUMMARY = "heap_summary"

class EvidenceProvenance(StrEnum):
    LOG_PARSER = "log_parser"
    AST_INDEX = "ast_index"
    TOOL = "tool"
    FAKE_VERIFICATION = "fake_verification"
    USER_ARTIFACT = "user_artifact"
```

### 5.2 内容与引用

| kind | source_ref | content 关键字段 |
|---|---|---|
| `THREAD_DUMP` | `artifact://thread-dump#Lx-Ly` | `threads[]`，每个含 name/nid/state/daemon/frames（≤8）/lock_events（≤4） |
| `THREAD_CPU` | `artifact://thread-cpu#Lx-Ly` | `samples[]`（≤64），含 tid_decimal/tid_hex/cpu_percent；可含 matched_threads |
| `GC_EVENT` | `artifact://gc-log#Lx` 或 `#Lx-Ly` | event_type/cause/heap before/after/total/pause_ms |
| `GC_SUMMARY` | `artifact://gc-log#L1-LN` | totals/full_events/max_pause_ms/total_pause_ms/promotion_failures |
| `HEAP_SUMMARY` | `artifact://heap-histo#L1-LN` | live/top_classes[]/total_instances/total_bytes |

- evidence 的 `provenance` 固定 `user_artifact`。
- 每条证据通过 ToolExecutor 产生时带 `tool_call_id`；seed 证据（如果向 ledger 预置 artifact 摘要）可无 tool_call_id，但不能计入 requirement coverage 除非绑定并评估。
- `content` 中的字符串截断到 512 字符；列表上限见上表。
- `warnings` 进入 content，不进入 source_ref。

### 5.3 ArtifactRecord 落盘

`RunResult.artifacts: list[ArtifactRecord]` 保存 bundle 的 records（无绝对路径）。报告和 run_meta 直接使用。

## 6. JVM 工具

所有工具同步、只读、`requires_approval=False`，输出 ≤32 KiB，参数 Pydantic `extra="forbid"`。所有工具支持 `EvidenceToolMeta`（`hypothesis_id`/`requirement_id`），只有绑定后才计入 requirement。

| 工具 | artifact 条件 | 输入 | 输出 | evidence kind |
|---|---|---|---|---|
| `jvm.get_thread_dump` | thread_dump | `thread_name?`, `state?`, `deadlock_only=false`, `limit=20` | 线程摘要、帧、锁、死锁 | `THREAD_DUMP` |
| `jvm.get_hot_threads` | thread_cpu + thread_dump | `limit=10`, `min_cpu_percent=1.0` | CPU 排序、nid 映射、栈顶、未匹配 TID | `THREAD_CPU` + `THREAD_DUMP` |
| `jvm.get_deadlocks` | thread_dump | 无 | JVM 报告的死锁/环、线程、锁 | `THREAD_DUMP` |
| `jvm.get_gc_summary` | gc_log | `full_only=false` | GC 次数、Full GC、停顿、heap、晋升失败 | `GC_SUMMARY` |
| `jvm.get_gc_events` | gc_log | `limit=20`, `full_only=false` | 最近/Full GC 事件 | `GC_EVENT` |
| `jvm.get_heap_histogram` | heap_histogram | `limit=20`, `class_pattern?` | Top-N 类、实例/字节、live 标记 | `HEAP_SUMMARY` |

规则：

- `limit` 范围 1..100；`min_cpu_percent` 0..100；`class_pattern` 最长 128，作为简单大小写不敏感子串/通配符（只允许字母数字 `.$_*?`），不执行正则。
- `jvm.get_hot_threads` 必须两种 artifact 都存在；否则不注册。
- 映射：十进制 TID → `0x` + 小写十六进制，与 jstack `nid` 比较（去 `0x`/前导零归一化）。
- CPU 样本无匹配线程时，输出 `unmatched_tids` + warning；不伪造线程名。
- 工具结果包含 `artifact_ids`、`source_refs`、warnings、truncated；不返回完整文件。
- 工具描述明确“用户提供的时间点文本快照，不是实时采集”。

### 6.1 evidence_mapping

新增确定性映射分支：

- `jvm.get_thread_dump` → 每个返回线程一条 `THREAD_DUMP`，`source_ref` 指向线程块起止行；无匹配时无证据。
- `jvm.get_hot_threads` → 每个 CPU 样本一条 `THREAD_CPU`（指向线程 CPU 行），匹配到的线程另生成 `THREAD_DUMP`（指向线程块）。
- `jvm.get_deadlocks` → 每个死锁段一条 `THREAD_DUMP`，content 含 threads/locks。
- `jvm.get_gc_summary` → 一条 `GC_SUMMARY`，`source_ref=artifact://id#L1-LN`。
- `jvm.get_gc_events` → 每个事件一条 `GC_EVENT`，指向事件行。
- `jvm.get_heap_histogram` → 一条 `HEAP_SUMMARY`，`source_ref=artifact://id#L1-LN`，content 含 Top-N。
- 所有映射检查 artifact id 属于 bundle，行号在文档范围内；不合法时跳过并 warning（工具应保证合法）。

## 7. 覆盖与运行时

### 7.1 覆盖集合

```python
SYMPTOM_KINDS = frozenset({
    LOG_EVENT, LOG_THREAD_CONTEXT, STACK_FRAME,
    THREAD_DUMP, THREAD_CPU, GC_EVENT, GC_SUMMARY, HEAP_SUMMARY,
    DB_ROW,
})
MECHANISM_KINDS = frozenset({
    SOURCE_CODE, CALL_PATH, SQL, ANNOTATION, CONFIG, DB_SCHEMA,
})
```

- 替代现有 `LOG_KINDS`/`CODE_KINDS` 的确认覆盖检查；排序/评分可沿用同类计数。
- 原先的 log/code 语义通过字符串 warning 保留为“缺少 symptom/mechanism 证据”。
- 确认仍要求至少一个工具来源的 supporting evidence；seed artifact 摘要不能单独满足。

### 7.2 同线程上下文规则

```python
requires_same_thread_context = primary.thread is not None and artifacts is None
required_thread() -> primary.thread if requires_same_thread_context else None
```

- 有 artifacts：不要求同线程日志上下文；`evaluate_current` 传 `require_log_thread_context=False`。
- 无 artifacts：保持 v0.3 行为（主事件有线程号时必须有已评估且线程匹配的上下文）。
- `thread_context_assessed`、`stop_repair_reason`、`complete_if_confirmed` 全部使用同一布尔规则，避免路径不一致。
- 报告/limitations 说明“JVM 快照为用户提供的时间点数据，不要求同线程上下文”。

### 7.3 Prompt

- 用户 prompt 新增 “JVM artifacts” 摘要：id、kind、source_name、line_count、warnings；不包含完整内容。
- 可用工具列表只展示已注册工具。
- System prompt 增加通用 JVM 分析指导：
  - CPU：先看线程 CPU，映射 nid → jstack，区分 GC/编译线程与业务线程；用 GC/deadlock 排除其他原因。
  - 内存/OOM：GC Summary 的 Full GC 频率与 GC 后 heap 是否回落、heap histogram 的主导类，再找代码中的无界集合/缓存/大对象；单次快照不能证明泄漏。
  - 首轮规划：有 thread CPU/thread dump 时分别提出 CPU-bound 应用代码候选与 blocking/lock/GC 候选；有 GC 日志/heap histogram 时分别提出 live heap 增长候选与容量/单次大对象候选；不要用 “or” 把机制合并成一个假设。
  - 跨线程：请求线程不一定等于 CPU 热点线程；热点线程可能是另一个 RUNNABLE 业务线程，不能用请求线程的等待状态直接否定 CPU 饱和。
  - 日志上下文：如果 requirement 依赖主线程日志上下文，必须用 `logs.get_thread_context` 获取并绑定，不能直接评估 seeded context。
  - 所有 artifact 结论标注为用户快照，不声称 live。
- 不出现 case id、fixture 路径、期望类名/方法名/答案。
- 上述指导是 live 调试后补充的通用规则；没有加入 case 名称、类名或预期答案。参见 [T7 task §6](./T7-live-docs-release/task.md)。
- `_incident_lines` 展示 cause chain；`_find_seed_matches` 在主栈未命中时尝试 cause frames。

### 7.4 运行时接线

- `DiagnosisRuntime(..., artifacts: ArtifactBundle | None = None)`。
- `ToolContext.artifacts`；`build_default_registry(..., artifacts=None)` 条件注册。
- `RunResult.artifacts` 与 `run_meta["artifacts"]` 写入 records。
- 原有 budget/repair/stop/event 语义不变；JVM 工具调用计入预算。

## 8. 报告 schema 0.4

### 8.1 新字段

```json
{
  "schema_version": "0.4",
  "artifacts": [
    {
      "artifact_id": "thread-dump",
      "kind": "thread_dump",
      "source_name": "thread-dump.txt",
      "source_environment": "user_provided",
      "line_count": 123,
      "truncated": false,
      "warnings": []
    }
  ]
}
```

- `sources` 增加 `category="artifact"`（或等价结构），仅展示 artifact id/source_name/kind，不展示绝对路径。
- `validation` 增加：
  - `artifact_citations_valid`：所有 `artifact://` 引用都能解析到存在的 artifact 和合法行号。
  - `artifacts_labeled`：提供的 artifact 全部标记 `user_provided`。
- `limitations` 自动追加：
  - “JVM snapshots are user-provided point-in-time text files; no live attach or collection was performed.”
  - “Heap dump/JFR was not parsed; CPU/memory conclusions are limited to the snapshot window.”
  - 若只有 artifact 无代码机制：“No code mechanism evidence was found; JVM-only evidence cannot confirm a root cause.”
- report status 仍由 evaluator 决定；artifact 存在不自动提升状态。

### 8.2 引用校验

- 支持 scheme：`repo://`、`log://`、`db://`、`artifact://`。
- `artifact://<id>#Lx-Ly`：id 必须存在；x/y 为正整数、x≤y、y≤line_count；单点 `#Lx` 等价 `#Lx-Lx`。
- 非法格式/不存在/越界均使 `citations_valid=false`，并记录具体 source_ref（截断）。
- 报告 builder 只从 evidence/source 生成引用，不允许 LLM 自由写 source_ref。

### 8.3 CLI

- `--artifacts PATH`（可选目录），加载失败 `exit 2`。
- `schema_version` 和 run_meta 写 `0.4`。
- JSON/文本摘要展示 artifact 数量/类型、JVM 证据数。
- 退出码保持不变。

## 9. 评测设计

### 9.1 Case

| Case | 症状 | 真实原因 | 关键 artifacts | 备选 |
|---|---|---|---|---|
| `v04-j1-cpu-high` | 请求超时/高延迟，CPU 高 | `PricingService.recalculate` 热点循环 | thread dump、thread cpu、正常 GC 日志 | GC 压力、锁竞争、下游等待 |
| `v04-j2-memory-oom` | `OutOfMemoryError: Java heap space` | 静态 `ReportCache` 无界增长 | GC 日志（多次 Full GC）、heap histogram | 堆太小、单次大对象 |

- 两个 case 的日志、仓库、artifacts、mock 脚本、expected 均为合成 fixture。
- expected 只在 pytest/expected 文件中；runtime/prompt 不含 case 标识或答案。
- 离线断言：schema 0.4、Top-1、expected evidence kinds、artifact refs 有效、artifact 标注、remediation 接地、无禁止/失败工具。
- 负向：仅 thread dump 无 CPU → CPU 假设不能 confirmed；正常 GC → GC 压力 refute；仅 heap histogram/GC → OOM 最多 supported；路径/大小/service/injection 安全测试。

### 9.2 无远程/无执行静态检查

`tests/eval/test_no_remote_or_exec.py` 扫描 `src/tracemind`：

- 不允许 `subprocess`、`os.system`、`socket`、`requests`、`httpx`、`jstack`/`jcmd`/`jmap` 执行调用。
- JVM 工具只能通过 `ArtifactBundle` 读已校验文件，不得接受任意路径参数。
- 允许 DeepSeek SDK 的网络调用（既有 `llm/deepseek.py` 明确例外）。

## 10. 安全与隐私

- manifest/artifact 路径不进入报告；只展示 basename 和 artifact id。
- artifact 文本进入证据/工具结果/报告前脱敏。
- 不读取 manifest 之外的文件；不跟随 symlink。
- 不支持任意文件路径参数；工具只接受 artifact id 隐含的 bundle 文档。
- 输出大小、线程/帧/事件/类数量、prompt 摘要全部有上限。
- 静态禁止执行 JVM 命令/网络（LLM 客户端除外）。
- 真实 Key 只从 env/.env 读取，永不写入产物。

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 文本格式差异 | 解析遗漏/误判 | 明确支持格式、逐行容错、warnings、fixture 覆盖变体 |
| nid/TID 映射失败 | CPU 热点无法关联栈 | 输出 unmatched + warning；不伪造线程 |
| 快照误判为根因 | 过度确认 | 必须有 mechanism；只有快照最多 supported；报告限制 |
| 同线程放宽被滥用 | 旧 case 回归 | 仅 artifacts 存在时放宽；无 artifacts 全量回归；替代/refute 不变 |
| prompt 膨胀 | token/上下文超限 | 只放摘要和 Top-N；工具/证据上限 |
| 大文件/畸形 manifest | 内存/解析问题 | 严格大小/行数/数量/编码/路径校验 |
| 报告泄露路径/秘密 | 隐私 | basename、脱敏、secret scan、引用校验 |
| live 非确定性 | 结论不稳 | opt-in、固定预算、如实记录 |

## 12. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 初稿：artifact 契约、四解析器、六个工具、evidence kind、symptom/mechanism、报告 0.4、两 case |
| 2026-10-23 | T1–T6 实现：artifact 加载/解析、JVM 工具与证据、覆盖模型、报告 0.4、CPU/OOM 离线评测 |
| 2026-10-23 | T7 实现：opt-in live 两 case、live CLI 冒烟、0.4.0；补充通用 JVM 首轮候选/跨线程/日志上下文绑定指导，OOM 备选假设与 T6 对齐（移除“GC 参数”） |
