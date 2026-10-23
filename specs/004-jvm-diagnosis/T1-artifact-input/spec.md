# T1 — Artifact 输入契约 Spec

- **任务 ID**：T1
- **状态**：implemented
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.4 设计**：[DESIGN §3](../DESIGN.md)
- **v0.4 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.3 只接受日志文件与仓库，没有承载 JVM 运行时事实的输入。CPU 高、内存高/OOM 判断需要线程转储、线程 CPU、GC 日志和堆直方图。直接新增多个命令行文件参数会产生类型/路径/配对歧义，也可能让 Agent 读取任意文件。

T1 定义一个受控的 artifact bundle：用户提供一个目录，目录内固定 `manifest.json` 声明快照类型与文件；TraceMind 在运行前做严格的 schema、服务名、路径、symlink、大小、编码校验，并把元数据作为不可变记录交给运行时。T1 不解析具体 JVM 格式，也不注册工具。

**用户故事**：作为用户，我把某次故障时间点的 jstack/top/GC/histo 文本放进一个目录并声明类型；TraceMind 要么完整、安全地接受这个 bundle，要么明确拒绝并且不开始诊断；作为审计者，我能看到用了哪些快照，但看不到绝对路径或秘密。

## 2. In scope

- `src/tracemind/artifacts/models.py`：`ArtifactKind`、`ArtifactSpec`、`ArtifactManifest`、`ArtifactDocument`、`ArtifactRecord`、`ArtifactBundle`、`ArtifactError`。
- `src/tracemind/artifacts/loader.py`：manifest 严格加载、service 匹配、id/kind/path/大小/行数/编码校验、有界文本读取。
- `src/tracemind/artifacts/redaction.py`：文本脱敏与命中类别。
- `src/tracemind/artifacts/__init__.py`：公开接口。
- CLI 新增 `--artifacts PATH`；校验失败退出 2，且不写 run 目录。
- 单元测试与 CLI 错误测试。

## 3. Out of scope

- JVM 文本解析（T2）。
- JVM 工具/证据映射（T3）。
- evaluator/runtime/prompt（T4）。
- 报告 schema 0.4（T5）。
- 运行 `jstack`/`jmap`/`top`、attach、实时采集、`.hprof`/JFR。
- 任意文件读取、glob、通配符、压缩包。
- 从网络/对象存储下载 artifact。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T1-01 | 定义四种 artifact kind 和严格 manifest 模型（`extra="forbid"`） | must |
| FR-T1-02 | manifest 必须存在、≤64 KiB、UTF-8、严格 JSON、schema_version="1" | must |
| FR-T1-03 | service 必填且与 CLI `--service` 完全一致；instance/captured_at 只展示 | must |
| FR-T1-04 | artifacts 1..8 条，id 唯一且匹配 `[a-z][a-z0-9_-]{0,31}` | must |
| FR-T1-05 | path 必须为相对路径，拒绝绝对路径、`..`、`.`、空段、反斜杠、NUL | must |
| FR-T1-06 | 目标必须是普通文件；拒绝 symlink（含路径组件）；真实路径必须在 bundle 根内 | must |
| FR-T1-07 | 按 kind 校验单文件字节/行数上限、总字节 ≤32 MiB、总行数 ≤500,000 | must |
| FR-T1-08 | 严格 UTF-8 读取；空文件/解码失败/不可读拒绝 | must |
| FR-T1-09 | 构建不可变 `ArtifactBundle`，提供 by_kind/document/has_kind/records | must |
| FR-T1-10 | `ArtifactRecord` 只含 basename、kind、行数、字节、truncated、warnings、source_environment=user_provided | must |
| FR-T1-11 | 提供 `redact_text`，覆盖 password/token/secret/authorization/credential 常见赋值 | must |
| FR-T1-12 | CLI `--artifacts` 在 provider/日志/索引/run 目录之前校验；失败退出 2 | must |
| FR-T1-13 | 错误消息只含相对路径/artifact id/原因，不含文件内容或绝对路径 | must |
| FR-T1-14 | 不提供 artifacts 时行为与 v0.3 完全一致 | must |

## 5. 接口/数据契约

```python
class ArtifactKind(StrEnum):
    THREAD_DUMP = "thread_dump"
    THREAD_CPU = "thread_cpu"
    GC_LOG = "gc_log"
    HEAP_HISTOGRAM = "heap_histogram"

class ArtifactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    kind: ArtifactKind
    path: str

class ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1"]
    service: str
    instance: str | None = None
    captured_at: str | None = None
    artifacts: list[ArtifactSpec]

class ArtifactDocument(BaseModel):  # frozen
    spec: ArtifactSpec
    source_name: str
    lines: tuple[str, ...]
    byte_size: int
    line_count: int
    warnings: list[str]

class ArtifactRecord(BaseModel):  # frozen
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

def load_artifacts(root: Path, expected_service: str) -> ArtifactBundle: ...
def redact_text(text: str) -> tuple[str, list[str]]: ...
```

### 5.1 大小/行数上限

| kind | 字节 | 行数 |
|---|---:|---:|
| thread_dump | 10 MiB | 500,000 |
| thread_cpu | 2 MiB | 100,000 |
| gc_log | 20 MiB | 500,000 |
| heap_histogram | 5 MiB | 200,000 |

总字节 ≤32 MiB；所有文件合计行数 ≤500,000；manifest ≤64 KiB。

### 5.2 错误

统一 `ArtifactError(message)`，CLI 转为：

```text
artifacts error: <message>
```

退出码 2。错误信息不得包含文件内容、绝对路径、完整 manifest。

## 6. 验收标准

| ID | 验收标准 |
|---|---|
| AC-T1-01 | 合法四类 manifest 加载成功，bundle 顺序、records、by_kind/document/has_kind 正确 |
| AC-T1-02 | manifest 缺失/非 JSON/数组/未知字段/错误 schema_version 被拒绝 |
| AC-T1-03 | 未知 kind、重复 id、非法 id、空 artifacts、>8 条被拒绝 |
| AC-T1-04 | service 不匹配、空 service 被拒绝；instance/captured_at 可选 |
| AC-T1-05 | 绝对路径、`..`、`.`、空段、反斜杠、NUL 路径被拒绝 |
| AC-T1-06 | symlink 文件、symlink 路径组件、指向根外的真实路径被拒绝 |
| AC-T1-07 | 单文件字节/行数超限、总字节/总行数超限被拒绝 |
| AC-T1-08 | 非 UTF-8、空文件、目录冒充文件、不可读文件被拒绝 |
| AC-T1-09 | 记录不含绝对路径；source_name 为 basename；source_environment=user_provided |
| AC-T1-10 | `redact_text` 对常见 key=value、Bearer、JSON 字符串脱敏并返回类别 |
| AC-T1-11 | CLI 合法 artifacts 可继续诊断；非法 artifacts 退出 2 且不创建 run 目录 |
| AC-T1-12 | 无 `--artifacts` 时 CLI/旧测试行为不变 |

## 7. 测试计划

- `tests/unit/test_artifact_manifest.py`
  - 合法 manifest、四 kind、records。
  - 缺失/坏 JSON/未知字段/版本/空列表/重复 id/非法 id/未知 kind。
  - service 匹配与不匹配。
  - 行数/字节上限（用 monkeypatch 小阈值，避免生成大文件）。
  - 编码/空文件/目录。
- `tests/unit/test_artifact_safety.py`
  - `..`、绝对路径、`.`、空段、反斜杠、NUL。
  - symlink 文件与 symlink 父目录。
  - 指向根外。
  - 记录无绝对路径。
- `tests/unit/test_artifact_redaction.py`
  - `password=...`、`token: ...`、`Authorization: Bearer ...`、JSON。
  - 无命中保持原文。
- `tests/e2e/test_cli_artifacts.py`
  - 合法目录进入 mock 诊断（不需要 JVM 工具，仅确认加载不报错）。
  - 非法 manifest/service 退出 2，输出目录为空/不存在。
  - 未提供 `--artifacts` 的旧路径回归。

## 8. 风险与开放问题

- **路径安全跨平台**：统一用 `PurePosixPath` 解析 manifest 路径（manifest 约定 `/`），再映射到本地文件；拒绝 Windows 分隔符，避免平台差异。
- **行数统计内存**：文件 ≤32 MiB，一次性读入可接受；仍用上限提前判断字节。
- **脱敏误伤**：只替换赋值/头部模式，不把普通单词 `token` 全部替换。
- **红线**：T1 不引入解析/工具逻辑；不得读取 bundle 外文件。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_artifact_manifest.py tests/unit/test_artifact_safety.py tests/unit/test_artifact_redaction.py tests/e2e/test_cli_artifacts.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-23 | 创建 T1 spec：manifest、路径/大小/编码安全、bundle/records、脱敏、CLI `--artifacts` |
