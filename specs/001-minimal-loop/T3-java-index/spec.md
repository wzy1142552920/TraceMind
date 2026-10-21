# T3 — Java 源码索引 Spec

- **任务 ID**：T3
- **状态**：draft
- **依赖**：T1、T2
- **下游**：T4、T6
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **文档索引**：[README](../README.md)

## 1. Context / 用户故事

T2 已经能从堆栈中解析出 `com.example.order.OrderService.updateStatus(OrderService.java:24)`。下一步需要把这个栈帧映射到本地 Java 源码的真实文件、类、方法和行号，并对源码片段做可复核引用。

**用户故事**：作为开发者，我给它一个仓库路径和一个 stack frame，它能返回源码文件、方法范围、行号是否有效，以及可用于报告的 `SourceMatch`。

## 2. In scope

- 单仓库、单个本地目录。
- 使用 `tree-sitter` + `tree-sitter-java` 解析 `.java` 文件。
- 提取 package、class/interface/enum/record、method/constructor、起止行号、方法名、参数/签名（简化）。
- 支持嵌套类、重载方法、构造器、`static` 初始化块的有限识别。
- 按 FQN + method + line、FQN + method、file name + method 依次匹配 stack frame。
- 读取源码行范围，返回带行号的文本。
- 支持 tree-sitter 不可用时的同接口 regex fallback（明确标记 provenance）。
- 提供 `index`、`find_symbol`、`resolve_frame`、`get_source_range` 接口。

## 3. Out of scope

- 多仓库、跨仓库消歧。
- SQLite/FTS5、增量索引、文件监听。
- JDT/JavaParser sidecar、完整类型解析、符号求解。
- Lombok 生成方法、Spring AOP 代理、反射/运行时分派。
- MyBatis XML、Spring 注解语义、调用图。
- 大仓库性能优化。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T3-01 | 递归扫描 repo 下的 `.java` 文件；跳过 `target/`、`build/`、`.git/` | must |
| FR-T3-02 | 提取 package FQN、类/接口/枚举/record 名、方法/构造器名、起止行号 | must |
| FR-T3-03 | 支持嵌套类；FQN 同时兼容 `Outer.Inner` 和 `Outer$Inner` 匹配 | must |
| FR-T3-04 | `resolve_frame` 返回 `SourceMatch` 候选，按 confidence 排序；找不到返回空列表 | must |
| FR-T3-05 | 匹配规则：FQN+method+line 在范围内 > FQN+method > file+method | must |
| FR-T3-06 | `get_source_range` 返回指定行范围，1-based，超出文件范围时裁剪并标记 | must |
| FR-T3-07 | 索引只读；不修改仓库文件 | must |
| FR-T3-08 | tree-sitter 不可用时启用 `RegexJavaIndex` 兜底，结果标记 `provenance="regex_fallback"` | should |
| FR-T3-09 | 索引结果包含相对路径和行号，供 `repo://` 引用 | must |

## 5. 接口/数据契约

### `JavaSymbol`

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol_id` | `str` | `sym_...`，索引内稳定 |
| `fqn` | `str` | 类 FQN，嵌套类用 `Outer$Inner` |
| `class_name` | `str` | 简单类名 |
| `method_name` | `str \| None` | 方法/构造器名；类级符号为空 |
| `symbol_type` | `str` | `class`/`interface`/`enum`/`record`/`method`/`constructor` |
| `file_path` | `str` | 相对 repo 根的路径 |
| `start_line` / `end_line` | `int` | 1-based，包含端点 |
| `signature` | `str \| None` | 简化签名 |
| `provenance` | `str` | `tree_sitter` / `regex_fallback` |

### `SourceMatch`

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | `JavaSymbol` | 命中的符号 |
| `file_path` | `str` | 相对路径 |
| `start_line` / `end_line` | `int` | 命中方法/类范围 |
| `matched_line` | `int \| None` | 栈帧行号（若提供） |
| `confidence` | `float` | 0–1，仅用于排序 |
| `match_reason` | `str` | `fqn_method_line` / `fqn_method` / `file_method` |
| `provenance` | `str` | 继承自 symbol |

### 接口

```python
class JavaIndex(Protocol):
    def index(self, repo_path: Path) -> IndexStats: ...
    def find_symbol(self, query: str, limit: int = 10) -> list[JavaSymbol]: ...
    def resolve_frame(self, frame: StackFrame) -> list[SourceMatch]: ...
    def get_source_range(self, file_path: str, start_line: int, end_line: int) -> SourceSnippet: ...
```

`SourceSnippet` 字段：`file_path`、`start_line`、`end_line`、`text`（带行号或可加行号）、`truncated`。

### 匹配规则

1. FQN 匹配 + method 匹配 + 行号在方法范围内 → confidence `0.95`。
2. FQN + method 匹配，行号不在范围 → confidence `0.70`，`match_reason=fqn_method`，标记行号可疑。
3. 只有 FQN（构造器/类级）→ confidence `0.60`。
4. file name + method 匹配 → confidence `0.50`，`match_reason=file_method`。
5. 无匹配 → 空列表。

行号是 1-based，与 Java 堆栈一致。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T3-01 | 索引 fixture 仓库后能找到 `com.example.order.OrderService` 和 `updateStatus` | 单元测试 |
| AC-T3-02 | T2 的首帧解析到 `.../OrderService.java`，方法 `updateStatus`，行为 24 | 单元测试 |
| AC-T3-03 | `get_source_range` 返回的片段包含第 24 行的 `throw` | 单元测试 |
| AC-T3-04 | 不存在的类/方法返回空列表，不抛异常 | 单元测试 |
| AC-T3-05 | 嵌套类 FQN 可通过 `$` 或 `.` 形式匹配 | 单元测试 |
| AC-T3-06 | 重载方法按行号范围选择候选；无法消歧时返回多个候选 | 单元测试 |
| AC-T3-07 | 行号超出文件范围时裁剪并标记 | 单元测试 |
| AC-T3-08 | 没有 tree-sitter 时，fallback 能找到相同的 fixture 方法，并标记 provenance | 单元测试（可选 mock/开关） |

## 7. 测试计划

### 单元

- `tests/unit/test_java_index.py`
  - 正常类/方法索引。
  - fixture stack frame → SourceMatch。
  - 嵌套类、重载方法、构造器。
  - 不存在/空仓库。
  - 行号越界裁剪。
  - fallback provenance。

### 集成

- 与 T2 的 `ParsedLog` 联合：取 primary event 的首帧，传给 `resolve_frame`，断言结果。
- 由 T6 的集成测试覆盖。

### E2E

- 由 T7 使用 `resolve_frame` 生成 `repo://` 引用；T3 不单独做 CLI E2E。

## 8. Fixture 设计

```text
fixtures/repos/minimal-order-service/
  src/main/java/com/example/order/
    OrderService.java
    OrderController.java
    OrderMapper.java
```

要求：

- `OrderService.updateStatus` 的 `throw new IllegalStateException(...)` 在第 **24** 行。
- `OrderController.handlePaid` 在第 41 行调用 `orderService.handlePaid(...)`（与 T2 堆栈一致）。
- `OrderMapper.updateStatus` 是接口或简单类，第 18 行有方法声明（与 `Caused by` 帧一致）。
- 至少包含一个嵌套类或重载方法，用于 T3 测试；不影响 E2E 主路径。

示例（行号以实现时为准，必须保证 throw 在第 24 行）：

```java
package com.example.order;

import org.springframework.stereotype.Service;

@Service
public class OrderService {
    private final OrderMapper orderMapper;

    public OrderService(OrderMapper orderMapper) {
        this.orderMapper = orderMapper;
    }

    public void handlePaid(Long orderId) {
        this.updateStatus(orderId, "PAID");
    }

    public int updateStatus(Long orderId, String status) {
        if (orderId == null) {
            throw new IllegalArgumentException("orderId is null");
        }
        int rows = orderMapper.updateStatus(orderId, status);
        if (rows == 0) {
            throw new IllegalStateException("update failed for orderId=" + orderId);
        }
        return rows;
    }
}
```

## 9. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| tree-sitter-java 安装失败 | wheel 与 Python 3.12/macOS 不兼容 | 同接口 regex fallback；T1 安装时验证；README 记录 |
| 嵌套类 FQN | 堆栈用 `$`，源码用 `.` | 索引/匹配时统一规范化 |
| 重载方法 | 同名方法多个 | 用行号范围选择；无法消歧返回多个候选 |
| 方法范围 | tree-sitter 节点范围可能包含注释/注解 | 行号裁剪和测试；报告引用以方法范围为准 |
| 静态分析限制 | Lombok/AOP/反射不可见 | 报告注明限制；不声称完整调用图 |
| 性能 | 大仓库递归解析慢 | v0.1 限制 fixture 规模；后续增量索引 |

**开放问题**

- tree-sitter-java 的 method/class 节点查询方式（query 还是 AST walk）在实现时确认。
- 是否需要把 package 声明和文件路径不一致的文件纳入索引？v0.1 以 package 声明为准，同时保留路径。
- fallback 的触发方式：安装失败自动切换，还是显式配置 `TRACEMIND_JAVA_INDEX=regex`？建议显式配置 + 默认 tree-sitter。

## 10. 验证命令

```bash
uv run pytest tests/unit/test_java_index.py -q
```

## 11. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-21 | 创建 T3 spec；定义单仓库索引、frame 匹配、fixture 和验收标准 |
