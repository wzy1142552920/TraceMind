# TraceMind v0.4 — JVM 深度诊断 SDD

- **状态**：COMPLETE（T1–T7 implemented，v0.4.0）
- **日期**：2026-10-23
- **父设计**：[TraceMind v2.0](../../docs/TraceMind_Agent_System_Design_v2.md)
- **上一版本**：[v0.3 证据落地的鉴别诊断](../003-grounded-diagnosis/README.md)
- **目标版本**：`0.4.0`

## 1. 目标与范围

v0.3 已把“异常日志 → 证据账本 → 多假设鉴别 → 代码/只读数据验证 → 接地修复建议”的主链路跑通，但它的证据模型偏向**单次同步请求**：主异常线程 + 同线程日志上下文 + 代码/SQL + 单行数据。CPU 高、内存高、OOM 这类高频 JVM 问题通常跨线程、全局、需要运行时快照，v0.3 无法承载。

v0.4 的目标不是增加一个“JVM 工具列表”，而是让**用户提供的 JVM 文本快照**进入现有证据协议：

1. 用户通过 `--artifacts DIR` 提供 jstack 线程转储、`top -H`/`ps -L` 线程 CPU、GC 日志、`jmap -histo` 堆直方图。
2. 四类快照被解析成有行号、有上限、可截断、可审计的结构化证据，并映射到新的 evidence kind。
3. LLM 通过只读、参数受限的 JVM 工具查询热点线程、线程状态/死锁、GC 压力、堆统计，再结合代码定位机制。
4. 确定性 evaluator 用 `symptom` / `mechanism` 覆盖替代硬编码的 log/code 覆盖；快照可满足 symptom，代码/SQL/配置仍是 mechanism。
5. 报告升级为 schema 0.4，包含 artifact 元数据、`artifact://` 引用校验和快照限制；不声称 live attach 或生产结论。
6. 新增两个可重复的离线 case：`v04-j1-cpu-high`、`v04-j2-memory-oom`，并补 opt-in live 验证。

**不做 MCP、不接真实远程数据源、不做其他问题域**（MyBatis XML/N+1/慢 SQL、Redis、DB 死锁、Spring 事务/AOP、连接池等后移到 v0.5+）。

### 主业务流程

```text
异常日志文件 + Java 仓库 + JVM 文本快照目录（可选）
  -> 解析日志/堆栈，选择 primary anomaly
  -> 加载并校验 manifest / 四类快照
  -> LLM 基于日志与 artifact 摘要提出多个候选原因
  -> 按需调用代码流工具 + JVM 只读工具
  -> 快照事实（symptom）+ 代码机制（mechanism）互相印证
  -> LLM 评估证据，确定性 evaluator 判定状态
  -> 输出问题原因 + 结构化修复建议 + 快照限制
  -> 每条结论/建议可追溯到日志、代码、工具或 artifact 行号
```

| 流程步骤 | v0.4 实现 | 约束 |
|---|---|---|
| 输入异常日志 | CLI `--log`；沿用 v0.3 的 primary 选择 | 仍只处理用户提供的日志文件 |
| 输入 JVM 快照 | CLI `--artifacts DIR` + `manifest.json` | 只读本地文本；不运行 jstack/jcmd/jmap/top |
| 解析快照 | T2 四个纯文本解析器 | 支持 JDK 8/11/17 常见格式；逐行容错；未知行只告警 |
| 分析原因 | T3 JVM 工具 + 既有代码流工具 | 工具条件注册；调用绑定 hypothesis/requirement；输出 ≤32 KiB |
| 判定状态 | T4 symptom/mechanism 覆盖 + v0.3 鉴别规则 | 替代假设排除、refute、工具证据、discriminating requirement 不放松 |
| 同线程上下文 | 有 artifacts 时可选；无 artifacts 时保持 v0.3 强制 | 规则确定性、可解释；仅因存在快照而放松 |
| 报告 | T5 schema 0.4 + artifacts[] + artifact 引用校验 | 不出现绝对路径、完整 dump 或秘密 |
| 评测 | T6 两个 case + 负向/安全/防过拟合 | 默认 pytest 离线、确定性 |
| live | T7 opt-in | 两 case Top-1 目标 2/2，至少 1/2；如实记录 |

### In scope

- Artifact manifest 输入契约、路径/大小/编码/类型安全校验、脱敏。
- jstack、`top -H`/`ps -L`、GC 日志、`jmap -histo` 文本解析。
- 六个只读 JVM 查询工具与确定性证据映射。
- 新 evidence kind/provenance、symptom/mechanism 覆盖、artifact 引用。
- 同线程上下文规则在 JVM 快照场景下的确定性放宽。
- 报告 schema 0.4、CLI `--artifacts`、artifact 元数据与限制。
- 两个 JVM case、离线 pytest 评测、opt-in live 验证。
- 文档、版本 `0.4.0`、发布检查。

### Out of scope

- MCP、SSH、真实 MySQL/PostgreSQL/Redis、远程连接、任意命令/任意 SQL。
- 运行 `jstack`/`jcmd`/`jmap`/`top`、attach 到 JVM、实时采集、持续监听。
- `.hprof`、JFR、async-profiler、堆支配树、分配采样、Native 内存分析。
- MyBatis XML、N+1、慢 SQL、Redis、DB 锁/死锁、Spring 事务/AOP、HikariCP、`@Async`/MDC。
- 自动修复、补丁生成/应用、catalog/skill 库。
- 无日志输入的“纯 JVM 指标”诊断；v0.4 仍要求一个主异常/告警日志文件。
- 生产环境验证或生产准确率声明。

## 2. 核心不变量

1. **证据唯一来源**：证据只能由日志解析器、索引器、artifact 解析器或 ToolExecutor 产生；LLM 不能创建、修改或伪造证据。
2. **快照不是实时**：所有 JVM 证据 provenance 为 `user_artifact`，artifact 标记 `source_environment=user_provided`；不得声称 live attach。
3. **快照不足不能确认**：只有 JVM symptom、没有代码/SQL/配置 mechanism 时最多 `supported`，不能 `confirmed`。
4. **替代假设仍须排除**：v0.3 的多假设、refute、discriminating requirement、工具证据规则全部保留。
5. **引用可定位**：JVM 证据 `source_ref` 必须是 `artifact://<id>#Lx-Ly`，行号范围必须真实存在。
6. **只读有界**：不执行系统命令、不访问网络；文件、行数、线程、帧、事件、类、输出全部有上限。
7. **秘密不外泄**：manifest、artifact 摘录、证据、报告、事件、审计、日志均不得包含 Key/Token/密码。
8. **条件放宽可回归**：无 JVM artifacts 时，v0.3 同线程上下文强制规则与全部旧 case 行为不变。
9. **不按 case 特判**：case 名称、仓库/类/文件名、期望答案不得进入 runtime/prompt。

## 3. 架构摘要

```text
--log + --repo + --artifacts DIR
  -> LogParser / JavaIndex 初始证据
  -> ArtifactLoader 校验 manifest、路径、大小、编码
  -> ArtifactBundle（按需解析、有界行窗口）
  -> LLM 提出 grounded hypotheses
  -> ToolExecutor 执行代码/JVM 只读工具（绑定 hypothesis/requirement）
  -> ArtifactParser -> JVM 结构化证据（artifact:// 行号）
  -> 确定性 evaluator：symptom + mechanism + 替代假设/refute
  -> LLM remediation -> 报告 schema 0.4
```

跨任务协议、数据模型、覆盖规则、报告契约见 [DESIGN.md](./DESIGN.md)。

## 4. 任务索引

| ID | 任务 | 依赖 | 状态 | Spec | Task |
|---|---|---|---|---|---|
| T1 | Artifact 输入契约 | — | implemented | [spec](./T1-artifact-input/spec.md) | [task](./T1-artifact-input/task.md) |
| T2 | JVM 文本解析器 | T1 | implemented | [spec](./T2-jvm-parsers/spec.md) | [task](./T2-jvm-parsers/task.md) |
| T3 | JVM 工具与证据映射 | T1、T2 | implemented | [spec](./T3-jvm-tools/spec.md) | [task](./T3-jvm-tools/task.md) |
| T4 | 覆盖模型与运行时 | T3 | implemented | [spec](./T4-coverage-runtime/spec.md) | [task](./T4-coverage-runtime/task.md) |
| T5 | 报告 0.4 与 CLI | T1、T4 | implemented | [spec](./T5-report-cli/spec.md) | [task](./T5-report-cli/task.md) |
| T6 | 两个 JVM case 与离线评测 | T2–T5 | implemented | [spec](./T6-jvm-cases/spec.md) | [task](./T6-jvm-cases/task.md) |
| T7 | Live、文档与发布 | T6 | implemented | [spec](./T7-live-docs-release/spec.md) | [task](./T7-live-docs-release/task.md) |

**执行顺序**：

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7
```

T5 的部分工作可在 T1 后开始，但 artifact 报告契约以 T4 的证据模型为准；T6 依赖报告 0.4 完成。

## 5. 共享决策

### 5.1 输入方式

- 一个目录 + 固定 `manifest.json`；不做命令行逐文件参数，避免路径/类型歧义。
- manifest 严格 JSON、UTF-8、≤64 KiB，未知字段拒绝。
- `service` 必须与 CLI `--service` 一致；不一致退出 2，避免拿错进程快照。
- artifact 路径相对 manifest，拒绝绝对路径、`..`、symlink、非普通文件。
- 每种 kind 的大小/行数上限见 [DESIGN §3](./DESIGN.md)；总原始字节 ≤32 MiB，artifact 数 ≤8。
- 读取/编码/校验失败退出 2，且不创建 run 目录。

### 5.2 证据模型

- 新增 `EvidenceProvenance.USER_ARTIFACT`。
- 新增 `EvidenceKind`：`THREAD_DUMP`、`THREAD_CPU`、`GC_EVENT`、`GC_SUMMARY`、`HEAP_SUMMARY`。
- `source_ref = artifact://<artifact_id>#L<start>-L<end>`；聚合摘要引用 `#L1-L<line_count>`。
- `content` 只放结构化摘要（线程/状态/帧、GC 类型/停顿/heap、类/实例/字节），不塞完整文件。
- 继续使用 ledger 的 `(kind, source_ref)` 去重和现有 binding/reuse 逻辑。

### 5.3 覆盖与确认

- `SYMPTOM_KINDS`：`LOG_EVENT`、`LOG_THREAD_CONTEXT`、`STACK_FRAME`、`THREAD_DUMP`、`THREAD_CPU`、`GC_EVENT`、`GC_SUMMARY`、`HEAP_SUMMARY`、`DB_ROW`。
- `MECHANISM_KINDS`：`SOURCE_CODE`、`CALL_PATH`、`SQL`、`ANNOTATION`、`CONFIG`、`DB_SCHEMA`。
- 确认仍需：basis、全部 requirement、≥1 discriminating requirement、无 refute、≥1 工具证据、≥1 symptom、≥1 mechanism、替代假设全部 contradicted。
- 只有 JVM symptom 时最多 `supported`；报告增加限制。
- 有 artifacts 时同线程上下文可选；无 artifacts 时保持 v0.3 强制规则。

### 5.4 工具与安全

- JVM 工具只在对应 artifact 存在时注册；无 artifacts 时完全不出现。
- 所有工具同步、只读、参数受限、输出 ≤32 KiB、经过 ToolExecutor 审计和绑定校验。
- 不实现任意文件读取工具；不能通过参数选择 manifest 之外的路径。
- 不执行 subprocess/socket/JVM attach；静态测试扫描禁止符号。

### 5.5 报告与版本

- 报告 schema 直接升到 `0.4`，不提供 `0.3` shim。
- 新增 `artifacts[]`、artifact source 类别、`artifact://` 引用校验。
- 自动 limitations：用户提供时间点快照、未解析 hprof/JFR、结论受快照限制。
- 退出码保持 0/1/2/3/4。
- 版本 `0.4.0`；pyproject/`__init__`/lock 一致。

### 5.6 评测与 live

- 只做 pytest，不新增 eval CLI。
- 两个 case 使用 MockProvider 脚本做确定性集成测试。
- 负向覆盖：快照不足、GC 正常、路径穿越、symlink、service 不匹配、prompt injection、无 exec/remote。
- live 必须三条件同时满足；初始预算 18 iterations / 20 LLM calls / 28 tool calls / 2200 output tokens。
- live 验收：结构 2/2；Top-1 ≥1/2（目标 2/2）、Top-3 2/2；不得伪造 confirmed；未满足记 FAIL/BLOCKED。

## 6. 验收

详细矩阵见 [ACCEPTANCE.md](./ACCEPTANCE.md)（实现后按实际结果回填，不预填 PASS）。

v0.4 完成时至少满足（实际结果已回填到 [ACCEPTANCE.md](./ACCEPTANCE.md)）：

- T1–T7 的 AC 全部有结果，未达标如实记录。
- 两个 case 离线报告 schema 0.4，Top-1 2/2，artifact 引用 100% 有效。
- 只有快照/无 mechanism 的负向场景不得 confirmed。
- 路径穿越、symlink、service 不匹配、超大文件全部被拒绝且不产生 run 目录。
- 无 artifacts 时 v0.3 三 case 全量回归通过。
- `ruff check .`、`mypy src` 通过；默认 pytest 离线。
- live 状态如实回填；无 Key 时为 BLOCKED。

实际发布验证：

- 默认离线测试：**571 passed, 9 skipped**；ruff/mypy 通过。
- v0.4 离线两 case：Top-1 2/2、artifact 引用/标注/接地 100%。
- v0.4 live DeepSeek：**2/2 confirmed**，Top-1 2/2、Top-3 2/2；live CLI 冒烟退出码 0。
- live 调试中 CPU case 出现过 `insufficient_data`，按通用 JVM 提示修正后通过；未按 case 特判，记录见 [T7 task §6](./T7-live-docs-release/task.md)。

## 7. 文档约定

- 每个任务包含 `spec.md`（Context、In/Out scope、FR、契约、AC、测试计划、风险、验证命令、变更记录）和 `task.md`（实施顺序、交付物、DoD、验证命令、风险、验证结果）。
- 未实现项状态写 `planned`；测试和结果未执行时写 `PLANNED`，不得预填 PASS。
- 不修改 `docs/TraceMind_Agent_System_Design*.md`、`specs/001-minimal-loop/**`、`specs/002-live-deepseek/**`。
- 跨任务协议以 [DESIGN.md](./DESIGN.md) 为准；若实现与 DESIGN 冲突，先更新 DESIGN 和受影响 spec，再改代码。

## 8. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 v0.4 SDD：只用用户提供的 JVM 文本快照、artifact 契约、JVM 工具与证据、symptom/mechanism 覆盖、两个 case、T1–T7 |
| 2026-10-23 | T1 artifact 输入、T2 四类 JVM 文本解析器实现并回填；专项 30 测试、全量 459 通过 |
| 2026-10-23 | T3 六个只读 JVM 工具、条件注册与证据映射实现并回填；专项 20 测试、全量 479 通过 |
| 2026-10-23 | T4 symptom/mechanism 覆盖、artifacts 注入、同线程规则与 prompt/cause chain 实现并回填；专项 19 测试、全量 498 通过 |
| 2026-10-23 | T5 报告/run_meta 0.4、artifacts[]/category、artifact 引用校验、JVM limitations、Markdown/CLI 摘要实现并回填；专项 23 测试、全量 521 通过 |
| 2026-10-23 | T6 CPU/OOM 两 case、mock/expected、离线/负向/安全/overfit 评测实现并回填；T6 专项 69 测试、v0.3 eval 29 回归、全量 570 通过 |
| 2026-10-23 | T7 opt-in live 两 case、live CPU CLI 冒烟、README/specs 回填、0.4.0 版本与发布检查；live 2/2 confirmed、Top-1/Top-3 2/2、全量 571 passed/9 skipped |
