# T2 — 领域模型与日志解析 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T2
- **状态**：draft
- **依赖**：T1
- **下游**：T3、T4、T6

## 1. 实施顺序

> 当前阶段只生成文档；以下步骤供后续实现会话执行。严格按“spec → 测试 → 实现 → 验证”的顺序。

1. **确认 spec**
   - 阅读 T2 `spec.md`，确认日志头格式、堆栈规则、primary event 规则、fixture 内容。
   - 确认模型字段能被 T3（栈帧）、T4（日志工具）、T6（证据）直接使用。

2. **定义模型**
   - 在 `src/tracemind/core/models.py` 定义 `StackFrame`、`ExceptionCause`、`LogEvent`、`ParsedLog`。
   - 在 `src/tracemind/core/errors.py` 定义 `LogParseError`。
   - 所有模型使用 Pydantic v2，可序列化。

3. **创建 fixture**
   - 创建 `fixtures/logs/basic/incident.log`，内容按 spec §8。
   - 行号与 T3 fixture 的 `OrderService.java` 第 24 行对应。
   - 包含一个 `Caused by` 和 `... 2 more`。

4. **先写测试**
   - `tests/unit/test_log_parser.py`：事件数、primary、字段、堆栈、cause、未知行、空文件。
   - `tests/unit/test_stacktrace.py`：普通/native/未知/反射帧。
   - 测试先失败（模块不存在/未实现）。

5. **实现日志头与事件合并**
   - 读取文件，保留原始行号。
   - 识别日志头；未匹配行作为上一个事件的 continuation 或 warning。
   - 生成 `evt_0001` 形式的事件 ID。
   - 解析时间（固定格式，失败记 warning，不崩溃）。

6. **实现堆栈解析**
   - 识别 `Caused by:`/`Suppressed:`/`... N more`。
   - 解析 `at` 帧；处理 native/unknown/反射帧。
   - 把顶层帧放入 `stack_frames`，cause 帧放入 `cause_chain`。

7. **实现 primary event 选择**
   - 按 spec FR-T2-05：第一个带 stack frame 的异常事件；否则第一个 ERROR；否则第一个 WARN。
   - 记录 `primary_event_id`。

8. **验证并回填**
   - 运行 T2 spec 的验证命令。
   - 把结果写入本文档 §6。

## 2. 交付物

- [ ] `src/tracemind/core/models.py`（StackFrame/ExceptionCause/LogEvent/ParsedLog）
- [ ] `src/tracemind/core/errors.py`（LogParseError）
- [ ] `src/tracemind/log_analysis/parser.py`
- [ ] `src/tracemind/log_analysis/stacktrace.py`
- [ ] `src/tracemind/log_analysis/__init__.py`
- [ ] `fixtures/logs/basic/incident.log`
- [ ] `tests/unit/test_log_parser.py`
- [ ] `tests/unit/test_stacktrace.py`

## 3. Definition of Done

- [ ] T2 spec 的 AC-T2-01 至 AC-T2-08 全部满足。
- [ ] fixture 解析结果可被 T3/T4/T6 直接消费，无需二次清洗。
- [ ] 未知行/空文件/截断堆栈不崩溃。
- [ ] `LogEvent`/`ParsedLog` 可 `model_dump_json()`。
- [ ] 没有引入 LLM/网络/额外依赖。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_log_parser.py tests/unit/test_stacktrace.py -q
```

## 5. 开放问题 / 风险

- **主事件选择**：v0.1 固定规则；如果后续需要多异常/多服务，增加配置和评分。
- **时间解析**：v0.1 只支持 `YYYY-MM-DD HH:MM:SS.mmm`；其他格式记 warning，时间留空。
- **多行异常消息**：v0.1 只按缩进/`at` 行合并；异常消息中的换行可能产生额外 continuation，需要在测试中确认。
- **编码**：v0.1 按 UTF-8 读取；GBK 后续支持。
- **行号对应**：fixture 的 `OrderService.java:24` 必须在 T3 fixture 中保持一致；T2/T3 任务需交叉检查。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| — | — | — | 未执行 | 当前阶段只生成文档 |
