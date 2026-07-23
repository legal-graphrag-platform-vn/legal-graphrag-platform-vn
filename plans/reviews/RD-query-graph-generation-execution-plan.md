# Execution plan: Query-specific graph plan cho câu hỏi multi-hop

> **Ngày lập:** 2026-07-20
>
> **Trạng thái:** Accepted — Task 0 rerun đã pass; Task 1 được phép triển khai
> review, ontology v1.6.0 artifact rebuild còn mở
>
> **Technical design:** [RD-query-graph-generation.md](./RD-query-graph-generation.md)
>
> **Phạm vi:** Read path, retrieval, Neo4j execution, generation gate và evaluation
>
> **Không thuộc phạm vi:** sửa ontology, extraction pipeline, branching query,
> general LLM-generated Cypher và chứng minh legal entailment

---

## 1. Kết quả cần đạt

Sau khi hoàn tất plan này, một query multi-hop tuyến tính 2–3 bước phải đi qua
đúng chuỗi sau:

    User query
      -> deterministic routing
      -> LLM tạo UnlinkedSemanticPlan
      -> validate plan theo allowlist
      -> EntityLinker bind độc lập anchor và target vào canonical nodes
      -> Neo4j chạy exact ordered pattern giữa hai endpoint
      -> tạo PlanExecutionResult
      -> sufficiency kiểm satisfied-path membership
      -> compaction chỉ giữ evidence thuộc satisfied path
      -> answer generation hoặc fail-closed có reason code

Ví dụ acceptance xuyên suốt:

    Khoản 3 Điều 145
      -> REFERS_TO -> Khoản 2 Điều 145
      -> REFERS_TO -> Khoản 1 Điều 145

Hệ thống chỉ được gọi answer provider khi path thật đã thỏa plan và toàn bộ legal
unit cần trích dẫn còn tồn tại sau evidence projection.

---

## 2. Trạng thái code hiện tại

| Thành phần | Trạng thái | Vị trí hiện tại |
|---|---|---|
| Intent routing | Đã có, deterministic | src/retrieval/routing/router.py |
| Generic graph expansion | Đã có | src/retrieval/retriever/graph.py |
| Neo4j read repository | Đã có | src/infrastructure/neo4j/retriever_repo.py |
| GraphPath và requirement cũ | Đã có | src/retrieval/models.py |
| Temporal path validation | Đã có | src/retrieval/retriever/graph.py |
| Evidence/path validation | Đã có | src/generation/evidence_validation.py |
| Multi-hop sufficiency | Đã có nhưng chỉ kiểm minimum edge và unordered relation membership | src/generation/sufficiency.py |
| Evidence compaction | Đã có | src/generation/evidence_compaction.py |
| Answer grounding | Đã có | src/generation/grounding.py |
| Query-specific planner | Chưa có | — |
| Anchor binding | Chưa có retrieval-owned component | — |
| Exact ordered executor | Chưa có | — |
| Satisfied-path membership | Chưa có | — |

Lỗ hổng cần lấp không phải chỉ là gán thêm reasoning_requirement. Cần có trọn
chuỗi Planner → Linker → Exact Executor → Membership Gate.

---

## 3. Quyết định triển khai

### ED-1 — Giữ extraction và ontology nguyên trạng

- Không sửa plans/legal_ontology.md v1.6.0.
- Không import registry hoặc resolver nội bộ của extraction vào retrieval.
- Query planning chỉ dùng PHASE1_PERSISTED_LABELS, PHASE1_RELATION_ENUM và
  canonical active-voice directions.
- Runtime-only labels và legacy relation aliases bị reject.

### ED-2 — Tách package planning khỏi generic graph expansion

Tạo package mới:

    src/retrieval/planning/
      models.py
      patterns.py
      linker.py
      executor.py
      service.py

Generic GraphRetriever vẫn phục vụ các intent hiện tại. Planned multi-hop dùng
exact executor riêng; generic expansion không được coi là bằng chứng rằng plan
đã thỏa.

### ED-3 — Không gọi async tùy tiện trong sync retrieval runtime

Planner provider là async. Neo4j retrieval hiện là sync và backend đã chạy nó
trong BoundedRetrievalRunner.

Vì vậy RetrievalRuntime được tách thành:

    prepare(request) -> PreparedRetrievalRequest
    execute(prepared, unlinked_plan | None) -> RetrievalContext

Backend application service thực hiện:

    prepared = runtime.prepare(request)                 # pure, không I/O
    plan = await planner.plan(prepared)                 # async provider call
    context = await runner.run(
        lambda: runtime.execute(prepared, plan)         # sync Neo4j work
    )

Không dùng asyncio.run trong RetrievalRuntime. Không gọi sync Neo4j trực tiếp
trên FastAPI event loop. Method retrieve hiện tại được giữ làm convenience path
cho non-multi-hop; multi-hop không có plan vẫn fail-closed như hiện nay.

### ED-4 — Static query templates, không sinh Cypher từ LLM

- LLM chỉ sinh relation, direction và next_label trong enum đóng.
- Neo4j repository dùng template cố định cho depth 2 và 3.
- Bound anchor ID, bound target ID, filters và constraint values truyền bằng parameters.
- Python re-validates từng returned path theo plan.
- Không nối user text, node ID hoặc relation do LLM sinh trực tiếp vào Cypher.

### ED-5 — Path identity là topology identity

Di chuyển path identity về retrieval/shared boundary. Fingerprint chỉ gồm:

- canonical node IDs theo traversal order;
- relation type;
- canonical source_id và target_id.

Không dùng relation_id, citation evidence, confidence, model, created_at hoặc
mutable provenance. Generation import helper này thay vì tự tạo identity.

### ED-6 — V1 chỉ nhận exact-linear plan 2–3 bước

V1 không nhận:

- one-hop query;
- branching hoặc join;
- optional/gapped step;
- soft relation constraint;
- nhiều anchor;
- temporal hint do planner tự sinh;
- target predicates, arbitrary property expressions hoặc legal conditions;
- semantic relaxation khi không tìm thấy path.

Case multi_hop_05 trong dataset là branching one-hop và phải được báo
OUT_OF_SCOPE_PLAN_SHAPE, không được ép thành linear plan.

### ED-7 — Bind target độc lập trước exact execution (ADR-23)

Task 0 cho thấy `relation + direction + next_label` trả dư target ở
`multi_hop_01`, `multi_hop_03`, và `multi_hop_04`. V1 bổ sung một
`TargetMention` bắt buộc:

- planner chỉ sinh text của target; target label derive từ bước cuối;
- linker resolve anchor và target độc lập, không dùng path existence làm feature;
- `BoundSemanticPlan` chỉ tồn tại khi cả hai endpoint resolve duy nhất;
- executor bắt buộc path bắt đầu tại bound anchor và kết thúc tại bound target;
- nhiều topology giữa cùng endpoint trả `AMBIGUOUS_PATH`, không tự chọn shortest;
- candidate list là diagnostic của linker, không phải trusted execution input.

QG-0 dùng manually bound gold endpoints để cô lập executor. Semantic target
binding được calibration riêng trước QG-1 end-to-end.

---

## 4. Dependency graph

    S0 Graph/data preflight
      |
      v
    S1 Planning contracts + pattern validator
      |
      +----------------------+
      |                      |
      v                      v
    S2 Path identity       S3 Structural endpoint linker
      |                      |
      +----------+-----------+
                 v
             S4 Exact executor
                 |
                 v
             QG-0 Gold bound-endpoint gate
                 |
        pass ----+---- fail -> dừng, sửa data/design
                 |
                 v
             S5 Runtime/context integration
                 |
                 v
             S6 Generation membership gate
                 |
                 v
             S7 LLM planner provider
                 |
                 v
             S8 Semantic endpoint linker
                 |
                 v
             S9 Async application wiring
                 |
                 v
             S10 QG-1 + docs/full verification

Task 8 không được bắt đầu trước khi QG-0 pass. Nếu exact executor không chạy đúng
với plan viết tay hoàn hảo, thêm LLM chỉ làm failure khó chẩn đoán hơn.

---

## 5. Kế hoạch theo task

## Task 0 — Chạy graph viability và plan-expressivity preflight

**Mục tiêu:** chứng minh snapshot Neo4j hiện tại có dữ liệu multi-hop đủ để tiếp
tục và current plan shape đủ biểu diễn gold cases.

**Công việc:**

1. Ghi lại database identity, graph snapshot hash, ontology version và document
   scope.
2. Đếm path 2–3 bước theo ordered relation sequence trong allowlist.
3. Kiểm ba reviewed linear cases `multi_hop_01`, `multi_hop_02`,
   `multi_hop_04`; ghi rõ `multi_hop_03` là direct reference sau resolver v2.0.1.
4. Với mỗi gold case, đo:
   - gold path có tồn tại hay không;
   - relation+direction+label plan trả đúng một path hay trả dư path;
   - legal units trên path có đủ content và citation metadata hay không.
5. Xuất report read-only; không ghi hoặc sửa Neo4j.

**Acceptance criteria:**

- [ ] Report có snapshot identity và corpus scope, không dùng database không rõ nguồn.
- [x] Mỗi linear case `multi_hop_01`, `multi_hop_02`, `multi_hop_04` có kết quả
      path_exists, exact_denotation và citable_evidence_complete.
- [x] Case `multi_hop_03` được kiểm bằng direct atomic `REFERS_TO` và ghi rõ
      out of V1 exact-linear 2–3 bước.
- [ ] Case multi_hop_05 được ghi rõ out of V1 scope.
- [ ] Nếu pattern trả dư path, issue được ghi là PLAN_UNDERCONSTRAINED; không
      tự thêm heuristic để che lỗi.

**Stop condition:**

- Nếu gold path không tồn tại: dừng read-path implementation và mở task sửa graph.
- Nếu gold path tồn tại nhưng plan hiện tại không phân biệt được gold target:
  dừng trước Task 1 và amend technical design, ví dụ bổ sung target mention/binding
  hoặc thu hẹp V1 claim. Không được để answer LLM tự chọn target rồi gọi đó là
  exact plan execution.

**Artifacts:**

- results/retrieval/query_graph_preflight.json
- results/retrieval/query_graph_preflight.md

**Verification:**

- [ ] Query chỉ dùng MATCH/RETURN/SHOW/CALL read-only.
- [ ] Chạy lại cùng snapshot cho kết quả giống nhau.

**Dependencies:** Không.

**Estimated scope:** S — report và command/probe; chưa sửa production code.

### Task 0 initial execution result — 2026-07-22

Artifacts:

- `results/retrieval/query_graph_preflight.json`
- `results/retrieval/query_graph_preflight.md`

Result: **failed**.

- Gold paths tồn tại cho `multi_hop_01–04`.
- Shape cũ exact only cho `multi_hop_02`.
- `multi_hop_01`, `multi_hop_03`, `multi_hop_04` trả ba target Clause và được
  phân loại `PLAN_UNDERCONSTRAINED`.
- Cả bảy scoped `REFERS_TO` edges thiếu provenance bắt buộc của ontology v1.6.0.

Response:

1. ADR-23 bổ sung independent target binding.
2. Gold-bound read-only probe xác nhận amended plan contract có exact denotation
   ở 4/4 linear cases; đây chưa phải target-linker evaluation.
3. Rerun Task 0 sau artifact rebuild để xác nhận citable-evidence completeness.
4. Task 1 chỉ được mở khi rerun xác nhận exact denotation và
   citable-evidence completeness.

### Task 0 rerun result — 2026-07-23

Result: **passed**.

- Resolver v2.0.1 biểu diễn `multi_hop_03` bằng direct atomic
  `Clause -> REFERS_TO -> Clause`; reviewed dataset đã được cập nhật tương ứng.
- Ba exact-linear case còn thuộc V1 (`multi_hop_01`, `multi_hop_02`,
  `multi_hop_04`) đều trả đúng một gold-bound topology.
- Direct case `multi_hop_03` cũng trả đúng một topology; branching
  `multi_hop_05` tiếp tục out of V1 plan shape.
- 11/11 legal units trên scoped paths có content và temporal metadata.
- 377/377 `REFERS_TO` có common và method-specific provenance hợp lệ.
- Hai graph snapshot liên tiếp cùng projection SHA-256
  `294cf005d4d5926d5d09c9388236ff23d92cd6b845eeaef89a4d263f6280e291`.

Task 1 được phép bắt đầu; QG-0 vẫn là gate riêng sau khi exact executor được
triển khai.

---

## Task 1 — Đóng planning DTO và validation contract

**Mục tiêu:** tạo các immutable DTO và enum đóng trước khi viết linker/executor.

**Công việc:**

- Tạo UnlinkedSemanticPlan, AnchorMention, TargetMention,
  PathStepConstraint, BoundEndpoint, BoundSemanticPlan, PlanExecutionResult và
  PlanReasonCode.
- Enforce depth 2–3, positional label roles, relation allowlist, exact direction,
  non-empty normalized anchor/target mention và no runtime-only labels.
- Target label derive từ final `next_label`; không expose field lặp có thể lệch.
- BoundSemanticPlan chỉ nhận đúng một bound anchor và một bound target; label
  của bound target phải bằng final `next_label`.
- Enforce consistency invariant của PlanExecutionResult:

      satisfied
        iff reason_code == SATISFIED
        and satisfied_path_fingerprints không rỗng
        and derived_reasoning_requirement khác null

      failed
        implies satisfied_path_fingerprints rỗng
        and derived_reasoning_requirement là null

- Tạo validate_directed_step dựa trên shared ontology pattern, không gọi
  write-time validator yêu cầu provenance.

**Acceptance criteria:**

- [ ] Invalid relation, legacy alias, wrong direction, wrong positional label,
      depth 1/4, blank anchor và blank target đều bị reject bằng ValueError rõ nghĩa.
- [ ] DTO không có field cho node ID ở UnlinkedSemanticPlan.
- [ ] Bound target label khác final next_label bị reject.
- [ ] Candidate list không thể được truyền như trusted BoundSemanticPlan.
- [ ] Bound plan không tự được coi là trusted execution result.
- [ ] JSON schema provider chỉ expose query-plannable labels/relations.

**Files likely touched:**

- src/retrieval/planning/models.py
- src/retrieval/planning/patterns.py
- src/retrieval/planning/__init__.py
- src/retrieval/tests/test_query_plan_models.py
- src/retrieval/tests/test_query_plan_patterns.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_query_plan_models.py
- [ ] uv run pytest -q src/retrieval/tests/test_query_plan_patterns.py

**Dependencies:** ADR-23 accepted và Task 0 rerun pass trên artifacts ontology v1.6.0.

**Estimated scope:** M — 5 files.

---

## Task 2 — Chuẩn hóa topology path fingerprint

**Mục tiêu:** một path có đúng một identity dùng chung giữa retrieval và
generation, ổn định trước thay đổi mutable provenance.

**Công việc:**

- Tạo helper build_topology_path_fingerprint.
- Thay build_path_id hiện tại trong generation/evidence_validation.py.
- Giữ parallel REFERS_TO citations cho presentation nhưng collapse chúng về cùng
  topology fingerprint.
- Bổ sung regression test: thay relation_id, confidence, created_at hoặc citation
  text không đổi fingerprint; đổi node/direction/relation type phải đổi.

**Acceptance criteria:**

- [ ] Retrieval và generation dùng cùng helper.
- [ ] Không có implementation path identity thứ hai.
- [ ] Stable ordering không phụ thuộc set/dict iteration.

**Files likely touched:**

- src/retrieval/path_identity.py
- src/generation/evidence_validation.py
- src/retrieval/tests/test_path_identity.py
- src/generation/tests/test_evidence_compaction.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_path_identity.py
- [ ] uv run pytest -q src/generation/tests/test_evidence_compaction.py

**Dependencies:** Task 1.

**Estimated scope:** M — 4 files.

---

## Task 3 — Implement deterministic structural endpoint linker

**Mục tiêu:** bind structural anchor hoặc target như “Khoản 3 Điều 145” vào
canonical legal unit mà không dùng LLM-generated ID.

**Công việc:**

- Định nghĩa StructuralEndpointResolverPort ở retrieval boundary.
- Parse Document/Article/Clause/Point reference theo controlled grammar.
- Neo4j lookup theo document scope và canonical hierarchy.
- Trả candidate có typed resolution status; không trả top-1 nếu lookup không duy nhất.
- Stable ordering theo canonical node ID.
- Dùng cùng resolver contract cho vai trò anchor/target nhưng giữ reason code
  `UNBOUND_ANCHOR`/`AMBIGUOUS_ANCHOR` tách khỏi
  `UNBOUND_TARGET`/`AMBIGUOUS_TARGET`.

**Acceptance criteria:**

- [ ] Unique structural reference bind đúng canonical ID.
- [ ] Thiếu document scope hoặc nhiều match trả typed ambiguous code đúng endpoint role.
- [ ] Không có match trả typed unbound code đúng endpoint role.
- [ ] Không suy ID bằng string prefix và không import extraction registry.
- [ ] Lookup query parameterized và không ghi graph.

**Files likely touched:**

- src/retrieval/planning/linker.py
- src/retrieval/ports.py
- src/infrastructure/neo4j/retriever_repo.py
- src/retrieval/tests/test_structural_endpoint_linker.py
- src/retrieval/tests/test_repository.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_structural_endpoint_linker.py
- [ ] uv run pytest -q src/retrieval/tests/test_repository.py

**Dependencies:** Task 1.

**Estimated scope:** M — 5 files.

---

## Checkpoint A — Foundation

- [x] Task 0 preflight pass.
- [ ] DTO/schema tests pass.
- [ ] Path identity is topology-only.
- [ ] Structural anchors/targets resolve deterministically.
- [ ] Không có ontology hoặc write-path change.

Không bắt đầu exact executor nếu Checkpoint A chưa đạt.

---

## Task 4 — Implement exact ordered path executor

**Mục tiêu:** chạy BoundSemanticPlan bằng static Neo4j templates và chỉ trả path
khớp toàn bộ ordered constraints.

**Công việc:**

- Thêm PlannedPathExecutionPort.
- Tạo static query template riêng cho depth 2 và depth 3.
- Parameterize cả bound anchor ID và bound target ID; target mention text không
  được đưa vào Cypher.
- Enforce relation type, traversal direction và next_label theo từng vị trí.
- Reuse temporal validation hiện tại cho node và edge.
- Reject cycle, malformed edge, duplicate topology và path vượt budget.
- Deterministic sort theo depth, source ID, target ID, relation sequence và node IDs.
- Lift Article/Clause/Point evidence; semantic target chỉ pass khi có citable
  Article/Clause trên chính satisfied path.

**Acceptance criteria:**

- [ ] Executor không dùng generic any-order relation membership.
- [ ] Mọi returned path bắt đầu tại bound anchor và kết thúc tại bound target.
- [ ] Incoming traversal không đảo canonical source_id/target_id.
- [ ] Không có Cypher do LLM sinh.
- [ ] Same input/snapshot trả cùng ordered result.
- [ ] Empty result, temporal rejection, ambiguous result và truncation có reason
      code khác nhau.
- [ ] Executor không tìm evidence ngoài satisfied path để cứu plan.

**Files likely touched:**

- src/retrieval/planning/executor.py
- src/retrieval/ports.py
- src/infrastructure/neo4j/retriever_repo.py
- src/retrieval/tests/test_exact_path_executor.py
- src/retrieval/tests/test_repository.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_exact_path_executor.py
- [ ] uv run pytest -q src/retrieval/tests/test_repository.py
- [ ] Integration query xác nhận canonical edge direction trên Neo4j fixture.

**Dependencies:** Tasks 1–3.

**Estimated scope:** M — 5 files.

---

## Task 5 — QG-0: chạy manual gold plans

**Mục tiêu:** chứng minh executor đúng khi plan và hai bound endpoint đầu vào
hoàn hảo, trước khi thêm LLM planner hoặc semantic target linker.

**Công việc:**

- Viết manual BoundSemanticPlan fixture cho các executable linear case
  `multi_hop_01`, `multi_hop_02`, `multi_hop_04`, gồm gold anchor ID và gold
  target ID. `multi_hop_03` là direct reference nên không đưa vào QG-0 của
  exact-linear executor V1.
- Kiểm structural anchor resolver riêng, sau đó chạy exact executor bằng bound
  fixture; không dùng semantic target ranking trong gate này.
- So sánh source ID, ordered relation types và target ID với gold_paths.
- Ghi false-positive paths, failure reason và latency.

**Gate QG-0:**

- [ ] 100% executable linear gold cases có manual bound endpoints đúng contract.
- [ ] Structural anchor resolver bind đúng anchor ở 100% linear cases.
- [ ] 100% returned denotation khớp gold path; không chỉ “gold nằm trong top-k”.
- [ ] Không có legacy relation alias.
- [ ] Không path nào pass khi direction bị đảo.
- [ ] Case thiếu edge trả NO_PATH và không gọi bất kỳ answer provider nào.

**Stop condition:**

Nếu QG-0 fail, dừng. Phân loại lỗi vào một trong ba nhóm:

1. graph/data thiếu hoặc sai;
2. plan contract không đủ biểu đạt;
3. executor/structural-linker implementation sai.

Không bắt đầu Task 6 trở đi cho tới khi QG-0 pass.

**Files/artifacts likely touched:**

- configs/evaluation/query_graph_gold_plans.json
- src/retrieval/tests/test_query_graph_gold_plans.py
- results/retrieval/query_graph_qg0.json
- results/retrieval/query_graph_qg0.md

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_query_graph_gold_plans.py

**Dependencies:** Task 4.

**Estimated scope:** M — 4 files.

---

## Task 6 — Tích hợp PlanExecutionResult vào retrieval context

**Mục tiêu:** planned multi-hop có một authority result rõ ràng; requirement cũ
chỉ được derive từ execution result đã satisfied.

**Công việc:**

- Tách RetrievalRuntime thành prepare và execute, giữ retrieve convenience path.
- Planned path được chạy đúng một lần cho multi-hop.
- Thêm plan_execution vào internal RetrievalContext.
- Chỉ khi execution satisfied mới derive GraphReasoningRequirement.
- Generic graph_paths có thể tồn tại cho ranking/XAI nhưng không được đưa vào
  satisfied_path_fingerprints nếu không thỏa plan.
- Thêm metrics theo phase và reason code.

**Acceptance criteria:**

- [ ] Non-multi-hop behavior và retrieval-runtime-v2 contract không regression.
- [ ] Multi-hop thiếu plan tiếp tục trả MULTI_HOP_REQUIREMENT_UNRESOLVED.
- [ ] Failed plan không tạo reasoning_requirement.
- [ ] Satisfied result có fingerprint tồn tại trong context.graph_paths.
- [ ] Một request chỉ thực hiện một planned execution.

**Files likely touched:**

- src/retrieval/models.py
- src/retrieval/runtime/runtime.py
- src/retrieval/context/context_builder.py
- src/retrieval/tests/test_runtime_contract.py
- src/retrieval/tests/test_graph_and_hybrid.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_runtime_contract.py
- [ ] uv run pytest -q src/retrieval/tests/test_graph_and_hybrid.py

**Dependencies:** QG-0 pass.

**Estimated scope:** M — 5 files.

---

## Task 7 — Siết generation membership và atomic compaction

**Mục tiêu:** chỉ satisfied paths của query plan mới có thể mở generation gate
và đi vào projected context.

**Công việc:**

- Sufficiency kiểm path fingerprint membership trước minimum edge và compatibility.
- EvidenceValidator dùng shared topology fingerprint.
- EvidenceCompactor chỉ tạo multi-hop bundle từ satisfied paths.
- ProjectedContextValidator xác nhận projected path vẫn thuộc satisfied set.
- Answer provider không được gọi sau bất kỳ plan failure nào.

**Acceptance criteria:**

- [ ] Generic path cùng relation types nhưng khác anchor/target/order không mở gate.
- [ ] Path bị đổi direction không mở gate.
- [ ] Compaction không thay satisfied path bằng path ngắn hơn.
- [ ] Mất một citable intermediate làm projected validation fail.
- [ ] planner_provider_calls và answer_provider_calls_after_plan_failure là metric
      tách biệt; metric thứ hai luôn bằng 0.

**Files likely touched:**

- src/generation/sufficiency.py
- src/generation/evidence_compaction.py
- src/generation/projected_validation.py
- src/generation/tests/test_sufficiency.py
- src/generation/tests/test_evidence_compaction.py

**Verification:**

- [ ] uv run pytest -q src/generation/tests/test_sufficiency.py
- [ ] uv run pytest -q src/generation/tests/test_evidence_compaction.py
- [ ] uv run pytest -q src/generation/tests/test_grounding_and_service.py

**Dependencies:** Tasks 2 và 6.

**Estimated scope:** M — 5 files.

---

## Checkpoint B — Deterministic end-to-end path

Tại checkpoint này chưa có LLM planner. Dùng manual gold plan:

- [ ] Query multi_hop_02 chạy từ bind đến RetrievalContext.
- [ ] Sufficiency pass đúng satisfied path.
- [ ] Context projection giữ đủ ba legal units.
- [ ] Answer provider chỉ nhận evidence trên satisfied path.
- [ ] Wrong-order/unrelated path bị reject.
- [ ] Toàn bộ fast retrieval + generation tests pass.

Nếu Checkpoint B chưa pass thì không tích hợp provider.

---

## Task 8 — Implement async LLM query planner provider

**Mục tiêu:** chuyển query multi-hop thành UnlinkedSemanticPlan đúng strict schema,
gồm anchor mention, target mention và ordered steps; không sinh ID hoặc Cypher.

**Công việc:**

- Định nghĩa QueryPlannerPort async.
- Tạo prompt chỉ expose allowlisted labels, relations và directions; target chỉ
  có normalized mention text, label derive từ final step.
- Gemini adapter dùng structured output, timeout, bounded concurrency và retry
  policy giống answer provider nhưng config riêng.
- Validate response bằng DTO contract; malformed/empty payload fail typed.
- Không log full prompt, API key hoặc provider raw payload.

**Acceptance criteria:**

- [ ] Provider output không thể chứa node_id hoặc Cypher.
- [ ] Missing/blank target mention là typed invalid-plan failure.
- [ ] Timeout, cancellation, closed provider, malformed JSON và unsupported enum
      có typed failure.
- [ ] Same valid payload tạo cùng plan fingerprint.
- [ ] Unit tests không gọi provider thật.
- [ ] Online provider test có marker riêng.

**Files likely touched:**

- src/retrieval/planning/ports.py
- src/retrieval/planning/prompts.py
- src/infrastructure/llm/gemini_query_planner.py
- src/retrieval/tests/test_query_planner_contract.py
- tests/provider/test_query_planner_online.py

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_query_planner_contract.py
- [ ] Online marker chỉ chạy khi có explicit opt-in.

**Dependencies:** Checkpoint B pass.

**Estimated scope:** M — 5 files.

---

## Task 9 — Thêm semantic endpoint linking và calibration

**Mục tiêu:** hỗ trợ semantic anchor/target khi structural parser không áp dụng,
đặc biệt target mô tả bằng nội dung như “trình tự chào bán phần vốn góp”, nhưng
vẫn fail-closed khi kết quả mơ hồ.

**Công việc:**

- Reuse vector + full-text retrieval ports, không tạo index/model contract mới.
- Fuse candidate deterministically.
- Chốt top-score threshold, margin và candidate budget riêng cho anchor và target
  bằng calibration set.
- Không dùng “có path” làm ground truth cho anchor correctness.
- Không dùng “có path tới bound anchor/target” làm ranking feature hoặc tie-break.
- Structural resolver luôn được ưu tiên khi mention là structural reference.

**Acceptance criteria:**

- [ ] Candidate ordering deterministic khi score bằng nhau.
- [ ] Dưới threshold trả typed `UNBOUND_ANCHOR` hoặc `UNBOUND_TARGET` theo role.
- [ ] Không đủ margin trả typed `AMBIGUOUS_ANCHOR` hoặc `AMBIGUOUS_TARGET`.
- [ ] Threshold được lưu trong config và có calibration evidence; không dùng magic number.
- [ ] Anchor accuracy, target accuracy và path execution accuracy được báo riêng.

**Files likely touched:**

- src/retrieval/planning/linker.py
- src/retrieval/config.py
- src/retrieval/tests/test_semantic_endpoint_linker.py
- configs/evaluation/query_graph_linker_calibration.json
- results/retrieval/query_graph_linker_calibration.md

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_semantic_endpoint_linker.py
- [ ] Re-run calibration tạo cùng threshold trên cùng artifact.

**Dependencies:** Tasks 3 và 8.

**Estimated scope:** M — 5 files.

---

## Task 10 — Wire async planner vào backend và lifecycle

**Mục tiêu:** backend gọi planner async rồi chuyển Neo4j work vào bounded sync
runner, không block event loop và không leak provider.

**Công việc:**

- Mở rộng SyncRetrievalRuntime port với prepare/execute.
- GraphRAGRetrievalService điều phối planner cho MULTI_HOP.
- Thêm QUERY_PLANNING_ENABLED và planner provider/model/timeout/concurrency/retry
  settings riêng.
- Container tạo planner khi profile bật và đóng planner khi shutdown.
- Startup failure rollback đóng planner, document service, runner và runtime đúng ownership.
- Retrieval-only profile không load planner dependency khi planning disabled.

**Acceptance criteria:**

- [ ] Planner async chạy trên event loop; Neo4j execution chạy trong retrieval worker.
- [ ] Không asyncio.run, per-request executor hoặc blocking retrieval trên event loop.
- [ ] Timeout/cancellation không retry request hoặc gọi answer provider.
- [ ] Shutdown idempotent và partial startup failure cleanup đủ resource.
- [ ] Mock mode không cần planner/Neo4j/provider.

**Files likely touched:**

- apps/backend/services/interfaces.py
- apps/backend/services/graphrag_retrieval_service.py
- apps/backend/settings.py
- apps/backend/container.py
- apps/backend/tests/test_graphrag_retrieval_service.py

Lifecycle tests bổ sung ở task kế tiếp nếu vượt giới hạn 5 file.

**Verification:**

- [ ] uv run pytest -q apps/backend/tests/test_graphrag_retrieval_service.py
- [ ] uv run pytest -q apps/backend/tests/test_backend_lifecycle.py
- [ ] uv run pytest -q apps/backend/tests/test_retrieval_runner.py

**Dependencies:** Tasks 6, 8 và 9.

**Estimated scope:** M — 5 files.

---

## Task 11 — Bổ sung lifecycle, error mapping và API regression tests

**Mục tiêu:** đóng failure paths tại backend boundary mà không đổi API thành
silent empty result.

**Công việc:**

- Map planner timeout/dependency/output failures sang typed backend errors.
- Multi-hop plan failure trả cannot-answer hoặc typed retrieval outcome theo
  contract hiện hành; không trả factual fallback.
- Bổ sung tests cho concurrent requests, cancellation, startup rollback và close.
- Xác nhận query/chat endpoints không lộ stack trace, provider payload hoặc secret.

**Acceptance criteria:**

- [ ] Unsupported capability khác no-results và khác plan-failed.
- [ ] Chat SSE không phát token trước khi full answer candidate được validate.
- [ ] Plan failure tạo zero answer-provider calls.
- [ ] Concurrent requests không dùng chung mutable plan/request state.
- [ ] Existing factual, definition, hierarchy, validity và comparison API tests pass.

**Files likely touched:**

- apps/backend/services/errors.py
- apps/backend/api/error_handlers.py
- apps/backend/tests/test_backend_lifecycle.py
- apps/backend/tests/test_query_error_contract.py
- apps/backend/tests/test_graphrag_answer_service.py

**Verification:**

- [ ] uv run pytest -q apps/backend/tests/test_backend_lifecycle.py
- [ ] uv run pytest -q apps/backend/tests/test_query_error_contract.py
- [ ] uv run pytest -q apps/backend/tests/test_graphrag_answer_service.py

**Dependencies:** Task 10.

**Estimated scope:** M — 5 files.

---

## Checkpoint C — Provider và backend integration

- [ ] Planner timeout, cancellation và malformed output đều fail typed.
- [ ] Neo4j execution không chạy trên FastAPI event loop.
- [ ] Plan failure tạo zero answer-provider calls.
- [ ] Startup rollback và shutdown đóng đủ planner, runner và runtime.
- [ ] Mock mode cùng các non-multi-hop endpoints không regression.
- [ ] Provider-online tests vẫn là explicit opt-in.

Không chạy QG-1 nếu Checkpoint C chưa đạt.

---

## Task 12 — QG-1 planner evaluation và baseline comparison

**Mục tiêu:** đo riêng planner correctness, linker correctness, executor correctness
và end-to-end retrieval; không gom thành một con số dễ che lỗi.

**Profiles bắt buộc:**

1. generic retrieval hiện tại;
2. deterministic/rule-based planner baseline;
3. gold manual planner upper bound;
4. LLM planner.

**Metrics bắt buộc:**

- plan schema-valid rate;
- exact relation/direction/label sequence match;
- anchor binding accuracy;
- target binding accuracy;
- exact path denotation accuracy;
- extra-path rate;
- NO_PATH và AMBIGUOUS_PATH rate;
- graph path hit rate;
- answer-provider calls after plan failure;
- planner latency p50/p95;
- total retrieval latency p50/p95.

**Acceptance criteria:**

- [ ] Thresholds được preregister trước khi chạy test fold.
- [ ] Gold executor được báo là upper bound, không phải baseline cạnh tranh.
- [ ] Wrong-but-valid plan được tính là sai dù executor chạy thành công.
- [ ] Kết quả ghi dataset hash, graph snapshot hash, model và prompt fingerprint.
- [ ] Development evidence không được gắn nhãn official khi M3-B13/artifact rebuild
      còn mở.

**Corpus gate:**

Current reviewed multi-hop cases tập trung ở một document. Leave-one-document-out
chỉ hợp lệ sau khi corpus tối thiểu 4 văn bản và artifacts ontology v1.6.0 được
rebuild. Trước đó chỉ được báo development case study, không claim generalization.

**Files likely touched:**

- src/retrieval/eval/query_planning.py
- src/retrieval/tests/test_query_planning_evaluation.py
- configs/evaluation/query_graph_generation_thresholds.json
- results/retrieval/query_graph_qg1.json
- results/retrieval/query_graph_qg1.md

**Verification:**

- [ ] uv run pytest -q src/retrieval/tests/test_query_planning_evaluation.py
- [ ] Re-run cùng snapshot/model/prompt cho artifact metadata giống nhau.

**Dependencies:** Tasks 10–11.

**Estimated scope:** M — 5 files.

---

## Task 13 — Đồng bộ docs và full verification

**Mục tiêu:** bảo đảm implementation, docs, config, tests và runtime behavior nói
cùng một contract.

**Docs cần cập nhật:**

- plans/05_graphrag_retrieval.md
- plans/reviews/RD-query-graph-generation.md
- apps/backend/README.md
- apps/backend/.env.example
- plans/results liên quan nếu QG-1 tạo claim mới

**Acceptance criteria:**

- [ ] Technical design phản ánh orchestration prepare/async plan/sync execute.
- [ ] Reason code table khớp closed enum trong code.
- [ ] Config docs có default, range và enable/disable semantics.
- [ ] Không mô tả multi-hop là supported nếu planner profile đang disabled.
- [ ] Không thay đổi ontology v1.6.0 hoặc extraction contract.

**Verification commands:**

    uv run pytest -q src/retrieval/tests
    uv run pytest -q src/generation/tests
    uv run pytest -q apps/backend/tests
    uv run pytest -q
    uv run ruff check <all changed Python files>
    uv run ruff format --check <all changed Python files>
    git diff --check

Nếu có Neo4j integration environment:

    uv run pytest -q tests/integration/test_retrieval_online.py

Provider-online tests chỉ chạy bằng marker/explicit opt-in; không nằm trong fast
suite mặc định.

**Dependencies:** Task 12.

**Estimated scope:** S cho docs; verification có thể dài nhưng không thêm behavior.

---

## 6. Test matrix tổng

### Happy paths

- Structural anchor duy nhất, linear depth 2.
- Structural anchor duy nhất, linear depth 3.
- Semantic target duy nhất sau calibrated threshold/margin.
- Incoming và outgoing step đúng canonical direction.
- Direct-citable target Article/Clause/Point.
- Semantic target có citable Article/Clause trên chính path.
- Temporal query tại effective_from boundary.

### Boundary cases

- Depth đúng min 2 và max 3.
- Một candidate, nhiều candidate và candidate list rỗng.
- Hai path có cùng topology nhưng khác REFERS_TO provenance.
- Equal-score linker candidates có stable canonical-ID tie order nhưng vẫn
  ambiguous nếu không đủ margin.
- Path budget đúng limit và vượt limit.
- effective_to là exclusive boundary.

### Invalid inputs

- Blank anchor.
- Blank target mention.
- Depth 1 hoặc 4.
- Legacy alias REFERENCES/AMENDED_BY.
- Runtime-only label.
- Direction không hợp lệ.
- Intermediate/final label sai vai trò.
- Planner payload có node_id hoặc field ngoài schema.
- Malformed Neo4j path, duplicate edge ID hoặc non-adjacent edge.

### Failure paths

- Planner timeout, cancellation, malformed/empty output.
- Planner provider/auth/model unavailable.
- Neo4j unavailable.
- Anchor unresolved hoặc ambiguous.
- Target unresolved hoặc ambiguous.
- No exact path.
- More than one exact denotation khi contract yêu cầu unique.
- Temporal rejection.
- Evidence unliftable.
- Context budget làm mất mandatory path evidence.
- Startup partial failure và shutdown grace expiry.

### Security và integrity

- Không nối user/LLM text vào Cypher.
- Không log secrets, embeddings hoặc raw provider payload.
- Read-only planned query không thay graph.
- Không dùng LLM-generated canonical ID.
- Không generic path nào được thay thế satisfied path.

### Determinism

- Same query/plan/snapshot cho cùng fingerprints và ordering.
- Mutable provenance không đổi topology fingerprint.
- Tie-break không phụ thuộc dict/set iteration.
- Một request không chạy planned executor nhiều hơn một lần.

---

## 7. Reason code tối thiểu

Closed enum cần cover tối thiểu:

| Code | Ý nghĩa |
|---|---|
| SATISFIED | Có ít nhất một path thỏa plan và evidence contract |
| INVALID_PLAN | DTO/pattern không hợp lệ |
| OUT_OF_SCOPE_PLAN_SHAPE | One-hop, branching hoặc shape ngoài V1 |
| PLANNER_UNAVAILABLE | Provider/config/dependency lỗi |
| PLANNER_TIMEOUT | Planner quá thời gian |
| UNBOUND_ANCHOR | Không resolve được anchor |
| AMBIGUOUS_ANCHOR | Anchor có nhiều candidate không đủ margin |
| UNBOUND_TARGET | Không resolve được target |
| AMBIGUOUS_TARGET | Target có nhiều candidate không đủ margin |
| NO_PATH | Anchor đúng nhưng không có exact path |
| AMBIGUOUS_PATH | Plan trả nhiều denotation không thể chọn deterministic |
| PATH_BUDGET_EXCEEDED | Kết quả bị truncate trước khi chứng minh đủ |
| TEMPORAL_REJECTED | Path tồn tại nhưng không hợp lệ tại query date |
| EVIDENCE_UNLIFTABLE | Path tới semantic target nhưng không có citable support |

Message hiển thị cho người dùng tách khỏi code. Không dùng free-form reason làm
logic branch.

---

## 8. Rollout

### Stage 1 — Dark mode

- Planner chạy và ghi metrics nhưng không thay context/generation.
- So sánh plan/path với generic retrieval.
- Không gửi planner raw payload vào log.

### Stage 2 — Evaluation-only

- Bật planned retrieval trong QG-1 runner.
- Không expose production claim.
- Review false positive và ambiguous cases.

### Stage 3 — Backend feature flag

- Bật QUERY_PLANNING_ENABLED cho development environment.
- Chỉ áp dụng intent MULTI_HOP.
- Các intent khác giữ nguyên đường chạy.

### Stage 4 — Default-on sau acceptance

Chỉ bật mặc định khi:

- QG-0 pass;
- QG-1 đạt preregistered thresholds;
- zero answer-provider calls after plan failure;
- backend lifecycle/concurrency tests pass;
- graph/corpus artifact đủ điều kiện cho claim tương ứng.

### Rollback

Tắt QUERY_PLANNING_ENABLED. Runtime quay về behavior cũ: multi-hop thiếu trusted
requirement và fail-closed. Không cần migration hoặc rollback Neo4j vì giải pháp
không ghi graph và không thay schema.

---

## 9. Rủi ro và giảm thiểu

| Rủi ro | Impact | Giảm thiểu |
|---|---|---|
| Graph thiếu relation | Cao | Task 0 preflight; dừng read-path work |
| Plan relation+label trả dư target | Cao | Exact-denotation check; amend design trước Task 1 |
| EntityLinker bind sai anchor/target | Cao | Independent binding, structural-first, calibrated margin, đo riêng |
| LLM sinh valid nhưng sai ý query | Cao | Gold comparison, wrong-but-valid metric |
| Generic path mở gate | Cao | Fingerprint membership trước compatibility checks |
| Async planner làm rối sync runtime | Cao | prepare/execute split; application coordinator |
| Dynamic Cypher injection | Cao | Static depth templates và allowlist |
| Context compaction làm mất path | Cao | Atomic bundle + projected membership validation |
| Corpus một document làm metric đẹp giả | Cao | Giới hạn claim; chờ 4-document gate |
| Planner tăng latency/cost | Trung bình | Dark mode metrics, timeout, bounded concurrency |

---

## 10. Definition of Done

Feature chỉ được coi là hoàn tất khi:

- [ ] Task 0 và QG-0 pass trên pinned graph snapshot.
- [ ] Tất cả DTO invariants có unit tests.
- [ ] Entity linking và exact path execution có contract/integration evidence.
- [ ] Anchor binding và target binding có metric/evidence tách biệt.
- [ ] Generation chỉ admit satisfied path.
- [ ] Answer provider call count sau plan failure bằng 0.
- [ ] Non-multi-hop regression suite pass.
- [ ] Backend timeout, cancellation, concurrency và lifecycle tests pass.
- [ ] QG-1 report có dataset/model/prompt/snapshot fingerprints.
- [ ] Docs/config/runtime cùng một contract.
- [ ] Full pytest, Ruff và git diff checks pass.
- [ ] Remaining corpus/artifact limitation được ghi rõ, không claim quá evidence.

---

## 11. Các mục cố ý hoãn

- Branching/join query, gồm multi_hop_05.
- Plan có nhiều anchor hoặc nhiều target.
- Interactive clarification.
- Soft constraints và automatic relaxation.
- General LLM-generated Cypher.
- Temporal source thứ hai do planner sinh.
- Version-family migration.
- Persist runtime reasoning nodes.
- Legal entailment verification.

Các mục trên cần technical design riêng; không được lén đưa vào implementation V1.
