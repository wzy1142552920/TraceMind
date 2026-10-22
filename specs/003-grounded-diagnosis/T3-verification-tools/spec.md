# T3 — 只读验证工具契约 Spec

- **任务 ID**：T3
- **状态**：planned
- **依赖**：T1
- **下游**：T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.2 只有本地日志/源码工具，无法验证“数据状态”类假设。v0.3 需要让 Agent 能通过只读工具查证：订单行是否存在、状态是否已经是目标值、SQL 条件是否导致 0 行。但 v0.3 不接真实数据库，必须先定义一个可替换的只读验证契约，并用 Fake backend 跑通。

**用户故事**：作为诊断 Agent，我能看到允许查询的表结构，按主键读取一行数据；我能确定这次验证来自 fixture 而不是生产库；所有查询只读、参数受限、有审计。

## 2. In scope

- `ReadOnlyVerificationBackend` 协议。
- `FakeVerificationBackend`：从 JSON 文件加载合成表/行。
- 工具：
  - `db.describe_table`
  - `db.get_row`
- CLI 参数 `--verification-data PATH`。
- 验证数据 schema、加载校验、表/列白名单、主键查询、单行返回、敏感列脱敏。
- 工具输出的 `source_ref`、`environment=fixture`、`provenance=fake_verification`。
- 错误码/审计/输出截断。
- 工具继承 T1 `EvidenceToolMeta`；绑定元数据可用。

## 3. Out of scope

- 真实 MySQL/PostgreSQL/Redis 连接、DSN、凭据、连接池。
- MCP/SSH/远程执行。
- 任意 SQL、WHERE 表达式、JOIN、聚合、多行查询、写操作、DDL/DML。
- 复合主键、外键关系、schema introspection 之外的数据库元数据。
- 敏感数据真实样本；v0.3 只用合成数据。
- 报告中的 fixture 标注（T5）。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T3-01 | 定义 ReadOnlyVerificationBackend 协议和结果模型 | must |
| FR-T3-02 | Fake backend 从 JSON 加载表/列/主键/行 | must |
| FR-T3-03 | 数据文件 schema/大小/标识符校验，错误明确 | must |
| FR-T3-04 | 只注册 `describe_table`/`get_row`，不支持任意 SQL/写 | must |
| FR-T3-05 | 表/列白名单；未知表/列返回 TARGET_DENIED | must |
| FR-T3-06 | 按主键单行查询；found/not_found 都是结构化结果 | must |
| FR-T3-07 | 敏感列值脱敏，结果标记 redacted_columns | must |
| FR-T3-08 | 结果带 `source_ref=db://table/key=value` 和 environment=fixture | must |
| FR-T3-09 | 没有 backend 时 DB 工具不注册 | must |
| FR-T3-10 | `--verification-data` 非法/不存在时在解析/索引前退出 2 | must |
| FR-T3-11 | 所有 DB 调用经过 ToolExecutor 审计，输出受限 | must |
| FR-T3-12 | 工具描述明确只读/fixture/非生产 | must |

## 5. 接口/数据契约

### 5.1 Backend 协议

```python
class TableDescription(BaseModel):
    table: str
    columns: list[str]
    primary_key: str
    row_count: int
    sensitive_columns: list[str] = []

class VerificationRowResult(BaseModel):
    found: bool
    table: str
    key_column: str
    key_value: str | int
    columns: list[str]
    row: dict[str, Any] | None = None
    redacted_columns: list[str] = []
    environment: Literal["fixture"] = "fixture"
    source_ref: str | None = None

class ReadOnlyVerificationBackend(Protocol):
    @property
    def environment(self) -> str: ...
    def describe_table(self, table: str) -> TableDescription: ...
    def get_row(
        self,
        table: str,
        key_value: str | int,
        columns: list[str] | None = None,
    ) -> VerificationRowResult: ...
```

- v0.3 只允许 `environment="fixture"`。
- 真实 backend 后续必须实现同一协议；报告层通过 environment/provenance 区分。
- `source_ref` 由 backend/tool 生成：`db://<table>/<primary_key>=<key_value>`。

### 5.2 验证数据文件

```json
{
  "backend": "fake",
  "tables": {
    "orders": {
      "primary_key": "id",
      "columns": ["id", "status", "updated_at"],
      "sensitive_columns": [],
      "rows": [
        {"id": 10086, "status": "PAID", "updated_at": "2026-10-18T10:20:00Z"}
      ]
    }
  }
}
```

校验规则：

1. 顶层 `backend` 必须为 `"fake"`；`tables` 非空对象。
2. 表名/列名匹配 `[A-Za-z_][A-Za-z0-9_]*`；最多 10 张表、每表 30 列、1000 行。
3. `columns` 非空、无重复；`primary_key` 必须在 columns 中且非空。
4. 每行必须包含 primary key；只允许标量值（str/int/float/bool/null）；不允许嵌套对象/数组。
5. `sensitive_columns` 必须是 columns 子集。
6. 文件 ≤ 1 MiB；JSON 解析失败/结构错误 → `VerificationDataError`。
7. 不保存/打印凭据；v0.3 数据文件不包含连接信息。

### 5.3 工具契约

#### `db.describe_table`

输入：`table: str`。

输出：

```json
{
  "table": "orders",
  "columns": ["id", "status", "updated_at"],
  "primary_key": "id",
  "row_count": 1,
  "sensitive_columns": [],
  "environment": "fixture",
  "source_ref": "db://orders#schema"
}
```

- 未知表 → `TARGET_DENIED`。
- 输出受 `max_output_bytes` 限制。

#### `db.get_row`

输入：

```json
{
  "table": "orders",
  "key_value": 10086,
  "columns": ["id", "status"],
  "hypothesis_id": "hyp_001",
  "requirement_id": "hyp_001_req_01"
}
```

- `key_value` 只接受 str/int；`columns` 可省略，默认全部列；必须是白名单子集。
- 主键比较使用规范字符串形式（`10086` 与 `"10086"` 等价），避免 JSON 数字/字符串类型差异。
- 结果 found：

```json
{
  "found": true,
  "table": "orders",
  "key_column": "id",
  "key_value": 10086,
  "columns": ["id", "status", "updated_at"],
  "row": {"id": 10086, "status": "PAID", "updated_at": "..."},
  "redacted_columns": [],
  "environment": "fixture",
  "source_ref": "db://orders/id=10086"
}
```

- 结果 not_found：

```json
{
  "found": false,
  "table": "orders",
  "key_column": "id",
  "key_value": 10086,
  "columns": ["id", "status", "updated_at"],
  "row": null,
  "redacted_columns": [],
  "environment": "fixture",
  "source_ref": "db://orders/id=10086"
}
```

- 敏感列值替换为 `"***"`，并在 `redacted_columns` 列出。
- 不存在多行/任意过滤/排序/聚合能力。
- 工具描述必须包含：只读、fixture、主键单行、非生产数据。

### 5.4 CLI

```bash
uv run tracemind diagnose \
  --log fixtures/logs/v03-c1-missing-row/incident.log \
  --repo fixtures/repos/minimal-order-service-fixed \
  --verification-data fixtures/verification/v03-c1-missing-row.json \
  --provider mock \
  --mock-script fixtures/mock/v03-c1-missing-row.json
```

- `--verification-data` 不存在/不可读 → Typer 退出 2。
- JSON/schema 校验失败 → 明确错误，退出 2，在日志解析/索引/建目录之前。
- 不提供该参数时 DB 工具不注册，不出现于工具目录。
- 运行产物记录 `verification: {environment, backend, tables}`，不含敏感值。

### 5.5 错误与审计

| 情况 | 错误码 |
|---|---|
| 未知表/列 | `TARGET_DENIED` |
| key_value 类型非法 | `INVALID_ARGUMENTS` |
| backend 不可用 | `TOOL_ERROR` |
| 输出超限 | `OUTPUT_LIMIT`（截断） |

- 所有调用记录 tool_call_id、参数 hash、绑定、耗时、结果/错误。
- 不允许通过参数注入 SQL/表名/列名；只接受标识符白名单。
- 不记录完整行到普通日志；证据 content 按 T1 截断/脱敏。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T3-01 | 合法数据文件加载，describe/get_row 可用 | `tests/unit/test_fake_verification.py` |
| AC-T3-02 | 非法 JSON/schema/标识符/大文件被拒绝 | 同上 |
| AC-T3-03 | 未知表/列返回 TARGET_DENIED | `test_db_tools.py` |
| AC-T3-04 | 主键命中/未命中都返回结构化结果和 source_ref | 同上 |
| AC-T3-05 | columns 子集与敏感列脱敏正确 | 同上 |
| AC-T3-06 | 无 backend 时 DB 工具不注册 | registry/CLI 测试 |
| AC-T3-07 | `--verification-data` 非法时退出 2 且无 run 目录 | CLI E2E |
| AC-T3-08 | 所有 DB 调用有审计、只读、无任意 SQL 入口 | executor/audit 测试 |
| AC-T3-09 | 结果 environment=fixture，工具描述含非生产提示 | 工具/CLI 测试 |
| AC-T3-10 | 输出截断/超限标记 | tool executor 测试 |
| AC-T3-11 | 绑定元数据可传入且不破坏参数校验 | `test_tool_binding.py` |
| AC-T3-12 | 验证数据/证据不含秘密 | secret scan / 代码审查 |

## 7. 测试计划

### 单元

- `tests/unit/test_fake_verification.py`
  - 加载合法文件；三 case 数据样例。
  - 非法 JSON、backend 非 fake、空表、无 PK、PK 不在 columns、重复列、非法标识符、嵌套值、超大文件。
- `tests/unit/test_db_tools.py`
  - describe_table、get_row found/not_found。
  - 未知表/列、非法 key 类型、columns 子集、敏感列脱敏。
  - source_ref/environment。
  - 无 backend 时 registry 不包含 db.*。
- `tests/unit/test_tool_executor.py` 扩展
  - 输出截断、审计、绑定元数据。
- `tests/e2e/test_cli_verification.py`
  - `--verification-data` 缺失/非法 → exit 2；无 run 目录。
  - 合法 → Mock 运行可调用 db 工具。

### 集成

- 用 `minimal-order-service-fixed` + 三份验证数据，验证 C1/C2 的 found/not_found/PAID 状态可通过工具区分。
- 不接真实数据库。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| Fake 与真实 DB 行为差异 | fixture 不覆盖隔离级别/锁/字符集 | 明确 fixture 边界；真实 backend 后续另立 spec |
| 验证数据泄露 | 示例数据可能含敏感值 | 只用合成数据；敏感列脱敏；不记录完整行 |
| 任意查询能力膨胀 | 后续想加 WHERE/JOIN | v0.3 固定主键查询；扩展需新契约 |
| 工具不存在时的体验 | LLM 可能调用不存在的 db 工具 | 工具目录只列已注册工具；repair 处理 unknown tool |
| 复合主键 | 真实业务常见 | v0.3 明确 out of scope；数据校验拒绝 |
| source_ref 伪造 | LLM 不能创建证据，但工具结果需可信 | source_ref 由 backend/tool 生成；报告校验证据存在 |

**开放问题**

- 是否允许按非主键列查询？v0.3 不允许；避免任意过滤和歧义。
- 是否返回多行？v0.3 不允许；后续 `db.count`/受限查询另立契约。
- 真实 backend 的连接/凭据/审批何时引入？不在 v0.3；需单独设计。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_fake_verification.py tests/unit/test_db_tools.py tests/e2e/test_cli_verification.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 10. 实现验证结果

| 日期 | 命令/检查 | 结果 |
|---|---|---|
| — | 待实现后回填 | PLANNED |

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-22 | 创建 T3 spec：只读验证协议、Fake backend、db.describe_table/db.get_row、白名单与 fixture 标注 |
