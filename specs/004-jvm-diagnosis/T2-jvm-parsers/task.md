# T2 — JVM 文本解析器 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T2
- **状态**：implemented
- **依赖**：T1
- **下游**：T3、T4、T5、T6、T7

## 1. 实施顺序

1. **确认格式**
   - 阅读 T2 spec 与 [DESIGN §4](../DESIGN.md)。
   - 确认支持/不支持格式；未知行只 warning。

2. **先写测试**
   - 四个 `tests/unit/test_jvm_*.py`，以内联文本为主。
   - 覆盖 JDK 8/17、空输入、畸形输入、上限、确定性、行号。
   - 测试先失败。

3. **公共工具**
   - `parsers/common.py`：`truncate_text`、`parse_units_mb`、`normalize_nid`、warning 汇总、行遍历。
   - 不引入第三方依赖。

4. **线程转储**
   - 状态机按空行/线程头切块。
   - 解析头部、`Thread.State`、栈帧、锁、死锁段。
   - 上限 4096 线程、8 帧、4 锁；超限 truncated。
   - 空/畸形 warning。

5. **线程 CPU**
   - 表头计数解析 top/ps；支持固定列位置与空白分割。
   - TID 十进制→小写 0x 十六进制；排序。
   - 样本上限 2048；warning 聚合。

6. **GC 日志**
   - 识别 unified 与 JDK 8 首行；解析类型/cause/heap/pause。
   - 汇总 Full/Young/停顿/晋升失败；event 上限 2000。
   - 单位 K/M/G → MiB；无法识别 warning。

7. **堆直方图**
   - 识别标题 live 标记；解析 rank 行和 Total 行；类名保留模块后缀。
   - 最多 200 类；非 live warning；空 warning。

8. **回归**
   - 全量离线测试；ruff/mypy；回填。

## 2. 交付物

- [x] `src/tracemind/artifacts/parsers/__init__.py`
- [x] `src/tracemind/artifacts/parsers/common.py`
- [x] `src/tracemind/artifacts/parsers/thread_dump.py`
- [x] `src/tracemind/artifacts/parsers/thread_cpu.py`
- [x] `src/tracemind/artifacts/parsers/gc_log.py`
- [x] `src/tracemind/artifacts/parsers/heap_histogram.py`
- [x] 四个解析器单测

## 3. Definition of Done

- [x] AC-T2-01 至 AC-T2-13 全部满足。
- [x] 行号指向原始行；排序稳定；相同输入结果一致。
- [x] 空/畸形输入不抛未捕获异常。
- [x] 无完整 dump 进入输出；字符串截断。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_jvm_thread_dump.py tests/unit/test_jvm_thread_cpu.py tests/unit/test_jvm_gc_log.py tests/unit/test_jvm_heap_histogram.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **解析器复杂度**：优先覆盖 case 所需格式，但测试必须包含变体；不为冷门格式写猜测逻辑。
- **GC 多行**：首版首行解析；字段缺失允许 None，避免误判。
- **线程死锁段**：只解析 JVM 明确报告的死锁，不自己构造环。
- **warning 爆炸**：只保留首条/聚合 warning，不逐行重复。
- **T3 契约**：工具层过滤/排序，不把解析器当输出层。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | `uv run pytest tests/unit/test_jvm_thread_dump.py tests/unit/test_jvm_thread_cpu.py tests/unit/test_jvm_gc_log.py tests/unit/test_jvm_heap_histogram.py -q` | PASS | 30 passed |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS | 459 passed, 6 skipped（live 默认跳过） |
| 2026-10-23 | Claude | `uv run ruff check .` | PASS | All checks passed |
| 2026-10-23 | Claude | `uv run mypy src` | PASS | 58 source files |

实现备注：

- `common.py` 提供 `truncate_text`、`parse_size_mb`、`normalize_nid`、`nid_from_tid`、`add_warning` 等辅助；`parse_size_mb` 为实际命名。
- 线程块记录 `line_start`/`line_end`；死锁段的锁 ID 统一为不带尖括号的十六进制值。
- GC cause 使用括号平衡扫描，保留 `System.gc()` 等嵌套内容；pause 事件保留原始精度，汇总时再四舍五入。
- 所有自由文本字段经脱敏/截断（≤512，ID ≤64）；专项测试覆盖死锁空段、锁上限、长值截断与四解析器确定性。
