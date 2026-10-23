# T2 — JVM 文本解析器 Spec

- **任务 ID**：T2
- **状态**：implemented
- **依赖**：T1
- **下游**：T3、T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §4](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

T1 只负责把用户提供的 JVM 文本安全加载进来，无法把 jstack/top/GC/histo 变成可绑定、可引用的证据事实。v0.4 需要确定性解析这些文本，同时避免把整份 dump 交给 LLM、避免把无法识别的行猜成事实。

T2 实现四个纯文本解析器：线程转储、线程 CPU、GC 日志、堆直方图。解析器只读 `lines`，输出有行号、有上限、带 warnings 的 Pydantic 模型，不访问文件/网络、不调用 LLM。

**用户故事**：作为运行时，我能把线程转储解析成线程/状态/帧/锁/死锁；把 top -H 解析成 TID/%CPU；把 GC 日志解析成 Full GC/停顿/heap 变化；把 jmap -histo 解析成类/实例/字节。每条事实都能指回原始行号；无法识别时我得到 warning，而不是被编造的结果。

## 2. In scope

- `src/tracemind/artifacts/parsers/common.py`：行号、单位换算、脱敏/截断、稳定排序辅助。
- `thread_dump.py`：JDK 8/11/17 `jstack` 常见文本。
- `thread_cpu.py`：`top -H -p PID`、`ps -L -p PID -o lwp,pcpu,comm`。
- `gc_log.py`：JDK 9+ unified logging、JDK 8 常见 GC 行。
- `heap_histogram.py`：`jmap -histo[:live]`。
- 解析器单元测试与畸形输入/上限测试。

## 3. Out of scope

- 文件加载、manifest 校验（T1）。
- 工具注册、参数校验、证据映射（T3）。
- 运行命令、attach JVM、解析二进制 `.hprof`/JFR。
- 完整 JVM 调优建议、泄漏判定。
- 非文本（PDF/HTML/JSON）GC 日志。
- 其他 JDK 版本的冷门格式；不支持时 warning/空结果。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T2-01 | 所有解析器是纯函数，输入 sequence[str]，输出 frozen/Pydantic 模型 | must |
| FR-T2-02 | 所有行号从 1 开始，指向原始 artifact 行；不因过滤改变行号 | must |
| FR-T2-03 | 线程转储解析线程头、状态、栈帧、锁行、JVM 死锁段 | must |
| FR-T2-04 | 线程帧最多 8 条、锁事件最多 4 条/线程、线程最多 4096 | must |
| FR-T2-05 | 线程 CPU 支持 top/ps 常见列，输出十进制 TID、十六进制 nid、%CPU | must |
| FR-T2-06 | 线程 CPU 按 %CPU 降序、同值按行号稳定排序；样本上限 2048 | must |
| FR-T2-07 | GC 日志解析 Young/Full、cause、before/after/total heap、pause_ms | must |
| FR-T2-08 | GC 汇总 Full 次数、最大/总停顿、晋升失败计数、事件上限 2000 | must |
| FR-T2-09 | 堆直方图解析 rank/instances/bytes/class，识别 `:live`、总量 | must |
| FR-T2-10 | 堆类最多保留 200 条；非 live 固定 warning | must |
| FR-T2-11 | 无法识别的行不产生事实，只产生有界聚合 warning | must |
| FR-T2-12 | 空输入/畸形输入返回空结果/模型和 warning，不抛未捕获异常 | must |
| FR-T2-13 | 输出字符串截断到 512 字符；不返回完整 dump | must |
| FR-T2-14 | 解析结果确定性；相同输入多次结果一致 | must |

## 5. 接口/数据契约

```python
def parse_thread_dump(lines: Sequence[str]) -> ThreadDumpSummary: ...
def parse_thread_cpu(lines: Sequence[str]) -> ThreadCpuSummary: ...
def parse_gc_log(lines: Sequence[str]) -> GcLogResult: ...
def parse_heap_histogram(lines: Sequence[str], *, live_hint: bool = False) -> HeapHistogramSummary: ...
```

模型：

```python
class ThreadFrame(BaseModel):
    class_name: str
    method: str
    file: str | None = None
    line: int | None = None
    frame_index: int

class ThreadSnapshot(BaseModel):
    name: str
    java_id: str | None = None
    nid: str | None = None
    state: str | None = None
    daemon: bool = False
    line_start: int
    line_end: int
    frames: list[ThreadFrame] = []
    lock_events: list[str] = []
    deadlock_related: bool = False

class DeadlockInfo(BaseModel):
    threads: list[str]
    lock_ids: list[str]
    line_start: int
    line_end: int

class ThreadDumpSummary(BaseModel):
    threads: list[ThreadSnapshot]
    deadlocks: list[DeadlockInfo]
    thread_count: int
    warnings: list[str]
    truncated: bool = False

class ThreadCpuSample(BaseModel):
    tid_decimal: int
    tid_hex: str
    cpu_percent: float
    command: str | None = None
    line_number: int

class ThreadCpuSummary(BaseModel):
    samples: list[ThreadCpuSample]
    warnings: list[str]
    truncated: bool = False

class GcEvent(BaseModel):
    event_type: Literal["young", "full", "other"]
    cause: str | None = None
    heap_before_mb: float | None = None
    heap_after_mb: float | None = None
    heap_total_mb: float | None = None
    pause_ms: float | None = None
    line_number: int
    summary: str

class GcSummary(BaseModel):
    total_events: int
    young_events: int
    full_events: int
    max_pause_ms: float | None
    total_pause_ms: float
    promotion_failures: int
    warnings: list[str]

class GcLogResult(BaseModel):
    summary: GcSummary
    events: list[GcEvent]  # 最多 2000
    truncated: bool = False

class HeapClassStat(BaseModel):
    rank: int
    instances: int
    bytes: int
    class_name: str
    line_number: int

class HeapHistogramSummary(BaseModel):
    live: bool
    classes: list[HeapClassStat]
    total_instances: int | None
    total_bytes: int | None
    warnings: list[str]
    truncated: bool = False
```

### 5.1 行号与 source_ref 支持

- 线程块：`line_start` 为线程头行，`line_end` 为该线程最后一个非空行。
- 死锁段：`line_start`/`line_end` 覆盖可解析死锁段。
- CPU 样本：`line_number` 为原始行。
- GC 事件：`line_number` 为事件行；summary 用 `#L1-LN`。
- Heap：类行号；summary 用 `#L1-LN`。

### 5.2 排序

- 线程 CPU：`(-cpu_percent, line_number)`。
- 线程转储：保持文件顺序。
- GC events：保持文件顺序；工具层选择最近 N。
- Heap classes：保持文件顺序（通常已按 bytes 降序）。

## 6. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T2-01 | 解析典型 JDK 17 jstack：线程名/id/nid/状态/帧/锁正确 |
| AC-T2-02 | 解析 JDK 8 jstack（`java.lang.Thread.State` 与旧状态）正确 |
| AC-T2-03 | 可识别 `Found one Java-level deadlock` 与线程/锁；无线程信息时 warning |
| AC-T2-04 | 线程数/帧数/锁事件超限时有 truncated/warning，行号不乱 |
| AC-T2-05 | top -H 与 ps -L 均能解析 TID/%CPU；十六进制 nid 正确 |
| AC-T2-06 | CPU 样本排序稳定；非数字/表头行被忽略且 warning 有界 |
| AC-T2-07 | JDK 9+ GC 日志解析 Young/Full、heap、pause |
| AC-T2-08 | JDK 8 GC 日志解析 Full GC、单位 K/M/G、pause |
| AC-T2-09 | GC 空输入/无 GC 行返回 warning，不抛异常 |
| AC-T2-10 | heap histogram 解析 Total、live 标记、类名模块后缀 |
| AC-T2-11 | 非 :live 产生固定 warning；空表返回 warning |
| AC-T2-12 | 四个解析器相同输入结果完全一致（确定性） |
| AC-T2-13 | 输出字符串 ≤512 字符；不包含完整文件内容 |

## 7. 测试计划

- `tests/unit/test_jvm_thread_dump.py`：JDK 8/17 fixture、状态、帧、锁、死锁、上限、空。
- `tests/unit/test_jvm_thread_cpu.py`：top/ps、排序、TID 十六进制、表头、空、上限。
- `tests/unit/test_jvm_gc_log.py`：unified/JDK8、Young/Full、单位、pause、晋升失败、空、上限。
- `tests/unit/test_jvm_heap_histogram.py`：live/非 live、Total、模块后缀、上限、空。
- 直接内联文本，不新增二进制；fixture 小、可读。

## 8. 风险与开放问题

- **格式漂移**：只承诺 DESIGN 列出的常见格式；未知行 warning，不猜测。
- **JDK 8 多行 GC**：一条 GC 可能跨多行；首版以首行解析，缺失字段允许为空，并在 warning 中说明。
- **状态识别**：头部状态与 `java.lang.Thread.State` 不一致时以后者为准；两者都缺时 state=None。
- **nid 归一化**：输出小写 `0x` + 去前导零；匹配逻辑在 T3。
- **上限**：解析器内部上限必须与工具输出上限分开；解析器保留足够数据供筛选，但不超过 2000/4096。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_jvm_thread_dump.py tests/unit/test_jvm_thread_cpu.py tests/unit/test_jvm_gc_log.py tests/unit/test_jvm_heap_histogram.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T2 spec：四类文本解析器、行号、上限、warnings、确定性 |
| 2026-10-23 | 实现回填：四解析器完成；线程块增加 `line_end`；所有自由文本统一脱敏并 ≤512 字符；30 个专项测试通过 |
