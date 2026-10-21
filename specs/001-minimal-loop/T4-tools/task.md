# T4 — Tool 层 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T4
- **状态**：implemented
- **依赖**：T1、T2、T3
- **下游**：T6、T7

## 1. 实施顺序

> T4 已实现；以下步骤保留作为复现指南。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T4 `spec.md`，确认四个工具的参数/返回、错误码、路径规则。
   - 确认 T2 的 `ParsedLog`、T3 的 `JavaIndex` 能提供工具上下文。

2. **定义契约**
   - `src/tracemind/tools/contracts.py`：ToolSpec、ToolRequest、ToolResult、错误码。
   - `src/tracemind/tools/registry.py`：注册/查找/列出。
   - `src/tracemind/tools/executor.py`：执行链、去重、审计收集。
   - `src/tracemind/workspace/paths.py`：路径规范化与 root 约束。

3. **先写测试**
   - 正常调用、路径穿越、未知工具、非法参数、重复调用、输出裁剪、审计。
   - 测试先失败（模块不存在/未实现）。

4. **实现路径安全**
   - `resolve_under_root(root, relative_path)`：拒绝绝对路径/`..`/符号链接逃逸。
   - 测试 `../`、绝对路径、`~`、符号链接。

5. **实现 Registry/Executor**
   - Pydantic 参数校验。
   - 工具查找。
   - canonical args hash + 去重。
   - 输出裁剪。
   - 审计事件收集（内存列表；T7 写 JSONL）。

6. **实现四个工具**
   - `logs.search` / `logs.get_event_context` 基于 `ParsedLog`。
   - `code.find_symbol` / `code.get_source_range` 基于 `JavaIndex`。
   - 返回 `source_ref`。
   - 不直接读任意路径。

7. **验证并回填**
   - 运行 T4 spec 的验证命令，回填 §6。

## 2. 交付物

- [x] `src/tracemind/tools/contracts.py`
- [x] `src/tracemind/tools/registry.py`
- [x] `src/tracemind/tools/executor.py`
- [x] `src/tracemind/tools/builtin.py`
- [x] `src/tracemind/workspace/paths.py`
- [x] `src/tracemind/tools/__init__.py`、`src/tracemind/workspace/__init__.py`
- [x] `tests/unit/test_tool_executor.py`
- [x] `tests/unit/test_tool_registry.py`

## 3. Definition of Done

- [x] T4 spec 的 AC-T4-01 至 AC-T4-11 全部满足。
- [x] Runtime 只能通过 ToolExecutor 调用工具；没有直接文件读取旁路。
- [x] 路径穿越/绝对路径/符号链接逃逸全部拒绝。
- [x] 重复调用不重复执行，返回 `DUPLICATE_CALL`。
- [x] 每次调用有审计事件；输出有上限/`truncated`。
- [x] 不依赖 LLM/网络/写操作。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_tool_executor.py tests/unit/test_tool_registry.py -q
```

## 5. 开放问题 / 风险

- **工具上下文构造**：ToolExecutor 需要 `ParsedLog`、`JavaIndex`、repo root、log root；建议用构造器注入，不要全局单例。
- **event_id 查找**：T2 的 event_id 在单文件内稳定；T4 只支持单文件上下文。
- **去重上限**：v0.1 同工具同参数上限 1；如果 Runtime 需要多轮相同查询，应在第一次结果中保留足够信息。
- **审计写入**：T4 只收集事件；T7 决定 JSONL 路径和失败策略。
- **源码路径**：LLM 只能给相对路径；T4 解析后检查 root。绝对路径/`..` 一律拒绝。
- **日志搜索语义**：v0.1 字面量、case-insensitive；正则可作为后续扩展。
- **输出裁剪**：先裁剪文本再包装 JSON，避免返回非法 JSON；在 ToolResult 标记 `truncated`。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-21 | Claude | `uv run pytest tests/unit/test_tool_executor.py tests/unit/test_tool_registry.py -q` | 17 passed | T4 专项 |
| 2026-10-21 | Claude | `uv run pytest -q` | 65 passed | 全量 |
| 2026-10-21 | Claude | `uv run ruff check .` | All checks passed | — |
| 2026-10-21 | Claude | `uv run mypy src` | Success: no issues found in 22 source files | — |
| 2026-10-21 | Claude | 安全用例 | 路径穿越/绝对路径/符号链接逃逸均被拒绝 | `TARGET_DENIED` |
