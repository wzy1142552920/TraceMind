# T5 — 结构化修复与报告 0.3 Spec

- **任务 ID**：T5
- **状态**：planned
- **依赖**：T4
- **下游**：T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.2 报告只有 root_causes（本质是异常位置）、证据来源、工具调用和使用量，没有“为什么”和“怎么改”。v0.3 要让 LLM 基于已支持/已确认的假设和真实证据生成结构化修复方案，并由确定性代码校验每条建议的证据、假设和修改目标。

**用户故事**：作为工程师，我能看到每个候选原因的证据链、同线程日志上下文与代码证据如何互相印证、哪些替代原因被排除、缺失证据，以及按原因分组的修复建议；每条建议都写明依据、风险、前置条件和修改后验证方式，但不会被自动执行。

## 2. In scope

- `RemediationAction` 模型和 `diagnosis.propose_remediation` 控制工具。
- REPORTING 阶段一次 remediation LLM 调用（覆盖所有 supported/confirmed 假设）。
- 确定性校验/丢弃无效 action：
  - 假设状态、证据 ID、证据关联、类型、target、去重、数量上限。
- 报告 schema 0.3：
  - `hypotheses`（排序、因果链、覆盖率、支持/反证/缺失、falsifiers）。
  - `remediation_plan`。
  - `verification`（fixture/none、backend、查询表、note）。
  - 扩展 validation。
- Markdown 模板和 CLI 摘要更新。
- 引用校验扩展 `db://` 与 `log://.../thread=...` 上下文；修复接地校验；fake 验证标注校验；状态一致性。
- 报告展示 `log_thread_context` 与代码/工具证据的对应关系，便于人工核对“日志上下文 + 代码”结论。
- RunStore/run.json schema 0.3。
- 单测/集成测试和旧报告测试迁移。

## 3. Out of scope

- 自动应用修复、生成 diff/patch、执行命令/SQL。
- 真实 DB backend（T3 只有 Fake）。
- 三 case fixtures/eval（T6）。
- live 验证（T7）。
- Web UI/OTel。
- catalog 驱动的修复模板。
- 0.2 报告兼容 shim。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T5-01 | 定义 RemediationAction 模型和 propose_remediation 工具 | must |
| FR-T5-02 | REPORTING 只对 supported/confirmed 假设生成修复建议 | must |
| FR-T5-03 | 每条 action 必须绑定 hypothesis 和真实 evidence IDs（或可合并解析的 source_refs） | must |
| FR-T5-04 | 校验 type/title/description/target/risk/verification，拒绝无效 action | must |
| FR-T5-05 | code target 必须在仓库内；data target 必须在验证白名单内 | must |
| FR-T5-06 | 去重/每假设最多 3 条/总计最多 8 条 | must |
| FR-T5-07 | 无有效修复时不伪造；记录 limitation/validation error | must |
| FR-T5-08 | 报告 schema 0.3 包含 hypotheses/remediation_plan/verification | must |
| FR-T5-09 | 报告校验 repo/log/db 引用、证据 ID、修复接地、fake 标注、状态一致 | must |
| FR-T5-10 | 诊断校验失败降级 status；无效 remediation 丢弃并标记 | must |
| FR-T5-11 | Markdown/CLI/RunStore 更新到 0.3 | must |
| FR-T5-12 | 条件性建议（supported 假设）在报告中标注 | must |
| FR-T5-13 | 报告不含 Key/完整 DB 行/完整源码/敏感值 | must |
| FR-T5-14 | 退出码保持 0/1/2/3/4 | must |
| FR-T5-15 | 报告展示/校验 `log_thread_context` 证据，支持 thread 级 `log://` source_ref | must |

## 5. 接口/数据契约

### 5.1 RemediationAction

```python
class RemediationAction(BaseModel):
    action_id: str
    hypothesis_id: str
    type: Literal["code", "config", "data", "ops", "test"]
    title: str
    description: str
    evidence_ids: list[str]
    target: str
    risk: str
    prerequisites: list[str] = []
    verification_steps: list[str] = []
```

字段规则：

| 字段 | 规则 |
|---|---|
| title | 1..120 字 |
| description | 1..1000 字 |
| evidence_ids | 1..8 个，真实存在且关联该假设 |
| target | code/data 需可校验；config/ops/test 非空 |
| risk | 1..300 字 |
| prerequisites | 0..5 条，每条 ≤300 字 |
| verification_steps | 0..5 条，每条 ≤300 字 |

- `action_id` 由 runtime 分配（`act_001...`）。
- LLM 只能提交不含 action_id 的 action。
- LLM 输入可用 `evidence_ids` 和/或 `evidence_source_refs`；runtime 解析后存 `evidence_ids`，报告只展示解析后的 ID。
- 修复建议只读展示，不执行。

### 5.2 `diagnosis.propose_remediation`

输入：

```json
{
  "actions": [
    {
      "hypothesis_id": "hyp_001",
      "type": "code",
      "title": "区分“不存在”与“无变化”两种 0 行结果",
      "description": "在 updateStatus 返回 0 后查询当前状态；不存在则返回业务错误，已为目标状态则按幂等成功处理。",
      "evidence_ids": ["ev_0012", "ev_0015"],
      "evidence_source_refs": ["db://orders/id=10086"],
      "target": "src/main/java/com/example/order/OrderService.java",
      "risk": "改变现有失败语义；需要与调用方确认幂等契约。",
      "prerequisites": ["确认支付回调允许重复投递"],
      "verification_steps": ["补充重复回调测试", "验证订单不存在时返回明确错误码"]
    }
  ]
}
```

- 只在 REPORTING 阶段暴露/接受；诊断阶段调用 → `INVALID_REMEDIATION`。
- 一次最多 8 条；同一假设最多 3 条。
- 无效 action 不进入报告，记录 `remediation.rejected` 和 validation error。

### 5.3 校验规则

1. hypothesis 存在且状态 ∈ {supported, confirmed}。
2. evidence_ids/evidence_source_refs 合并解析后非空、全部存在，且至少一条关联该假设（basis 或 assessment 引用）；source_ref 解析不到即拒绝。
3. type 在枚举内。
4. title/description/risk 非空且不超长。
5. target：
   - `code`: 必须是 repo 内存在的文件路径（可带 `#symbol` 后缀；文件部分必须存在）。
   - `data`: 若存在验证 backend，表必须在白名单；无 backend 时拒绝 data target。
   - `config` / `ops` / `test`: 非空、≤300 字；不做文件级验证，报告标注“目标未自动验证”。
6. 重复 `(hypothesis_id, type, target)` 只保留第一条。
7. 超出每假设/总数上限的 action 丢弃。
8. 不生成 diff/patch/可执行命令。

### 5.4 报告 schema 0.3

```json
{
  "schema_version": "0.3",
  "incident_id": "...",
  "run_id": "...",
  "service": "...",
  "status": "confirmed|probable|insufficient_data",
  "summary": "...",
  "hypotheses": [
    {
      "hypothesis_id": "hyp_001",
      "statement": "...",
      "cause_chain": ["..."],
      "status": "confirmed",
      "ranking_score": 12,
      "basis_evidence_ids": ["ev_0001"],
      "requirements": [
        {
          "requirement_id": "hyp_001_req_01",
          "description": "...",
          "evidence_kinds": ["db_row"],
          "discriminating": true,
          "satisfied": true,
          "supporting_evidence_ids": ["ev_0012"],
          "refuting_evidence_ids": []
        }
      ],
      "supporting_evidence_ids": ["..."],
      "refuting_evidence_ids": [],
      "missing_requirement_ids": [],
      "falsifiers": ["..."]
    }
  ],
  "remediation_plan": [
    {
      "action_id": "act_001",
      "hypothesis_id": "hyp_001",
      "type": "code",
      "title": "...",
      "description": "...",
      "evidence_ids": ["ev_0012"],
      "target": "src/main/java/.../OrderService.java",
      "risk": "...",
      "prerequisites": [],
      "verification_steps": ["..."],
      "conditional": false
    }
  ],
  "verification": {
    "environment": "fixture|none",
    "backend": "fake|null",
    "tables_queried": ["orders"],
    "note": "Runtime data came from a fixture, not a live database."
  },
  "sources": [
    {
      "evidence_id": "ev_0002",
      "kind": "log_thread_context",
      "source_ref": "log://incident.log#thread=http-nio-8080-exec-7&L2-L5",
      "claim": "Thread http-nio-8080-exec-7: INFO paid...; WARN rows=0; ERROR failed...",
      "thread": "http-nio-8080-exec-7",
      "line_start": 2,
      "line_end": 5,
      "messages": [
        "paid callback orderId=10086",
        "updateStatus returned rows=0, orderId=10086",
        "failed to update order status"
      ]
    }
  ],
  "tool_calls": [],
  "llm_usage": {},
  "llm_calls": [],
  "limitations": [],
  "stop": {"reason": "...", "state": "..."},
  "budget_usage": {},
  "validation": {
    "citations_valid": true,
    "evidence_ids_valid": true,
    "hypotheses_valid": true,
    "remediation_grounded": true,
    "verification_labeled": true,
    "status_consistent": true,
    "errors": []
  }
}
```

- `root_causes` 移除。
- `conditional=true` 表示该建议针对 `supported`（未确认）假设。
- `ranking_score` 标注为排序分，不是概率。
- `sources[]` 由 runtime 从证据账本生成，至少含 evidence_id/kind/source_ref/claim；`log_thread_context` 额外带 thread/line_start/line_end/messages（按日志顺序的摘要，不含堆栈），供报告展示和引用校验。
- `sources[]` 只包含被假设 basis/requirements/remediation 引用的证据，按 evidence_id 去重；不倾倒整个 ledger。

### 5.5 报告状态

| 条件 | status |
|---|---|
| run 级 confirmed 且替代假设全部 contradicted | `confirmed` |
| 存在 supported/confirmed 但存在开放替代 | `probable` |
| 无支持/确认或证据不足 | `insufficient_data` |
| run FAILED | `insufficient_data` |

- 退出码保持 v0.2 语义。

### 5.6 引用与一致性校验

`ReportValidation` 增加：

- `hypotheses_valid`
- `remediation_grounded`
- `verification_labeled`

校验：

1. `repo://` 文件/行范围存在；`log://` 事件/文件存在；`log://<file>#thread=<thread>&Lx-Ly` 能解析到至少一条账本中的同线程上下文证据且行范围有效；`db://` source_ref 在证据账本中存在。
2. 所有 basis/support/refute/remediation evidence ID 存在。
3. confirmed 假设满足 DESIGN §6.3 的 run 级条件。
4. remediation action 的假设/证据/target 合法。
5. 有 fake DB 证据时 `verification.environment=fixture` 且 note 非空；无 DB 证据时 environment=`none`。
6. report status 与 runtime 计算一致。
7. 失败处理：
   - 引用/证据/假设/状态失败：status 降级 `insufficient_data`，追加 limitation。
   - remediation 失败：丢弃无效 action，`remediation_grounded=false`，诊断状态不因此降级。

### 5.7 Markdown

必须包含：

1. 摘要（含验证环境提示）。
2. 鉴别诊断（按 ranking_score）：
   - 假设状态、因果链、basis、requirements 覆盖表、支持/反证/缺失证据、falsifiers。
   - 证据按类别展示：同线程日志上下文、代码/调用链、SQL、只读数据；同线程上下文展示线程号与行范围。
3. 验证过程：
   - environment/backend/tables/查询摘要/note。
4. 修复方案：
   - 按假设分组；type/target/description/evidence/risk/prerequisites/verification；条件性建议标注。
5. 证据来源（含 `log_thread_context` 的线程/行范围和代码证据）。
6. 工具调用、LLM 使用、停止原因、限制、校验。

### 5.8 CLI

- Rich 摘要：
  - Top hypothesis（status/statement）。
  - 假设数、证据数、工具调用数、修复建议数。
  - 验证环境（fixture/none）。
  - 校验结果。
- `--json` 摘要增加：`hypothesis_count`、`top_hypothesis`、`remediation_count`、`verification_environment`。
- 退出码不变。

### 5.9 RunStore

- run.json/report.json schema `0.3`。
- run_meta 增加 verification 元数据、hypothesis/assessment 计数。
- events/audit 仍为 JSONL。
- 不含 Key/完整 DB 行/完整源码/敏感值。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T5-01 | 报告含 hypotheses/remediation_plan/verification，schema 0.3 | `tests/unit/test_report_v03.py` |
| AC-T5-02 | 修复建议只针对 supported/confirmed 假设 | `test_remediation.py` |
| AC-T5-03 | 无证据/伪造 evidence/无法解析 source_ref/错误 hypothesis 的 action 被拒绝 | 同上 |
| AC-T5-04 | code target 越界/不存在、data target 非白名单被拒绝 | 同上 |
| AC-T5-05 | 去重/每假设/总数上限生效 | 同上 |
| AC-T5-06 | supported 假设的建议标记 conditional | 报告测试 |
| AC-T5-07 | 无有效修复时不伪造，增加 limitation/validation error | 同上 |
| AC-T5-08 | `db://` 引用校验、fake 环境标注 | `test_citation_validator.py` |
| AC-T5-09 | 诊断校验失败降级 status；remediation 失败不降级 | 报告测试 |
| AC-T5-10 | Markdown/CLI/RunStore 0.3 字段完整 | E2E/CLI 测试 |
| AC-T5-11 | 退出码不变 | CLI 测试 |
| AC-T5-12 | 报告/产物无 Key/完整 DB 行/完整源码 | secret scan/E2E |
| AC-T5-13 | 旧 root_causes 测试迁移，无 0.2 shim | 全量测试 |
| AC-T5-14 | remediation 调用计入 LLM/工具预算 | runtime 测试 |
| AC-T5-15 | 报告展示并校验同线程上下文证据；thread 级 `log://` 引用可验证 | `test_report_v03.py` + `test_citation_validator.py` |

## 7. 测试计划

### 单元

- `tests/unit/test_remediation.py`
  - 合法 action。
  - hypothesis 状态不合法。
  - 证据缺失/未关联/伪造。
  - type/target/title/description/risk 校验。
  - code target 越界、data target 非白名单。
  - 去重/数量上限。
- `tests/unit/test_report_v03.py`
  - status 映射、hypotheses 排序、conditional 标记。
  - verification fixture/none。
  - validation 降级逻辑。
- `tests/unit/test_citation_validator.py` 扩展
  - `db://` 有效/无效/不在证据账本。
  - `log://#thread=...&Lx-Ly` 有效/线程不存在/行号越界。
  - fake 环境标注缺失 → validation 失败。

### 集成/E2E

- 更新 `tests/e2e/test_minimal_loop.py`：schema 0.3、hypotheses/remediation/verification。
- 更新 `tests/unit/test_run_store.py`、`test_report.py`、`test_cli.py`。
- 用 T4 的多假设 RunResult 构建报告，不依赖 T6 三 case。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 修复建议幻觉 | 描述合理但无证据 | evidence 绑定 + target 校验 + conditional 标注 |
| 证据洗白 | 引用无关 evidence | 要求关联假设；报告展示 evidence/rationale；人工复核 |
| 报告膨胀 | 多假设+多建议+证据 | 数量上限、摘要、Markdown 分组 |
| 假验证误读 | fixture 被当成生产 | environment/note/limitations 强制 |
| schema 破坏 | 0.2 消费者 | v0.3 无 shim；文档/测试同步 |
| target 校验有限 | config/ops/test 只检查非空 | 标记“未自动验证”；code/data 强校验 |
| 预算 | remediation 调用额外 LLM | 计入预算；耗尽时跳过并说明 |

**开放问题**

- 是否为 supported 假设生成修复建议？是，但 `conditional=true`。
- 是否允许多个 confirmed 假设？不允许；两个 qualifies 视为歧义，报告 probable。
- 是否生成代码片段/diff？v0.3 不生成；只给结构化建议。
- 是否允许 data 修复建议包含 SQL 文本？不强制字段；以文字描述为主，不执行。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_remediation.py tests/unit/test_report_v03.py tests/unit/test_citation_validator.py tests/e2e/test_minimal_loop.py -q
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
| 2026-10-22 | 创建 T5 spec：结构化 remediation、报告 0.3、引用/接地/fixture 标注校验 |
| 2026-10-22 | 增加同线程日志上下文展示与 thread 级 `log://` 引用校验 |
