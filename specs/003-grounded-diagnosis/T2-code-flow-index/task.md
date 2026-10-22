# T2 — 代码流索引与工具 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T2
- **状态**：planned
- **依赖**：T1
- **下游**：T4、T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T2 spec、[DESIGN §7.2–§7.3](../DESIGN.md) 和 T1 工具绑定元数据。
   - 确认所有调用边是 `ast_heuristic`，不是运行时调用图。
   - 确认 v0.3 不解析 MyBatis XML/动态 SQL。

2. **先写索引测试**
   - 扩展 `tests/unit/test_java_index.py`：注解、字段、调用点、SQL、重载 arity。
   - 新增 `tests/unit/test_code_flow.py`：三条关键调用边和候选规则。
   - 新增 `tests/unit/test_code_flow_tools.py`：四个新工具 + find_symbol 增强。
   - 测试先失败。

3. **扩展索引模型与遍历**
   - `JavaSymbol` 增加 annotations/parameter_count/return_type/modifiers。
   - 新增 `AnnotationInfo`、`JavaField`、`MethodCall`、`CallEdge`、`SqlArtifact`。
   - `_walk` 收集字段/方法体调用；保留现有类/方法索引行为。
   - 提取注解简单字面量参数；`@Update` 等 SQL。
   - 不引入新依赖。

4. **实现调用解析**
   - 构建类 → 字段类型、方法（含 arity）索引。
   - `this`/隐式、字段 receiver、import/类名、全仓库 fallback。
   - 返回多候选 + confidence/provenance/source_ref。
   - 重载按参数个数过滤；无法解析时不伪造唯一结果。

5. **实现工具**
   - 新增 `code.get_symbol`、`code.get_callers`、`code.get_callees`、`code.find_sql`。
   - 增强 `code.find_symbol` 输出。
   - 支持从日志 `logger` 简单类名和栈帧定位代码符号（复用现有索引匹配）。
   - 所有参数模型继承 T1 `EvidenceToolMeta`，限制 limit/查询长度。
   - 未知 symbol → `TARGET_DENIED`；输出截断标记。
   - 工具描述明确“候选调用边”。

6. **接线与回归**
   - 注册到默认 registry；不新增写/网络工具。
   - 更新受影响的旧索引/工具测试。
   - 运行 T2 验证命令并回填。

## 2. 交付物

- [ ] `src/tracemind/indexing/java_index.py` 扩展
- [ ] 新工具实现（可放在 `tools/builtin.py` 或 `tools/code_flow.py`）
- [ ] 工具注册与描述
- [ ] `tests/unit/test_java_index.py` 扩展
- [ ] `tests/unit/test_code_flow.py`
- [ ] `tests/unit/test_code_flow_tools.py`
- [ ] 受影响的 registry/executor 测试适配

## 3. Definition of Done

- [ ] AC-T2-01 至 AC-T2-13 全部满足。
- [ ] `OrderController.paid → OrderService.handlePaid → OrderService.updateStatus → OrderMapper.updateStatus` 关键链路可查。
- [ ] 重载方法不强行唯一；所有候选带 confidence/provenance。
- [ ] `@Update` SQL、表名和 guard 条件可查。
- [ ] 未知 symbol/超限参数有稳定错误。
- [ ] 现有 find_symbol/get_source_range 行为不回归。
- [ ] 日志 `logger` 简单类名/栈帧可解析到类或方法，且不越权解析日志内容。
- [ ] 全量离线测试、ruff、mypy 通过。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_java_index.py tests/unit/test_code_flow.py tests/unit/test_code_flow_tools.py tests/unit/test_tool_binding.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **误报边**：无类型解析，字段 receiver 可能指向错误类型；必须返回候选并标注 confidence。
- **重载消歧**：名称+arity 仍可能多候选；不要强行选一个。
- **注解解析**：复杂表达式/数组/常量引用可能无法提取；跳过并记录 warning，不伪造 SQL。
- **工具输出膨胀**：限制 limit 和输出字节；截断必须标记。
- **绑定元数据**：继承 T1 base model；handler 不得把 meta 当作业务参数。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | 待实现 | PLANNED | — |
