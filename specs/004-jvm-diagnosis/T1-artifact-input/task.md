# T1 — Artifact 输入契约 Task

- **关联 Spec**：[spec.md](./spec.md)
- **任务 ID**：T1
- **状态**：implemented（记录在 raw bundle；run_meta/report 接线由 T5 完成）
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6、T7

## 1. 实施顺序

1. **确认契约**
   - 阅读 T1 spec 与 [DESIGN §3](../DESIGN.md)。
   - 确认 T1 只做加载/校验/记录，不做解析与工具注册。
   - 确认 path 用 POSIX 语义、bundle 根内解析、拒绝 symlink。

2. **先写测试**
   - `tests/unit/test_artifact_manifest.py`：合法加载、schema、kind/id/service、上限、编码。
   - `tests/unit/test_artifact_safety.py`：路径穿越、绝对路径、symlink、根外、记录无绝对路径。
   - `tests/unit/test_artifact_redaction.py`：脱敏 pattern。
   - `tests/e2e/test_cli_artifacts.py`：CLI 退出码与无 run 目录。
   - 测试先失败。

3. **实现模型**
   - 新增 `src/tracemind/artifacts/models.py`：枚举、manifest、document、record、bundle、`ArtifactError`。
   - frozen/Pydantic v2；文本行不可变。
   - `ArtifactBundle.records` 由文档生成，不保存绝对路径。

4. **实现加载器**
   - 新增 `loader.py`：manifest 字节上限、UTF-8、`json.loads`、Pydantic 校验。
   - service 匹配；id 唯一；kind 上限；路径 `PurePosixPath` 校验。
   - 逐组件 `lstat` 拒绝 symlink；`resolve()` 后 `relative_to(root)`。
   - 普通文件、大小、行数、总量、严格 UTF-8；构建文档/记录。
   - 错误信息只含 artifact id/相对路径与原因。

5. **实现脱敏**
   - 新增 `redaction.py`：大小写不敏感的赋值/Authorization 模式。
   - 去重类别；不返回原值；不因同一行多处命中重复替换。
   - 只作为文本处理工具，不修改文件。

6. **CLI 接线**
   - 新增 `--artifacts PATH`（可选目录）。
   - 在 provider/日志/索引/run 之前调用 `load_artifacts(path, service)`；失败 `_fail(..., 2)`。
   - 保存 bundle 供后续任务使用；T1 先只传元数据或暂存（T3/T4 使用）。
   - 保持无 `--artifacts` 分支不变。

7. **回归**
   - 旧 CLI/单元测试；无 artifacts 行为不变。
   - 运行验证命令并回填。

## 2. 交付物

- [x] `src/tracemind/artifacts/__init__.py`
- [x] `src/tracemind/artifacts/models.py`
- [x] `src/tracemind/artifacts/loader.py`
- [x] `src/tracemind/artifacts/redaction.py`
- [x] `src/tracemind/cli/main.py`（`--artifacts`；bundle 传递给 runtime 由 T4 完成）
- [x] `tests/unit/test_artifact_manifest.py`
- [x] `tests/unit/test_artifact_safety.py`
- [x] `tests/unit/test_artifact_redaction.py`
- [x] `tests/e2e/test_cli_artifacts.py`

## 3. Definition of Done

- [x] AC-T1-01 至 AC-T1-12 全部满足。
- [x] 非法 bundle 一律在 run 产物创建前退出 2。
- [x] 记录/错误不含绝对路径或文件内容。
- [x] symlink/路径穿越/超大/非 UTF-8 均有负向测试。
- [x] 无 `--artifacts` 时全量旧测试通过。
- [x] 全量离线测试、ruff、mypy 通过。
- [x] 不修改 001/002/003 specs 或 v2 设计文档。

## 4. 验证命令

```bash
uv run pytest tests/unit/test_artifact_manifest.py tests/unit/test_artifact_safety.py tests/unit/test_artifact_redaction.py tests/e2e/test_cli_artifacts.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src
```

## 5. 风险与开放问题

- **symlink 检查**：父目录 symlink 必须拒绝；测试在 macOS/Linux 上都要稳定。
- **上限测试**：用 monkeypatch 缩小阈值，不提交 32 MiB fixture。
- **CLI 加载时机**：必须在 provider 构建前，避免 DeepSeek 配置错误掩盖 artifact 错误；至少确保不创建 run 目录。
- **record 不含路径**：所有日志/错误/报告只看 `source_name` 与 artifact id。
- **T2/T3 依赖**：不要把 bundle.lines 直接塞入 prompt；T3 才做有界输出。

## 6. 验证结果（实现后回填）

| 日期 | 执行人 | 命令/检查 | 结果 | 备注 |
|---|---|---|---|---|
| 2026-10-23 | Claude | T1 专项 pytest | PASS（44 passed） | manifest/safety/redaction/CLI artifacts |
| 2026-10-23 | Claude | `uv run pytest -q` | PASS（429 passed, 6 skipped） | live 保持 opt-in |
| 2026-10-23 | Claude | `ruff check` / `mypy src` | PASS | T1 文件无告警 |
