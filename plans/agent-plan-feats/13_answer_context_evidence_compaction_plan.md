# Answer Context Evidence Compaction and Projection Plan

> **Purpose**: replace the current greedy context projection with a deterministic,
> intent-aware, fail-closed evidence selection pipeline. This plan extends the
> Answer Generation contract in Plan 11. It does not change retrieval ranking,
> the configured answer provider/model, or milestone status.

## 0. Mandatory Status

```text
Gate 7: OPEN
M3-B13: OPEN
Milestone A: NOT PASSED
Answer generation runtime: IMPLEMENTED
Context evidence compaction migration: IMPLEMENTED, VERIFIED
Official answer evaluation: NOT STARTED
```

This migration must not mark Gate 7, Milestone A, or Milestone B as passed.

## 1. Objective

Implement one canonical context-building path:

```text
RetrievalContext
-> Retrieval Outcome Gate
-> Evidence Eligibility Validation
-> Structural Grouping
-> Deduplication
-> Mandatory Bundle Resolution
-> Budget Planning
-> Atomic Mandatory Bundle Admission
-> Optional Evidence Filling
-> ProjectedContext Construction
-> Post-projection Sufficiency
-> Evidence Registry Construction
-> Prompt Construction
-> Provider
-> Structured Output Validation
-> Grounding Validation
```

The migration must guarantee:

1. Mandatory evidence is admitted as a complete bundle or not admitted at all.
2. Evidence omitted from `ProjectedContext` cannot appear in the citation registry.
3. Provider execution occurs only after post-projection sufficiency passes.
4. Selection and ordering are deterministic for unchanged input and config.
5. Malformed evidence is reported as a typed contract failure, never silently
   discarded.

## 2. Current Implementation and Gaps

Current source boundary:

```text
src/generation/service.py
src/generation/sufficiency.py
src/generation/context_projection.py
src/generation/models.py
src/generation/grounding.py
src/generation/config.py
src/application/answer_factory.py
```

Current projection behavior is a greedy ranked-prefix loop:

```python
for unit in context.retrieved_units:
    if len(unit.content_raw) > remaining:
        truncated = True
        break
    evidence.append(unit)
```

Known gaps:

- One oversized unit stops consideration of all lower-ranked units.
- Evidence sufficiency is checked before projection but not after projection.
- Article/Clause/Point overlap can consume budget with duplicate legal content.
- Selection is not intent-aware.
- Graph-path evidence is projected independently from evidence budget admission.
- Citation allowlisting is implicit instead of being represented by a dedicated
  immutable registry.
- Empty projection raises `AnswerRequestError`, which is incorrectly treated as
  an invalid user request instead of deterministic insufficient evidence.
- `truncated: bool` does not explain which units were omitted and why.

## 3. Ownership and Dependency Contract

### 3.1 Answer service and generation service

The existing two-layer boundary remains explicit:

```text
GraphRAGAnswerService
-> calls RetrievalApplicationPort
-> propagates typed unsupported/dependency/execution failures
-> passes a successfully created RetrievalContext to AnswerGenerator

AnswerGenerator
-> evaluates supported/no_results RetrievalContext outcome
-> owns evidence validation, compaction, projection and provider orchestration
```

`RetrievalContext.capability_status` currently contains only `supported` or
`no_results`. Unsupported capability and retrieval failures are raised before a
context is returned; the plan must not invent an unsupported RetrievalContext
state merely to simplify orchestration.

`AnswerGenerator` responsibilities:

```text
1. Inspect supported/no-results RetrievalContext outcome.
2. Stop for no-results.
3. Invoke evidence validation only for a supported context.
4. Run compaction and projection.
5. Stop when mandatory admission or post-projection sufficiency fails.
6. Call the provider only after all pre-provider gates pass.
7. Invoke existing grounding validation on provider output.
```

Neither service may implement grouping, deduplication, or budget arithmetic
inline.

### 3.2 Four implementation responsibilities

```text
EvidenceValidator
- retrieval-evidence contract and eligibility validation

EvidenceCompactor
- structural grouping
- hierarchy-aware deduplication
- mandatory bundle resolution

ContextProjector
- budget planning
- atomic mandatory admission
- optional evidence filling
- ProjectedContext construction
- Evidence Registry and provider request construction

ProjectedContextValidator
- final intent-specific sufficiency validation
```

These names describe responsibilities, not a requirement to create one class per
small operation. Helper functions may remain module-private when a class would
add no useful contract.

### 3.3 Dependency direction

```text
generation service
-> generation validation/compaction/projection abstractions

generation modules
-> retrieval DTOs and generation DTOs only

LLM infrastructure
-> provider port and provider request DTO only
```

Context selection must not import Neo4j infrastructure, backend routes, Gemini
SDK types, or retrieval channel implementations.

## 4. Retrieval Outcome Gate

The answer boundary evaluates retrieval outcome before evidence processing.

| Retrieval outcome | Owner and behavior |
|---|---|
| `supported` context | `AnswerGenerator` continues to `EvidenceValidator` |
| `no_results` context | `AnswerGenerator` returns deterministic `cannot_answer`; provider call count is zero |
| unsupported capability exception | `GraphRAGAnswerService` propagates typed unsupported failure; generator/provider call count is zero |
| retrieval dependency/execution exception | `GraphRAGAnswerService` propagates typed failure; generator/provider call count is zero |

`EvidenceValidator` may defensively reject a non-supported context, but it does
not own either service-level stop decision.

## 5. Evidence Eligibility Validation

`EvidenceValidator` validates every candidate that may enter compaction.

Required checks:

```text
- canonical non-empty unit ID
- supported unit label: Article, Clause, Point
- non-empty content_raw after whitespace normalization
- document_id present
- article_id/clause_id consistent with label when required
- citation_label present
- deep_link present or deterministically derivable by the existing trusted mapper
- unit metadata is consistent with the document/temporal filters recorded as
  already applied by retrieval
- temporal metadata is parseable when temporal evidence is required
- graph paths have valid shape
```

Graph-path shape invariants:

```text
len(nodes) == len(edges) + 1
all node and relation IDs are non-empty
every edge preserves canonical source_id/target_id
every edge connects adjacent traversal nodes
```

Malformed candidate behavior:

```text
raise typed EvidenceContractError
do not silently drop
do not replace with fake content
do not call provider
```

An eligible but low-ranked unit is not malformed. Eligibility validation must
not rerank candidates.

Generation does not execute document or temporal filtering again. It only
cross-checks trusted unit metadata against `filters_applied` and the resolved
temporal context to detect contract drift. Retrieval remains the sole owner of
filter semantics and candidate inclusion.

## 6. Structural Grouping

Group candidates by legal basis and hierarchy rather than treating every unit as
independent.

Canonical structure:

```text
Document
-> Article
-> Clause
-> Point
```

Recommended internal DTO:

```python
class EvidenceGroup(BaseModel):
    group_id: str
    document_id: str
    article_id: str
    clause_id: str | None
    members: tuple[EvidenceCandidate, ...]
    best_rank: int
```

Grouping rules:

- Article and its Clause/Point descendants are related but remain separately
  attributable units.
- A Point keeps its Point ID and provenance even when parent context is added.
- Cross-document/version evidence must never be placed in the same group merely
  because normalized text matches.
- Group order is deterministic by `best_rank`, then `group_id`.

## 7. Deduplication Contract

Deduplication removes redundant prompt content, not legal provenance.

Rules:

```text
1. Prefer the smallest unit that still contains enough legal meaning.
2. Do not hard-code Point > Clause > Article without a completeness check.
3. A Point may require its parent Clause/Article title as contextual framing.
4. If a Clause is selected, do not include identical Clause text again through
   its parent Article content.
5. Exact normalized-content duplicates use rank, specificity, then canonical ID
   as deterministic tie-breaks.
6. Distinct versions/documents are never deduplicated across version boundaries.
```

Deduplication output must retain a record of omitted units:

```python
class OmittedEvidence(BaseModel):
    unit_id: str
    reason: Literal[
        "hierarchical_duplicate",
        "content_duplicate",
        "context_budget_exceeded",
        "superseded_by_more_specific_unit",
    ]
    retained_unit_id: str | None = None
```

## 8. Mandatory Bundle Resolution

A mandatory bundle is the smallest complete set of legal units, paths, and
metadata required to support an intent.

Recommended DTO:

```python
class EvidenceBundle(BaseModel):
    bundle_id: str
    intent: IntentType
    unit_ids: tuple[str, ...]
    path_ids: tuple[str, ...] = ()
    temporal_subject_ids: tuple[str, ...] = ()
    version_keys: tuple[str, ...] = ()
    source_rank: int
```

Bundle IDs must be deterministic hashes of the stable bundle projection.

### 8.1 Factual

```text
At least one direct sufficient Article/Clause/Point evidence unit
+ its trusted citation metadata
```

### 8.2 Definition

```text
Unit containing the defining text
+ requested concept/term context when available
```

### 8.3 Hierarchy

```text
requested parent unit
+ requested child unit
+ verified CONTAINS path
```

Point endpoints remain attributable as Points. Parent context may be projected
without replacing the Point identity.

### 8.4 Multi-hop

```text
source legal unit
+ all required intermediate legal units
+ target legal unit
+ complete verified graph path
```

Generation must not infer a hop requirement from query text. Retrieval context
now supports a trusted `GraphReasoningRequirement` with explicit hop/branching
requirements. The ordinary router and public `force_intent` path do not create
that trusted requirement, so multi-hop answer generation remains fail-closed by
default rather than claiming unverified multi-edge reasoning.

The compactor still enforces atomic path projection: if a selected path is
`A -> B -> C`, all available legal-unit nodes `A`, `B`, `C` and the complete path
metadata must remain together.

### 8.5 Validity

```text
subject unit/document
+ resolved query date
+ effective_from/effective_to/legal_status metadata
+ legal-basis unit when supplied by retrieval
```

### 8.6 Comparison

```text
at least one complete evidence group for each required version
+ stable version identity
```

Bundle resolution may produce multiple complete bundles because comparison,
branching paths, or several independently required legal obligations can require
more than one bundle. It may also produce alternative complete bundle sets. It
must not produce an incomplete bundle as a fallback.

## 9. Budget Planning

### 9.1 V1 budget unit

This migration keeps the existing deterministic character budget to avoid a
provider/network call during context construction:

```text
ANSWER_CONTEXT_MAX_CHARS
```

The plan must not claim character count is an exact model token count.
Provider-specific local token estimation is deferred until it can be introduced
without making context selection depend on a remote provider call.

### 9.2 Budget contents

Budget planning must account for:

```text
fixed system instruction
output contract/schema text
query and routing metadata
temporal metadata
graph path metadata
serialized evidence blocks
safety reserve
```

Recommended immutable result:

```python
class ContextBudgetPlan(BaseModel):
    total_chars: int
    fixed_overhead_chars: int
    evidence_budget_chars: int
    safety_reserve_chars: int
```

If fixed overhead consumes the configured budget, fail with a typed internal
configuration error before provider execution.

## 10. Atomic Mandatory Bundle Admission

Mandatory bundle admission is all-or-nothing for each bundle and for the chosen
required bundle set.

Rules:

```text
- sort alternative bundle sets and their bundles deterministically
- estimate the complete serialized cost of the required bundle set before admission
- admit all units/path/metadata in every chosen required bundle
- never admit only a subset of one bundle or only a subset of a jointly required set
- optional evidence cannot displace an admitted mandatory bundle
```

Recommended ordering within a candidate bundle set:

```text
directness/completeness
-> source_rank ASC
-> serialized cost ASC
-> bundle_id ASC
```

If no complete mandatory bundle fits:

```text
cannot_answer = true
reason_code = REQUIRED_EVIDENCE_EXCEEDS_CONTEXT_BUDGET
provider call count = 0
```

This is insufficient projectable evidence, not an invalid user request and not
an HTTP 422 `ANSWER_REQUEST_INVALID` condition.

## 11. Optional Evidence Filling

After mandatory admission, optional evidence fills only the remaining evidence
budget.

Rules:

- Preserve final retrieval rank among retained optional candidates.
- Skip an oversized optional candidate and continue to lower-ranked candidates.
- Never use `break` merely because one candidate does not fit.
- Do not re-add structural/content duplicates.
- Use canonical unit ID as the final stable tie-break.
- Record every budget omission with `context_budget_exceeded`.

Optional evidence improves explanation and coverage but is never required for
the projected context to pass sufficiency.

## 12. Projected Block Contracts

Projected legal text and graph reasoning metadata use separate DTOs.

```python
class LegalEvidenceBlock(BaseModel):
    unit_id: str
    label: Literal["Article", "Clause", "Point"]
    citation_label: str
    document_id: str
    document_number: str | None
    document_title: str | None
    version_family_id: str | None
    article_id: str | None
    clause_id: str | None
    deep_link: str
    content_raw: str
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None

class ProjectedPathBlock(BaseModel):
    path_id: str
    nodes: tuple[str, ...]
    edges: tuple[ProjectedGraphEdge, ...]
    description: str
```

Temporal-invalid paths are rejected at the retrieval boundary and never enter
projection. Projected edges retain canonical direction and relationship temporal
metadata.

Contract boundary:

```text
LegalEvidenceBlock
-> contains attributable legal text
-> may enter Evidence Registry
-> may be cited by model output

ProjectedPathBlock
-> contains verified graph reasoning metadata
-> may contain Document, structural, or semantic node IDs
-> may be referenced only through allowed reasoning_path_ids
-> does not automatically make any path node citable
```

A semantic node in a path does not require `content_raw`. A path node becomes
citable only when it separately resolves to a selected `LegalEvidenceBlock`.

## 13. Projected Context Contract

Extend `ProjectedAnswerContext` with deterministic projection metadata:

```python
class ProjectedAnswerContext(BaseModel):
    # existing trusted query, intent and temporal fields
    evidence: tuple[LegalEvidenceBlock, ...]
    paths: tuple[ProjectedPathBlock, ...]
    admitted_bundle_ids: tuple[str, ...]
    selected_unit_ids: tuple[str, ...]
    omitted_evidence: tuple[OmittedEvidence, ...]
    budget: ContextBudgetPlan
    truncated: bool
    projection_contract_version: Literal["answer-context-v2"]
```

Invariants:

```text
selected_unit_ids == tuple(item.unit_id for item in evidence)
admitted_bundle_ids are unique and deterministically ordered
all citable legal-unit nodes required by admitted bundles are selected evidence
semantic/non-citable path nodes may remain only in ProjectedPathBlock metadata
truncated == bool(omitted evidence caused by budget)
serialization is byte-stable for unchanged input/config
```

Do not include embeddings, provider credentials, raw provider exceptions, or
unselected retrieval evidence.

## 14. Post-projection Sufficiency

`ProjectedContextValidator` evaluates the final projected context, not the
original retrieval context.

Intent-specific checks:

```text
factual/definition
-> at least one direct evidence unit from the admitted bundle

hierarchy
-> required parent/child units and complete CONTAINS path remain

multi_hop
-> all required citable legal units and complete ProjectedPathBlock metadata remain
-> semantic intermediate nodes need not be LegalEvidenceBlocks

validity
-> temporal subject, resolved date and required interval metadata remain

comparison
-> every required version remains represented
```

Failure behavior:

```text
cannot_answer = true
reason_code = PROJECTED_EVIDENCE_INSUFFICIENT
provider call count = 0
```

The validator must not silently add evidence back from `RetrievalContext`.

## 15. Evidence Registry

Build the immutable registry only from selected `LegalEvidenceBlock` objects and
only after post-projection sufficiency passes.

Recommended contract:

```python
class EvidenceRegistryEntry(BaseModel):
    unit_id: str
    citation_label: str
    document_id: str
    article_id: str | None
    clause_id: str | None
    deep_link: str
    content_raw: str
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None

class EvidenceRegistry(BaseModel):
    entries: tuple[EvidenceRegistryEntry, ...]
    allowed_citation_ids: tuple[str, ...]
    allowed_path_ids: tuple[str, ...]
```

Registry invariants:

```text
registry entry IDs == ProjectedContext selected unit IDs
allowed citation IDs == registry entry IDs
allowed path IDs == projected path IDs
no omitted retrieval unit appears in the registry
semantic/path-only node IDs do not appear unless selected as LegalEvidenceBlocks
```

Grounding validation must consume this registry or an equivalent projection,
not reconstruct an allowlist from the original `RetrievalContext`.

## 16. Prompt Construction

Prompt construction consumes only:

```text
ProjectedAnswerContext
EvidenceRegistry
output schema/contract
```

Prompt requirements remain aligned with Plan 11:

- Legal text is delimited as trusted quoted data.
- Every supported claim requires an allowlisted citation ID.
- The model cannot create unit IDs, graph paths, legal dates, or deep links.
- Reasoning path IDs must come from `allowed_path_ids`.
- Temporal assertions must match the projected resolved date and subjects.
- Unselected evidence and conversation history cannot expand the citation
  allowlist.

## 17. Failure Matrix

| Condition | Result | Provider calls |
|---|---|---:|
| `no_results` | deterministic `cannot_answer` | 0 |
| unsupported capability | typed unsupported result/error | 0 |
| retrieval dependency failure | typed dependency failure | 0 |
| malformed evidence | `EvidenceContractError` | 0 |
| invalid fixed budget configuration | typed configuration/internal error | 0 |
| mandatory bundle does not fit | `cannot_answer`, `REQUIRED_EVIDENCE_EXCEEDS_CONTEXT_BUDGET` | 0 |
| projected context insufficient | `cannot_answer`, `PROJECTED_EVIDENCE_INSUFFICIENT` | 0 |
| provider timeout/dependency/output failure | existing typed provider failure | attempted |
| citation outside registry | `GroundingValidationError`/citation subtype | attempted |
| invented reasoning path | existing path validation failure | attempted |

No failure may produce fake evidence or a fabricated supported answer.

## 18. Proposed File Changes

Recommended minimal structure:

```text
src/generation/
├── evidence_validation.py       # EvidenceValidator
├── evidence_compaction.py       # groups, dedup, bundles
├── context_projection.py        # budget/admission/projection/registry/prompt
├── projected_validation.py      # ProjectedContextValidator
├── models.py                    # immutable DTO additions
├── errors.py                    # typed contract/config errors
├── service.py                   # canonical orchestration owner
├── grounding.py                 # registry-backed allowlist validation
└── config.py                    # projection budget/reserve config
```

Update composition only where constructor dependencies change:

```text
src/application/answer_factory.py
apps/backend/container.py
apps/backend/settings.py
apps/backend/.env.example
```

Do not create a second answer-generation service or a second prompt path.

## 19. Migration Strategy

### Step 1: Freeze DTOs and errors

- Add projection contract version and immutable DTOs.
- Add `EvidenceContractError` and configuration error if needed.
- Add the two stable insufficiency reason codes.
- Keep API response compatibility unless a versioned field is intentionally
  exposed.

### Step 2: Implement validation and compaction

- Implement eligibility validation.
- Implement structural grouping and deterministic deduplication.
- Implement intent-specific mandatory bundle resolution.
- Do not change retrieval ordering or graph traversal.

### Step 3: Replace greedy projection

- Add complete budget planning.
- Add atomic bundle admission.
- Replace `break` behavior with optional skip-and-continue.
- Record omission metadata.

### Step 4: Add post-projection gate and registry

- Validate final projected evidence.
- Build registry only from selected units and paths.
- Make prompt and grounding use the same registry contract.

### Step 5: Integrate services and composition root

- Keep retrieval exception ownership in `GraphRAGAnswerService`.
- Keep supported/no-results context gating in `AnswerGenerator`.
- Ensure every fail-closed branch avoids provider execution.
- Update factory/container constructor wiring.

### Step 6: Remove obsolete behavior

- Remove `AnswerRequestError("No projectable legal evidence is available")`.
- Remove any allowlist reconstruction from original unprojected context.
- Remove dead greedy-prefix helpers after migration tests pass.

## 20. Required Tests

### 20.1 Evidence validation

```text
test_malformed_evidence_raises_typed_contract_error
test_empty_content_is_not_silently_dropped
test_graph_path_shape_requires_nodes_equals_relations_plus_one
test_relation_id_count_matches_relation_count
```

### 20.2 Grouping and deduplication

```text
test_article_and_clause_are_grouped_by_legal_basis
test_clause_content_is_not_duplicated_through_parent_article
test_point_keeps_identity_with_parent_context
test_distinct_document_versions_are_not_deduplicated
test_dedup_tie_break_is_deterministic
```

### 20.3 Mandatory bundles

```text
test_factual_bundle_contains_direct_evidence
test_hierarchy_bundle_contains_parent_child_and_contains_path
test_multi_hop_bundle_is_atomic_for_source_intermediate_target
test_validity_bundle_contains_subject_date_and_interval_metadata
test_comparison_bundle_preserves_each_required_version
test_incomplete_bundle_is_never_returned
```

### 20.4 Budget and optional filling

```text
test_oversized_first_optional_unit_does_not_block_smaller_units
test_oversized_middle_unit_does_not_block_lower_ranked_units
test_mandatory_bundle_is_never_partially_admitted
test_mandatory_bundle_budget_failure_returns_cannot_answer
test_optional_evidence_cannot_displace_mandatory_evidence
test_budget_accounts_for_fixed_prompt_and_path_overhead
test_projection_serialization_is_deterministic
```

### 20.5 Post-projection sufficiency

```text
test_projected_factual_context_requires_direct_evidence
test_projected_hierarchy_context_requires_complete_path
test_projected_multi_hop_context_rejects_missing_intermediate_unit
test_projected_validity_context_rejects_missing_temporal_metadata
test_projected_comparison_context_rejects_missing_version
```

### 20.6 Registry and grounding

```text
test_registry_ids_equal_projected_evidence_ids
test_omitted_evidence_is_not_allowlisted
test_path_only_semantic_node_is_not_citation_eligible
test_prompt_allowlist_equals_registry_allowlist
test_citation_outside_registry_is_rejected
test_projected_path_allowlist_is_exact
```

### 20.7 Service orchestration

```text
test_no_results_does_not_call_provider
test_unsupported_capability_does_not_call_generator_or_provider
test_retrieval_dependency_failure_does_not_call_generator_or_provider
test_malformed_evidence_does_not_call_provider
test_budget_failure_does_not_call_provider
test_post_projection_failure_does_not_call_provider
test_provider_is_called_once_after_all_gates_pass
```

Existing provider, grounding, backend lifecycle, and SSE tests must continue to
pass without weakening assertions.

## 21. Verification Commands

Targeted tests during implementation:

```bash
uv run pytest -q \
  src/generation/tests/test_models_and_projection.py \
  src/generation/tests/test_sufficiency.py \
  src/generation/tests/test_grounding_and_service.py
```

Required completion checks:

```bash
uv run pytest -q
uv run ruff check src/generation src/application/answer_factory.py \
  apps/backend/container.py apps/backend/settings.py
uv run ruff format --check src/generation src/application/answer_factory.py \
  apps/backend/container.py apps/backend/settings.py
git diff --check
```

Optional live provider tests remain opt-in and are not required for deterministic
selection correctness.

## 22. Acceptance Criteria

| ID | Requirement | Evidence |
|---|---|---|
| CP-01 | Retrieval exceptions and context outcome remain owned by their existing service layers | Service unit tests |
| CP-02 | Malformed evidence fails typed and is not silently dropped | Validation tests |
| CP-03 | Structural overlap is compacted without losing provenance | Group/dedup tests |
| CP-04 | Every admitted bundle and jointly required bundle set is atomic | Bundle and budget tests |
| CP-05 | Oversized optional evidence does not block smaller later evidence | Projection tests |
| CP-06 | Mandatory budget failure returns deterministic `cannot_answer` | Service tests |
| CP-07 | Post-projection insufficiency prevents provider execution | Service tests |
| CP-08 | Registry IDs exactly equal selected LegalEvidenceBlock IDs | Registry tests |
| CP-09 | Omitted evidence cannot be cited | Grounding tests |
| CP-10 | Prompt and registry expose identical citation/path allowlists | Prompt tests |
| CP-11 | Unchanged input/config produces byte-stable projection | Determinism test |
| CP-12 | Full tests, Ruff, formatting, and diff checks pass | Command output |
| CP-13 | Path-only semantic nodes never become citation-eligible automatically | Registry tests |

## 23. Explicitly Deferred

The following are not part of this migration:

- Changing vector/full-text/graph ranking.
- Adding another model to summarize or select context.
- Remote provider token-count calls during projection.
- Arbitrary character-level truncation of legal provisions.
- Legal-aware sentence chunking beyond existing Article/Clause/Point units.
- Redefining the retrieval multi-hop intent or evaluation dataset.
- Closing Gate 7, M3-B13, Milestone A, or Milestone B.

Future token-aware budgeting or legal-aware sub-unit chunking requires a separate
measured change after this deterministic contract is stable.

## 24. Completion Status

```text
Plan status: IMPLEMENTED, ALIGNED WITH RETRIEVAL-RUNTIME-V2
Implementation: COMPLETE
Context contract version: answer-context-v2
Deterministic verification: PASS
Provider/model contract: unchanged
Retrieval ranking contract: unchanged
Graph-path safety contract: Plan 14
Multi-hop answer generation: fail-closed without trusted graph requirement
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```
