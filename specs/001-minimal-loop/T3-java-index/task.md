# T3 — Java 源码索引 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T3
- **状态**：draft
- **依赖**：T1、T2
- **下游**：T4、T6

## 1. 实施顺序

> 当前阶段只生成文档；以下步骤供后续实现会话执行。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T3 `spec.md` 和 T2 的 `StackFrame` 契约。
   - 确认 fixture 行号（OrderService.java:24、OrderController.java:41、OrderMapper.java:18）。

2. **定义契约**
   - 在 `src/tracemind/indexing/java_index.py` 定义 `JavaSymbol`、`SourceMatch`、`SourceSnippet`、`IndexStats`、`JavaIndex` Protocol。
   - 复用 T2 的 `StackFrame`；不要复制字段。
   - 明确相对路径、1-based 行号、provenance。

3. **创建 fixture 仓库**
   - 按 spec §8 创建 `fixtures/repos/minimal-order-service/`。
   - 保证 `OrderService.updateStatus` 的 throw 在第 24 行；用测试断言，而不是靠肉眼。
   - 可选加入嵌套类/重载方法，但不得改变主路径行号。

4. **先写测试**
   - `tests/unit/test_java_index.py`：类/方法索引、frame 解析、行号、嵌套类、重载、缺失、越界、fallback。
   - 测试先失败（模块不存在/未实现）。

5. **实现 tree-sitter 提取器**
   - 使用 `tree-sitter` + `tree-sitter-java` 解析文件。
   - 提取 package/class/interface/enum/record/method/constructor。
   - 计算 1-based start/end line；建立 FQN/method/file 索引。
   - 跳过 `target/`、`build/`、`.git/`。

6. **实现 frame 匹配**
   - 依次尝试 FQN+method+line、FQN+method、file+method。
   - 规范化嵌套类 `$`/`.`。
   - 返回 `SourceMatch` 列表，按 confidence 排序；无匹配返回 `[]`。

7. **实现源码片段读取**
   - `get_source_range` 读取相对路径，裁剪越界行，返回带行号文本。
   - 路径安全最终由 T4 的 ToolExecutor 再校验；T3 仍做基本路径约束。

8. **实现 fallback（可选）**
   - 如果 tree-sitter 不可用，用 regex 提取 package/class/method；标记 `provenance="regex_fallback"`。
   - 不把 fallback 结果伪装成 tree-sitter。

9. **验证并回填**
   - 运行 T3 spec 的验证命令，回填 §6。

## 2. 交付物

- [ ] `src/tracemind/indexing/__init__.py`
- [ ] `src/tracemind/indexing/java_index.py`
- [ ] `fixtures/repos/minimal-order-service/src/main/java/com/example/order/OrderService.java`
- [ ] `fixtures/repos/minimal-order-service/src/main/java/com/example/order/OrderController.java`
- [ ] `fixtures/repos/minimal-order-service/src/main/java/com/example/order/OrderMapper.java`
- [ ] `tests/unit/test_java_index.py`
- [ ] 可选的 `src/tracemind/indexing/regex_index.py`

## 3. Definition of Done

- [ ] T3 spec 的 AC-T3-01 至 AC-T3-08 全部满足。
- [ ] T2 的首帧能解析到 fixture 的 `OrderService.java:24`。
- [ ] 找不到/越界/空仓库不抛异常。
- [ ] 所有 `SourceMatch` 带 provenance/confidence。
- [ ] fixture 行号与 T2 日志、T4/T6 断言一致。
- [ ] tree-sitter 不可用时有明确 fallback 路径或明确失败提示，不静默返回空结果。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_java_index.py -q
```

## 5. 开放问题 / 风险

- **tree-sitter API**：`tree_sitter_java.language()` 的导入方式、节点类型名需在实现时确认；先用小脚本验证，再写正式代码。
- **行号稳定性**：fixture 中的 throw 必须在第 24 行；用测试断言，避免格式化/加注释后漂移。
- **嵌套类**：树遍历需要把外层类名拼进 FQN；堆栈中的 `$` 形式要能匹配。
- **重载方法**：v0.1 用行号范围消歧；如果两个重载范围重叠（不可能）或行号缺失，返回多个候选。
- **fallback**：如果 tree-sitter 可用，fallback 不应影响主路径；通过显式配置或单测注入切换。
- **方法范围**：tree-sitter 方法节点可能包含注解/注释；报告引用以方法 start/end 为准，必要时缩小到语句行。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | — | 未执行 | 当前阶段只生成文档 |
