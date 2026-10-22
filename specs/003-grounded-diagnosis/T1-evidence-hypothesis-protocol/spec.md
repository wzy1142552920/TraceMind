# T1 — 证据账本与假设协议 Spec

- **任务 ID**：T1
- **状态**：planned
- **依赖**：无
- **下游**：T2、T3、T4、T5、T6、T7
- **父设计**：[TraceMind v2.0](../../../docs/TraceMind_Agent_System_Design_v2.md)
- **v0.3 设计**：[DESIGN](../DESIGN.md)
- **v0.3 索引**：[README](../README.md)

## 1. Context / 用户故事

v0.2 的 `Evidence` 只有 kind/claim/source_ref/strength/supports；`Hypothesis` 由栈帧确定性生成，只有一个，且 Evaluator 只检查 `stack_frame + log_event + source_code`。它能证明“异常在这个位置发生”，不能承载“多个可能原因、每个原因需要什么证据、证据是否支持或反驳”。

v0.3 要求 LLM 自主提出假设，但假设必须基于真实证据。T1 先建立这个底座：证据账本、假设/验证要求/证据评估模型、控制工具、以及确定性评估核心。T1 不接入新的代码流/DB 工具，也不改写运行时主循环。

**用户故事**：作为运行时，我收到 LLM 提出的假设时，能验证它引用的证据真实存在；我收到 LLM 的证据评估时，能验证该证据确实是为该假设/要求采集的；我能在任何时刻用确定性规则计算假设状态，而不是相信模型自报。

## 2. In scope

- 扩展 `Evidence`：kind 枚举（含 `log_thread_context`）、provenance、tool_call_id、observed_at、independence_group、bound hypothesis/requirement、结构化 content。
- 新增 `EvidenceLedger`：唯一创建入口、去重、检索、按假设/要求查询。
- 新增 `Hypothesis`、`EvidenceRequirement`、`EvidenceAssessment`、`HypothesisStatus` 模型。
- 新增控制工具：
  - `diagnosis.propose_hypothesis`
  - `diagnosis.assess_evidence`
- 证据类工具公共元数据：`hypothesis_id`、`requirement_id`；executor/audit/result 传递绑定。
- `DiagnosisWorkspace`：承接控制工具，校验 grounding，分配 hypothesis/requirement/assessment ID。
- 确定性评估核心：requirement 覆盖、refute、单假设 qualifies、run 级确认条件、排序分。
- 新增稳定错误码：`HYPOTHESIS_NOT_GROUNDED`、`INVALID_BINDING`、`INVALID_ASSESSMENT`。
- 单元测试：账本、grounding、assessment 绑定、evaluator 判定、工具元数据。

## 3. Out of scope

- 代码流索引/工具（T2）。
- 只读验证 backend/DB 工具（T3）。
- runtime 主循环、prompt、repair、预算（T4）。
- remediation 生成、报告 schema 0.3（T5）。
- 三 case fixtures/eval（T6）。
- live 验证（T7）。
- catalog、skill、规则引擎。
- 真实 DB/MCP/OTel/SQLite。

## 4. 功能需求

| ID | 需求 | 优先级 |
|---|---|---|
| FR-T1-01 | 定义 EvidenceKind / EvidenceProvenance / Evidence 扩展字段 | must |
| FR-T1-02 | EvidenceLedger 是唯一证据创建入口，支持去重和 source_ref 查询 | must |
| FR-T1-03 | Hypothesis/EvidenceRequirement/EvidenceAssessment 模型，状态字段只能由 runtime 写 | must |
| FR-T1-04 | `diagnosis.propose_hypothesis` 校验 basis（evidence ID 或 source_ref）/requirements/falsifiers/limits，分配 ID | must |
| FR-T1-05 | 假设必须非空 basis，且至少一条 discriminating requirement | must |
| FR-T1-06 | `diagnosis.assess_evidence` 校验 hypothesis/requirement/evidence 三者绑定、source_ref 解析、kind 匹配与 verdict | must |
| FR-T1-07 | 工具调用元数据 `hypothesis_id`/`requirement_id` 必须成对、指向真实对象；未绑定证据不能覆盖 requirement | must |
| FR-T1-08 | 确定性 evaluator 计算覆盖、contradicted、qualifies、run 级 confirmed、排序分 | must |
| FR-T1-09 | 至少 2 个假设且替代假设全部 contradicted 才能 run 级 confirmed | must |
| FR-T1-10 | 拒绝未接地假设、非法 assessment、重复 assessment、越界/伪造 ID | must |
| FR-T1-11 | 假设/requirement 数量受预算限制（默认 6/5） | must |
| FR-T1-12 | 所有控制工具调用经过 ToolExecutor 审计 | must |
| FR-T1-13 | 当 run 上下文要求同线程日志上下文时，confirmed 需有已绑定并评估、且线程号匹配的 `log_thread_context` 证据 | must |

## 5. 接口/数据契约

完整语义见 [DESIGN §3–§6](../DESIGN.md)。本任务实现以下契约。

### 5.1 Evidence

```python
class EvidenceKind(StrEnum):
    LOG_EVENT = "log_event"
    LOG_THREAD_CONTEXT = "log_thread_context"
    STACK_FRAME = "stack_frame"
    SOURCE_CODE = "source_code"
    CALL_PATH = "call_path"
    SQL = "sql"
    ANNOTATION = "annotation"
    CONFIG = "config"
    DB_ROW = "db_row"
    DB_SCHEMA = "db_schema"

class EvidenceProvenance(StrEnum):
    LOG_PARSER = "log_parser"
    AST_INDEX = "ast_index"
    TOOL = "tool"
    FAKE_VERIFICATION = "fake_verification"
```

`Evidence` 新增：

| 字段 | 类型 | 规则 |
|---|---|---|
| `provenance` | EvidenceProvenance | 必填 |
| `tool_call_id` | str \| None | 工具证据非空 |
| `observed_at` | str | ISO-8601 UTC |
| `independence_group` | str \| None | 默认 `kind:source_ref` |
| `bound_hypothesis_id` | str \| None | 来自工具元数据 |
| `bound_requirement_id` | str \| None | 必须有 hypothesis |
| `content` | dict | 脱敏/截断后的结构化结果 |

- `supports` 字段在 v0.3 不再承载假设关联；关联由 `bound_*`、basis 和 assessment 决定。
- 旧测试如依赖 `supports` 需迁移，不允许同时保留两套语义。

### 5.2 EvidenceLedger

```python
class EvidenceLedger:
    def add(self, evidence: Evidence) -> Evidence: ...
    def get(self, evidence_id: str) -> Evidence | None: ...
    def all(self) -> list[Evidence]: ...
    def by_source_ref(self, source_ref: str) -> list[Evidence]: ...
    def by_requirement(self, hypothesis_id: str, requirement_id: str) -> list[Evidence]: ...
    def bind(
        self,
        evidence_id: str,
        hypothesis_id: str,
        requirement_id: str,
        tool_call_id: str | None = None,
    ) -> Evidence: ...
    def dedupe_key(self, kind: EvidenceKind, source_ref: str) -> str: ...
```

- 同一 `(kind, source_ref)` 重复 add 返回已有记录，不新增。
- `bind` 只能把未绑定证据升级为绑定；已绑定到同一对象幂等，绑定到不同对象拒绝（`INVALID_BINDING`）。
- 首次绑定时可写入 `tool_call_id`；已绑定证据再次绑定时不覆盖非空 `tool_call_id`。复用初始证据时不复制记录。
- `content` 超过输出上限时截断并记录标记；不能静默丢失。
- Ledger 不接受 LLM 提供的 evidence；控制工具无法直接调用 `add`。

### 5.3 Hypothesis 模型

```python
class EvidenceRequirement(BaseModel):
    requirement_id: str
    description: str
    evidence_kinds: list[EvidenceKind]
    discriminating: bool
    suggested_tools: list[str] = []

class Hypothesis(BaseModel):
    hypothesis_id: str
    statement: str
    cause_chain: list[str]
    basis_evidence_ids: list[str]
    requirements: list[EvidenceRequirement]
    falsifiers: list[str]
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    evidence_ids: list[str] = []
    assessment_ids: list[str] = []
    missing_requirement_ids: list[str] = []
    ranking_score: int = 0
    source: Literal["llm"] = "llm"
```

- runtime 负责填 `hypothesis_id` / `requirement_id` / status / evidence_ids / assessment_ids / missing / score。
- `basis_source_refs` 只出现在控制工具输入；Hypothesis 存储解析后的 `basis_evidence_ids`。
- 控制工具输入模型使用 `extra="forbid"`，不包含上述运行时字段。

### 5.4 `diagnosis.propose_hypothesis`

输入：

```json
{
  "statement": "...",
  "cause_chain": ["..."],
  "basis_evidence_ids": ["ev_0001", "ev_0002"],
  "basis_source_refs": ["repo://src/main/java/.../OrderService.java#L17-L27"],
  "requirements": [
    {
      "description": "...",
      "evidence_kinds": ["db_row"],
      "discriminating": true,
      "suggested_tools": ["db.get_row"]
    }
  ],
  "falsifiers": ["..."]
}
```

校验：

1. statement 非空、≤300 字；cause_chain 1–5 条。
2. basis 输入（`basis_evidence_ids` + `basis_source_refs`）合计 1–5 个；source_ref 必须能解析到 ledger 证据，可匹配多条并合并去重，解析后最多 10 条 ID。
3. requirements 1–5 条；每条 description 非空、evidence_kinds 非空；`suggested_tools` 只是建议，不校验 registry。
4. 至少一条 `discriminating=true`。
5. falsifiers 1–3 条，非空。
6. 当前假设数 < max_hypotheses。
7. 不允许额外字段/status。

返回：

```json
{
  "hypothesis_id": "hyp_001",
  "requirement_ids": ["hyp_001_req_01"],
  "status": "candidate"
}
```

失败返回 `HYPOTHESIS_NOT_GROUNDED`，消息包含具体原因。

### 5.5 `diagnosis.assess_evidence`

输入：

```json
{
  "assessments": [
    {
      "hypothesis_id": "hyp_001",
      "requirement_id": "hyp_001_req_01",
      "evidence_id": "ev_0012",
      "source_ref": null,
      "verdict": "supports",
      "rationale": "..."
    }
  ]
}
```

- `evidence_id` 与 `source_ref` 二选一。source_ref 必须在该 hypothesis+requirement 的已绑定证据中**唯一**匹配；零条或多条都拒绝。

校验：

1. 1–4 条；hypothesis/requirement 存在；evidence 由 `evidence_id` 或 `source_ref` 解析得到。
2. 解析后的 evidence 的 `bound_hypothesis_id`/`bound_requirement_id` 必须匹配，且 `kind` 属于 requirement 的 `evidence_kinds`。
3. verdict ∈ supports/refutes/neutral；rationale 非空、≤500 字。
4. 同一 `(hypothesis_id, requirement_id, 解析后 evidence_id)` 不得重复。
5. 不能引用 basis 证据来满足 requirement。

失败返回 `INVALID_ASSESSMENT`。

### 5.6 工具绑定元数据

`EvidenceToolMeta` 加到所有证据类工具参数：

```python
class EvidenceToolMeta(BaseModel):
    hypothesis_id: str | None = None
    requirement_id: str | None = None
```

- 成对出现；只给一个 → `INVALID_BINDING`。
- 指向不存在 hypothesis/requirement → `INVALID_BINDING`。
- executor 校验后，把绑定写入 `ToolResult` 和 `AuditEvent`；handler 不消费这两个字段。
- 未绑定工具结果仍可创建证据，但 `bound_*` 为空，只能作为 basis。

### 5.7 Evaluator 纯函数

```python
def evaluate_hypotheses(
    hypotheses: list[Hypothesis],
    evidence: list[Evidence],
    assessments: list[EvidenceAssessment],
    require_log_thread_context: bool = False,
    required_log_thread: str | None = None,
) -> EvaluationResult: ...
```

- 计算每个假设的 satisfied/missing requirements、status、score。
- `require_log_thread_context=True` 时，qualifying 假设必须至少有一条被评估为 `supports`、已绑定且满足 requirement 的 `log_thread_context` 证据；否则最多 `supported`，不能 `confirmed`。
- `required_log_thread` 非空时，上述上下文证据的 `content.thread`（或 source_ref 的 `thread=` 参数）必须与该值一致；两处都存在但不一致，或与要求不一致的上下文，不能计入确认门槛。
- run 级 confirmed 条件见 [DESIGN §6](../DESIGN.md)。
- 纯函数：不读时钟、不写事件、不调用 LLM；runtime 负责持久化/事件。
- `EvaluationResult` 包含 `top_hypothesis`、`run_confirmed`、`ambiguity` 和每个假设的变更摘要。

### 5.8 错误码

`ToolErrorCode` 新增：

```text
HYPOTHESIS_NOT_GROUNDED
INVALID_BINDING
INVALID_ASSESSMENT
```

- 错误消息必须可操作，例如：`basis evidence does not exist: ev_9999`。
- 错误计入审计；不产生证据。

## 6. 验收标准

| ID | 验收标准 | 验证方式 |
|---|---|---|
| AC-T1-01 | Evidence 扩展字段和枚举完整，Ledger 去重/检索/绑定升级正确 | `tests/unit/test_evidence_ledger.py` |
| AC-T1-02 | 无 basis / basis 不存在或 source_ref 无法解析 / 无 discriminating requirement 的假设被拒绝 | `test_hypothesis_protocol.py` |
| AC-T1-03 | 合法假设（ID 或 source_ref basis）获得 runtime ID 和 requirement IDs | 同上 |
| AC-T1-04 | assessment 引用未绑定/不存在证据、歧义 source_ref 或 kind 不匹配被拒绝 | 同上 |
| AC-T1-05 | 重复 assessment（含 source_ref 解析后重复）被拒绝 | 同上 |
| AC-T1-06 | 工具元数据成对校验，绑定写入 result/audit | `test_tool_binding.py` |
| AC-T1-07 | 单假设 qualifies 但替代未排除 → 不 confirmed | `test_grounded_evaluator.py` |
| AC-T1-08 | 全部 requirements 满足 + 替代 contradicted + 三类来源 → confirmed | 同上 |
| AC-T1-09 | refute 使假设 contradicted，且不能被后续 supports 覆盖 | 同上 |
| AC-T1-10 | ranking_score 确定性、可解释、无 LLM confidence | 同上 |
| AC-T1-11 | 假设/requirement 超限被拒绝 | `test_hypothesis_protocol.py` |
| AC-T1-12 | 控制工具调用进入执行器审计，不直接写 evidence | `test_tool_binding.py` |
| AC-T1-13 | `require_log_thread_context=true` 时，缺少已评估的 `log_thread_context` 不能 confirmed；指定 `required_log_thread` 时跨线程上下文不能计入；为 false 时不受影响 | `test_grounded_evaluator.py` |

## 7. 测试计划

### 单元

- `tests/unit/test_evidence_ledger.py`
  - 创建/检索/按 source_ref/按 requirement 查询。
  - 相同 (kind, source_ref) 去重。
  - bind 升级未绑定证据并写入 tool_call_id；重复绑定幂等且不覆盖 tool_call_id；不同 requirement 绑定拒绝。
  - 超长 content 截断标记。
- `tests/unit/test_hypothesis_protocol.py`
  - 合法假设（ID basis / source_ref basis）、无 basis、伪造 basis、无 discriminating、非法 evidence_kinds、超限。
  - source_ref 匹配多条时合并去重；匹配不到时拒绝。
  - 模型拒绝额外字段/status。
- `tests/unit/test_hypothesis_protocol.py`（assessment）
  - evidence_id 与 source_ref 二选一；source_ref 唯一解析；零条/多条拒绝。
  - 解析后重复 assessment 拒绝。
- `tests/unit/test_grounded_evaluator.py`
  - 全覆盖 + 单假设 + 无替代 → 不 confirmed。
  - 全覆盖 + 替代 contradicted + 三类来源 → confirmed。
  - 两个 qualifies → 都不 confirmed，报告歧义。
  - refute 后 supports 不覆盖。
  - `require_log_thread_context=true` 且无已评估上下文 → 不 confirmed；有上下文 → confirmed。
  - `required_log_thread=exec-7` 但唯一上下文属于另一线程 → 不 confirmed。
  - 排序分公式与同分排序。
- `tests/unit/test_tool_binding.py`
  - 元数据成对；非法 hypothesis/requirement。
  - ToolResult/AuditEvent 包含绑定。
  - 未绑定证据不能通过 assessment 满足 requirement。

### 集成（T1 范围内）

- 用 fake ledger/workspace 跑一个最小序列：初始证据 → 提出 2 个假设 → 绑定工具证据 → assessment → evaluator。
- 不依赖真实 LLM；使用直接 workspace 调用或 MockProvider 的简化脚本。

## 8. 风险与开放问题

| 风险 | 说明 | 缓解 |
|---|---|---|
| 模型绕过 grounding | 伪造/借用无关 evidence ID | 校验 evidence 存在且 requirement 绑定；负向测试 |
| 证据语义错配 | evidence 真实但被错误 assessment 为 supports | 报告展示 evidence + rationale；区分性 requirement；人工复核；T6 验收 |
| 动态 requirement 过弱 | 模型声明容易满足的要求 | 至少一条 discriminating；跨三类来源；负向测试 |
| 旧测试依赖 supports | v0.2 语义移除 | T4/T6 同步迁移；不保留双语义 |
| 控制工具绕过 executor | 直接调用 workspace | 控制工具注册进 registry，统一审计/预算 |
| 假设爆炸 | 模型不断提假设 | max_hypotheses=6；repair/停止 |

**开放问题**

- requirement 是否允许只有 `tool_result` 类泛化证据？v0.3 不允许；必须使用具体 kind。
- assessment 是否允许删除/撤回？v0.3 不提供撤回；refute 终止。
- basis 是否必须包含日志证据？不强制；但初始证据会提供日志/源码，确认门槛另有三类来源要求。

## 9. 验证命令

```bash
uv run pytest tests/unit/test_evidence_ledger.py tests/unit/test_hypothesis_protocol.py tests/unit/test_grounded_evaluator.py tests/unit/test_tool_binding.py -q
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
| 2026-10-22 | 创建 T1 spec：证据账本、假设/评估协议、绑定元数据、确定性 evaluator |
| 2026-10-22 | 增加同线程上下文 kind/确认门槛（含 required_log_thread）与绑定 tool_call_id 规则 |
