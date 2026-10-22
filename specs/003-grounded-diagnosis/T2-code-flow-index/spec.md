# T2 — 代码流索引与工具 Spec

- **任务 ID**：T2
- **状态**：planned
- **依赖**：T1
- **下游**：T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.2 的 `TreeSitterJavaIndex` 只索引类/方法/FQN/行号，工具只有 `code.find_symbol` 和 `code.get_source_range`。LLM 无法从 Controller 追到 Service、Mapper 和注解 SQL，也无法区分同名重载方法，因此无法形成“业务代码流程”层面的假设。

T2 增加最小可用的静态代码流能力：注解、注入字段、方法调用点、注解 SQL，以及对应的只读工具。所有调用边都是 AST 启发式候选，必须标注 provenance/confidence，不冒充运行时调用图。

**用户故事**：作为诊断 Agent，我能从异常栈定位到 Service 方法，再查它的调用者和被调用者，找到 Mapper 方法及其 SQL；我也能把同线程日志上下文里的 `logger` 类名（取其简单类名）和栈帧落到代码符号；这些结果都带文件、行号、置信度和来源，可作为真实代码证据。

## 2. In scope

- 扩展 Java 索引数据结构：
  - `JavaSymbol`：annotations、parameter_count、return_type、modifiers。
  - `JavaField`：owner、name、type、annotations、行号。
  - `MethodCall`：调用者、receiver、方法名、参数个数、行号。
  - `SqlArtifact`：SQL 文本、语句类型、表名、源码位置。
- tree-sitter 提取：
  - 类/方法/字段注解及简单字面量参数。
  - 方法体内的 method_invocation。
  - 注解 SQL：`@Select`、`@Insert`、`@Update`、`@Delete`。
- 调用候选解析：
  - `this.method(...)` / 同类隐式调用。
  - 字段 receiver → 注入字段类型 → 类方法。
  - import/static import / 类名限定。
  - 同名同参数个数的全仓库候选（低置信度）。
- 新工具：
  - `code.get_symbol`
  - `code.get_callers`
  - `code.get_callees`
  - `code.find_sql`
- 增强 `code.find_symbol` 输出：symbol_id、annotations、parameter_count、signature。
- 支持从日志 `logger` 的简单类名（如 `c.e.order.OrderService` → `OrderService`）和栈帧定位代码符号；不新增日志解析逻辑。
- 所有工具继承 T1 的 `EvidenceToolMeta`，返回结构化 source_ref/line/confidence，供 T4 映射为证据。

## 3. Out of scope

- MyBatis XML mapper、`@SelectProvider`/动态 SQL。
- JDT/JavaParser sidecar、完整类型推导、跨模块 classpath。
- 运行时调用图、Spring AOP/CGLIB 实际代理、反射/动态分派。
- Lombok 生成的方法/字段。
- `code.get_call_path` 多跳路径工具（LLM 可用 callers/callees 自行遍历）。
- 配置 key 索引（`config` evidence kind 预留，T2 不实现）。
- 修改日志解析、运行时、报告。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T2-01 | 索引类/方法/字段注解，保留简单字面量参数 | must |
| FR-T2-02 | 索引方法体内调用点，记录 receiver/方法名/参数个数/行号 | must |
| FR-T2-03 | 解析 `this`/同类、字段注入、import、同名同参数个数候选边，带 confidence | must |
| FR-T2-04 | 提取注解 SQL、语句类型和表名 | must |
| FR-T2-05 | 新增 `code.get_symbol`，按 symbol_id 返回完整符号信息 | must |
| FR-T2-06 | 新增 `code.get_callers` / `code.get_callees`，返回候选边 | must |
| FR-T2-07 | 新增 `code.find_sql`，按 SQL/表名/符号搜索 | must |
| FR-T2-08 | 增强 `code.find_symbol` 输出 annotations/parameter_count | must |
| FR-T2-09 | 重载方法按名称+参数个数消歧，保留多候选 | must |
| FR-T2-10 | 所有结果带 file_path/line/source_ref/confidence/provenance | must |
| FR-T2-11 | 未知 symbol_id/超限参数返回稳定错误 | must |
| FR-T2-12 | 不把候选边描述为运行时调用图；报告/工具描述明确限制 | must |
| FR-T2-13 | 日志 `logger` 简单类名/栈帧可解析到类或方法，作为日志→代码的落点 | must |

## 5. 接口/数据契约

### 5.1 扩展符号模型

```python
class AnnotationInfo(BaseModel):
    name: str                 # 不含 "@"
    arguments: dict[str, str] = {}
    line: int

class JavaSymbol(BaseModel):
    symbol_id: str
    fqn: str
    class_name: str
    method_name: str | None
    symbol_type: str          # class/interface/enum/record/annotation/method/constructor
    file_path: str
    start_line: int
    end_line: int
    signature: str | None
    provenance: str
    annotations: list[AnnotationInfo] = []
    parameter_count: int | None = None
    return_type: str | None = None
    modifiers: list[str] = []
```

- 字段不进入 `JavaSymbol` 列表；用独立 `JavaField` 支持注入解析：

```python
class JavaField(BaseModel):
    owner_fqn: str
    name: str
    type_name: str
    annotations: list[AnnotationInfo] = []
    start_line: int
```

### 5.2 调用与 SQL 模型

```python
class MethodCall(BaseModel):
    caller_symbol_id: str
    receiver: str | None      # "this" / "orderMapper" / "OrderService" / None
    method_name: str
    argument_count: int
    line: int

class CallEdge(BaseModel):
    caller_symbol_id: str
    caller_fqn: str
    callee_symbol_id: str
    callee_fqn: str
    file_path: str
    line: int
    receiver: str | None
    confidence: float
    provenance: str = "ast_heuristic"

class SqlArtifact(BaseModel):
    symbol_id: str
    file_path: str
    start_line: int
    end_line: int
    sql_text: str
    statement_type: str      # SELECT/INSERT/UPDATE/DELETE
    tables: list[str] = []
    provenance: str = "annotation_sql"
```

### 5.3 调用解析规则

优先级从高到低：

| 场景 | 解析 | 置信度 |
|---|---|---|
| `this.m(...)` 或同类隐式 `m(...)` | 当前类同名同参数个数方法 | 0.90 |
| `field.m(...)`，field 类型指向仓库内类 | 字段类型类同名同参数个数方法 | 0.75 |
| `ClassName.m(...)` / static import | 对应类同名方法 | 0.65 |
| 仅方法名+参数个数 | 全仓库候选 | 0.40 |

- 返回所有候选，不强行唯一。
- 重载方法参数个数不同 → 过滤；参数个数相同 → 保留多候选并降低置信度。
- 链式调用/嵌套调用只取最外层可解析 receiver；无法解析则 `receiver=None`，走低置信度候选。
- 方法引用（`::`）、lambda、反射不索引。

### 5.4 注解 SQL 提取

支持：

```java
@Select("SELECT status FROM orders WHERE id = #{orderId}")
@Insert("INSERT INTO ...")
@Update("UPDATE orders SET status = #{status} WHERE id = #{orderId} AND status <> #{status}")
@Delete("DELETE FROM ...")
```

- 取注解简单字符串参数（含数组第一个元素）。
- `statement_type` 由注解名决定。
- 表名用保守正则从 `FROM`/`INTO`/`UPDATE`/`DELETE FROM` 提取；不解析动态 SQL。
- `sql_text` 保留 `#{}`/`${}` 占位符，不做参数替换。
- `@SelectProvider`/`@UpdateProvider` 等不支持，记录 `parse_warnings`，不创建 SqlArtifact。

### 5.5 工具契约

#### `code.find_symbol`（增强）

输入：`query: str`（1..200），`limit: 1..20`（默认 10）。

- 查询词可来自日志 `logger` 的简单类名（如 `OrderService`）、方法名或栈帧类名；工具只做索引匹配，不自行推断日志与代码的语义关系。

输出：

```json
{
  "items": [
    {
      "symbol_id": "sym_0002",
      "fqn": "com.example.order.OrderService",
      "class_name": "OrderService",
      "method_name": "updateStatus",
      "signature": "public int updateStatus(Long orderId, String status)",
      "file_path": "src/main/java/com/example/order/OrderService.java",
      "start_line": 17,
      "end_line": 27,
      "annotations": [],
      "parameter_count": 2,
      "provenance": "tree_sitter"
    }
  ],
  "count": 1
}
```

#### `code.get_symbol`

输入：`symbol_id: str`。

输出：单个符号完整信息 + `calls` 摘要（不展开源码，源码由 `code.get_source_range` 读取）；未知 ID → `TARGET_DENIED`。

#### `code.get_callers`

输入：`symbol_id: str`，`limit: 1..20`（默认 10）。

输出：

```json
{
  "items": [
    {
      "caller_symbol_id": "sym_0003",
      "caller_fqn": "com.example.order.OrderService",
      "callee_symbol_id": "sym_0002",
      "callee_fqn": "com.example.order.OrderService",
      "file_path": "src/main/java/com/example/order/OrderService.java",
      "line": 14,
      "receiver": "this",
      "confidence": 0.9,
      "source_ref": "repo://src/main/java/com/example/order/OrderService.java#L14"
    }
  ],
  "count": 1,
  "provenance": "ast_heuristic"
}
```

#### `code.get_callees`

输入/输出同上，方向相反。

#### `code.find_sql`

输入：`query: str`（1..200），`limit: 1..20`（默认 10）。匹配 SQL 文本、表名、符号名。

输出：

```json
{
  "items": [
    {
      "symbol_id": "sym_0009",
      "fqn": "com.example.order.OrderMapper",
      "statement_type": "UPDATE",
      "sql_text": "UPDATE orders SET status = #{status} WHERE id = #{orderId} AND status <> #{status}",
      "tables": ["orders"],
      "file_path": "src/main/java/com/example/order/OrderMapper.java",
      "start_line": 16,
      "end_line": 16,
      "source_ref": "repo://src/main/java/com/example/order/OrderMapper.java#L16",
      "provenance": "annotation_sql"
    }
  ],
  "count": 1
}
```

- 所有工具结果受 `max_output_bytes` 截断；截断必须标记。
- 工具描述必须写明“候选调用边，不是运行时调用图”。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T2-01 | Controller/Service/Mapper 的类/方法注解被索引 | `tests/unit/test_java_index.py` 扩展 |
| AC-T2-02 | `handlePaid` → `updateStatus` 自调用边可查 | `test_code_flow.py` |
| AC-T2-03 | Controller → Service 调用边可查 | 同上 |
| AC-T2-04 | 重载 `updateStatus` 按参数个数过滤，保留候选 | 同上 |
| AC-T2-05 | `@Update` SQL/表名被提取 | 同上 |
| AC-T2-06 | `code.get_symbol` 返回注解/参数数/签名 | `test_code_flow_tools.py` |
| AC-T2-07 | 未知 symbol_id 返回 TARGET_DENIED | 同上 |
| AC-T2-08 | callers/callees 返回 confidence/provenance/source_ref | 同上 |
| AC-T2-09 | find_sql 可按表名/SQL 片段/符号搜索 | 同上 |
| AC-T2-10 | 工具描述/结果明确标注候选调用边 | 代码审查 + 测试断言 |
| AC-T2-11 | 现有 find_symbol/get_source_range 行为兼容 | 全量旧测试 |
| AC-T2-12 | 元数据参数可被 executor 识别，handler 不报错 | `test_tool_binding.py` |
| AC-T2-13 | 日志 `logger` 简单类名/栈帧可解析到类或方法 | `test_code_flow_tools.py` |

## 7. 测试计划

### 单元

- `tests/unit/test_java_index.py` 扩展：
  - `@RestController/@Service/@Mapper/@Update` 注解。
  - 字段 `orderService`/`orderMapper` 的类型解析。
  - 方法调用点行号/参数个数。
  - 重载 `updateStatus` 的 arity。
  - 注解 SQL 语句类型/表名/占位符保留。
- 新增 `tests/unit/test_code_flow.py`：
  - `OrderService.handlePaid` → `OrderService.updateStatus`（this）。
  - `OrderController.paid` → `OrderService.handlePaid`（field）。
  - `OrderService.updateStatus` → `OrderMapper.updateStatus`（field）。
  - 候选边不唯一时全部返回。
- 新增 `tests/unit/test_code_flow_tools.py`：
  - get_symbol/callers/callees/find_sql 的参数校验和输出。
  - 未知 symbol、超 limit。
  - 截断标记。
  - 日志 `logger` 简单类名（`OrderService`）与栈帧可定位到类/方法。

### 集成

- 用 `minimal-order-service` fixture 构建索引，跑完整工具序列。
- 不启动真实 LLM/DB。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 调用边误报 | tree-sitter 无类型解析 | 全部标记 ast_heuristic + confidence；报告声明 |
| 重载/同名方法 | 参数个数相同无法唯一 | 返回多候选，LLM 可用源码确认 |
| 链式/嵌套调用 | receiver 解析困难 | 低置信度候选或跳过；不索引 lambda/方法引用 |
| 注解 SQL 动态化 | Provider/XML 不支持 | 明确 out of scope；报告限制 |
| 大仓库性能 | 全仓库调用扫描 | 单仓库内存索引；v0.3 fixture 规模小；后续 FTS/增量 |
| 与 T1 绑定冲突 | meta 字段进入 handler | 公共 base 模型；handler 忽略 meta |

**开放问题**

- 是否索引字段符号本身？v0.3 用 JavaField 内部结构，不进入用户可见 symbol 列表。
- 是否支持多模块/多仓库消歧？v0.3 单仓库；调用边带文件路径。
- 是否需要 `code.get_call_path`？v0.3 不提供，LLM 用 callers/callees 遍历。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_java_index.py tests/unit/test_code_flow.py tests/unit/test_code_flow_tools.py tests/unit/test_tool_binding.py -q
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
| 2026-10-22 | 创建 T2 spec：注解/调用点/注解 SQL、候选边、代码流工具 |
| 2026-10-22 | 增加日志 logger 简单类名/栈帧到代码符号的落点要求（AC-T2-13） |
