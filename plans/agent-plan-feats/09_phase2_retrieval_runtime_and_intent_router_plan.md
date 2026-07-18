# Phase 2 Retrieval Runtime and Intent Router Execution Contract

> Plan status: IMPLEMENTED FOR PILOT DEVELOPMENT
> Canonical retrieval contract: `plans/05_graphrag_retrieval.md`
> Parent retrieval plan: `plans/agent-plan-feats/07_phase2_graphrag_retrieval_plan.md`
> Canonical ontology: `plans/legal_ontology.md` v1.6.0
> Blocker authority: `plans/agent-plan-feats/06_m3_blocker_register.md`
> Runtime contract version: `retrieval-runtime-v2`

## 0. Mandatory Status

```text
Gate 7: OPEN
M3-B13: OPEN
Milestone A: NOT PASSED
Phase 2 retrieval development: ALLOWED on current pilot data
Milestone B acceptance: NOT STARTED
Answer generation: IMPLEMENTED UNDER PLAN 11; OUT OF SCOPE OF THIS PLAN
Backend retrieval integration: IMPLEMENTED UNDER PLAN 10; OUT OF SCOPE OF THIS PLAN
```

No implementation, test, pilot metric, or report under this plan may change a
status above to `PASS`, `COMPLETE`, or `CLOSED`.

## 1. Objective and Scope

Implement one retrieval runtime that converts a validated legal query into an
auditable intent decision, executes selected seed retrieval channels, performs
one graph expansion, creates one graph-derived ranked list, and returns a
deterministic `RetrievalContext` containing citations, attribution, temporal
status, evidence paths, and deep links.

In scope:

- shared request/result contracts and retrieval ports;
- six-intent router and temporal precedence;
- capability inspection and typed outcomes;
- vector/full-text seed retrieval, two-stage RRF, and one graph expansion;
- strategy-specific temporal filtering and optional reranking;
- one application composition root and explicit resource ownership;
- synchronous developer CLI with atomic output;
- pilot development evaluation and separated integration suites.

Out of scope:

- answer generation or reasoning model calls;
- backend/FastAPI promotion and async integration;
- Gate 7 corpus expansion or M3-B13 closure;
- Milestone A/Milestone B sign-off;
- ontology migration, new relation types, or reranker training;
- fabricated legal evaluation data for unsupported capabilities.

## 2. Baseline and Required Refactor

Reusable channel, mapping, RRF, temporal, evidence, context, evaluation, and
infrastructure adapter code existed before execution. The former
`HybridRetriever` orchestration and concrete retrieval-to-infrastructure imports
were the refactor targets. They have been removed from the active runtime path.

Required outcome:

```text
HybridRetriever orchestration ownership: REMOVED
RetrievalRuntime orchestration ownership: EXCLUSIVE
Graph expansion per request: EXACTLY ONCE
Concrete dependency assembly points: EXACTLY ONE
```

## 3. Dependency Direction and Composition Root

### 3.1 Canonical dependency contract

```text
retrieval domain
-> depends only on shared DTOs, retrieval protocols, and domain abstractions

infrastructure
-> supplies concrete adapters that structurally satisfy retrieval ports
-> does not import retrieval orchestration/runtime

application composition root
-> may import retrieval, infrastructure, and shared
-> is the only concrete assembly point
```

Mandatory imports:

```text
src/retrieval must not import:
- src/infrastructure
- src/pipeline
- apps
- prototypes

src/infrastructure must not import:
- src/retrieval
- apps

src/application/retrieval_factory.py may import:
- src/retrieval
- src/infrastructure
- src/shared
```

Infrastructure adapters use structural typing and do not import protocol classes
to declare conformance. Test fakes implement the same protocols.

### 3.2 Target structure

```text
src/shared/
└── retrieval_contract.py

src/retrieval/
├── ports.py
├── config.py
├── errors.py
├── routing/
│   ├── models.py
│   └── router.py
├── runtime/
│   ├── runtime.py
│   └── lifecycle.py
├── retriever/
├── fusion/
├── context/
├── evidence/
├── eval/
└── cli.py

src/application/
└── retrieval_factory.py

src/infrastructure/
├── neo4j/
├── embedding/
└── llm/
```

### 3.3 Ports and composition

`src/retrieval/ports.py` defines typed behavior contracts such as:

```text
VectorSearchPort
FullTextSearchPort
GraphExpansionPort
EmbeddingPort
IntentClassifierPort
RerankerPort
CapabilityInspectionPort
Clock
ClosableResource
```

Ports expose shared/domain DTOs and primitives, never Neo4j sessions/records,
Cypher, provider SDK responses, or pipeline models.

`src/application/retrieval_factory.py` is the only composition root. It assembles
validated settings, driver, infrastructure adapters, optional providers,
router, runtime, and lifecycle owner. No driver, model, client, or runtime is
created at module import time.

## 4. One Canonical Orchestration Pipeline

Exactly one pipeline is permitted:

```text
1. Query analysis and routing
2. Execute seed channels:
   - vector when enabled
   - full-text when enabled
3. Seed RRF over executed seed ranked lists
4. Select graph_entry_k seeds in deterministic seed-RRF order
5. Execute graph expansion exactly once using the routed graph policy
6. Convert graph-derived legal units into one graph ranked list
7. Final RRF over:
   - vector ranked list when executed
   - full-text ranked list when executed
   - graph ranked list when produced
8. Apply strategy-specific temporal validation/filtering
9. Apply optional reranking
10. Verify evidence
11. Build RetrievalContext
```

Option B is mandatory: decompose `HybridRetriever` into responsibility-specific
channel executors; `RetrievalRuntime` owns all orchestration. No public or
compatibility wrapper may retain a second orchestration path.

`RetrievalChannel.GRAPH` means the graph-derived ranked list produced after seed
RRF. It is not an independent seed search. Therefore graph expansion never runs
before seed RRF, never runs twice, and enters final RRF exactly once.

## 5. Shared and Domain Contracts

### 5.1 Contract version and intent source

All public request, decision, context, CLI, and evaluation outputs expose:

```text
contract_version = retrieval-runtime-v2
```

`IntentType` has one definition in `src/shared/retrieval_contract.py`. It may be
re-exported for compatibility, but duplicate enum definitions are forbidden.

### 5.2 Retrieval request

```python
class RetrievalRequest(BaseModel):
    contract_version: Literal["retrieval-runtime-v2"]
    query: str = Field(min_length=1, max_length=4000)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int | None = Field(default=None, ge=1, le=200)
    final_k: int | None = Field(default=None, ge=1, le=200)
    force_intent: IntentType | None = None
    enable_reranker: bool | None = None
```

`force_intent` changes intent classification only. It does not bypass request,
filter, temporal, dependency, or capability validation.

### 5.3 Routing enums

```python
class RetrievalChannel(str, Enum):
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    GRAPH = "graph"

class RetrievalStrategyType(str, Enum):
    FACTUAL_HYBRID = "factual_hybrid"
    DEFINITION_GRAPH = "definition_graph"
    VALIDITY_TEMPORAL = "validity_temporal"
    HIERARCHY_GRAPH = "hierarchy_graph"
    COMPARISON_TEMPORAL = "comparison_temporal"
    MULTI_HOP_HYBRID = "multi_hop_hybrid"

class TemporalSource(str, Enum):
    NONE = "none"
    REQUEST = "request"
    QUERY_EXPRESSION = "query_expression"
    INJECTED_CURRENT_DATE = "injected_current_date"

class RetrievalDecisionReasonCode(str, Enum):
    FACTUAL_DEFAULT = "FACTUAL_DEFAULT"
    DEFINITION_EXPLICIT = "DEFINITION_EXPLICIT"
    VALIDITY_EXPLICIT_DATE = "VALIDITY_EXPLICIT_DATE"
    VALIDITY_CURRENT_DATE = "VALIDITY_CURRENT_DATE"
    HIERARCHY_EXPLICIT = "HIERARCHY_EXPLICIT"
    COMPARISON_EXPLICIT = "COMPARISON_EXPLICIT"
    MULTI_HOP_EXPLICIT = "MULTI_HOP_EXPLICIT"
    FORCED_INTENT = "FORCED_INTENT"
```

### 5.4 Routing decision

```python
class RetrievalDecision(BaseModel):
    contract_version: Literal["retrieval-runtime-v2"]
    intent: IntentType
    strategy: RetrievalStrategyType
    seed_channels: tuple[RetrievalChannel, ...]
    graph_enabled: bool
    graph_policy_intent: IntentType | None
    candidate_k: int
    graph_entry_k: int
    final_k: int
    apply_temporal_filter: bool
    preserve_versions: bool
    require_temporal_point: bool
    enable_reranker: bool
    force_intent_used: bool
    temporal_source: TemporalSource
    decision_reason_code: RetrievalDecisionReasonCode
    decision_reason: str
```

`seed_channels` may contain only `VECTOR` and `FULLTEXT`. `GRAPH` is represented
by `graph_enabled` because it is post-seed expansion/final-fusion evidence.
`decision_reason_code` is stable for audit/tests; `decision_reason` is explanatory.

### 5.5 Retrieval context metadata

Extend the existing `RetrievalContext`, do not duplicate result data. Required
metadata:

```text
contract_version
strategy
executed_channels
force_intent_used
temporal_source
decision_reason_code
decision_reason
filters_applied
reranker_applied
capability_status
```

## 6. Limit Precedence

```text
candidate_k = request.top_k ?? config.candidate_k
final_k = request.final_k ?? config.final_k
graph_entry_k = min(config.graph_entry_k, candidate_k)
```

Validate after resolution:

```text
1 <= final_k <= candidate_k <= 200
1 <= graph_entry_k <= candidate_k
```

Invalid request overrides raise `RetrievalRequestError`. `candidate_k` and
`final_k` are never silently clamped. The specified `min` for `graph_entry_k` is
the only permitted reduction. Output limits apply only after stable ordering.
Invalid config defaults fail startup.

## 7. Temporal Precedence and Conflicts

Precedence:

```text
explicit request filters.query_date
> temporal expression resolved from query
> injected Clock date only for explicit current-validity wording
```

Current-validity wording includes explicit equivalents of `hiện hành`, `hiện
nay`, `đang có hiệu lực`, and `còn hiệu lực không`. It does not include every
query without a date.

Rules:

- Router/runtime never call `date.today()` directly; use injected `Clock`.
- Request date and parsed date both present but different:
  `TemporalRoutingError`.
- Matching request/parsed dates use request date and `temporal_source=REQUEST`.
- Explicit temporal expression that cannot be resolved:
  `TemporalRoutingError`.
- Never downgrade failed temporal parsing to non-temporal retrieval.
- `force_intent` does not suppress temporal parsing.
- `force_intent=validity` without a resolved point fails unless explicit
  current-validity wording permits injected clock time.
- `force_intent=comparison` still requires comparison capability.
- Validity uses a point; comparison may use interval/multiple versions.
- Other intents apply time only when a valid source exists.

Validity remains half-open:

```text
effective_from <= query_date
AND (effective_to IS NULL OR effective_to > query_date)
```

## 8. Intent Routing Matrix

| Intent | Strategy | Seed channels | Graph policy | Temporal | Version behavior | Reranker |
|---|---|---|---|---|---|---|
| factual | factual hybrid | vector + full-text | factual | optional | ordinary | configurable |
| definition | definition graph | full-text + vector | definition | optional | ordinary | configurable |
| validity | validity temporal | full-text + vector | validity | required point | temporal chain | configurable |
| hierarchy | hierarchy graph | full-text; vector by config | hierarchy | optional | ordinary | off by default |
| comparison | comparison temporal | vector + full-text | comparison | required | preserve versions | configurable |
| multi-hop | multi-hop hybrid | vector + full-text | multi-hop | optional | strategy-specific | configurable |

All six intents route explicitly. Unknown intent is an error; there is no
fallback that runs all channels or silently selects factual.

## 9. Capability Contract

The runtime distinguishes:

```text
no_results
unsupported_capability
dependency_failure
```

- `no_results`: dependencies/capability exist, execution is valid, no legal unit
  matches filters/query.
- `unsupported_capability`: strategy requires legal graph/data capability absent
  in the scoped graph.
- `dependency_failure`: required runtime dependency is absent, invalid, or fails.

Add `RetrievalCapabilityError`. Use it when, for example:

- comparison needs multiple versions but scope has one;
- current/corpus-complete validity needs corpus coverage unavailable in pilot;
- version-chain validity needs temporal relations;
- historical scoped validity may use complete `effective_from`, `effective_to`,
  and `legal_status` metadata;
- implementing-document hierarchy requires `GUIDES`, while structural
  Article/Clause/Point hierarchy uses `CONTAINS`.

Do not return empty results for unsupported capability. Do not fabricate graph
relations or legal gold.

`CapabilityInspectionPort` returns a scoped immutable snapshot, separating
runtime/index capabilities from legal-data capabilities:

```text
vector_article_index_available
vector_clause_index_available
fulltext_index_available
scoped_temporal_metadata_available
corpus_complete_current_validity_available
temporal_relations_available
structural_hierarchy_available
guides_relations_available
multiple_versions_available
definition_relations_available
semantic_multi_hop_graph_available
canonical_relation_types_available
```

Scope uses request filters and canonical Document identity, never ID prefixes.

Unsupported evaluation case:

```json
{
  "status": "unsupported",
  "reason": "...",
  "required_capability": "...",
  "available_capability": "..."
}
```

Unsupported is reported separately, not scored as failed retrieval quality.

## 10. Graph Ranking Contract

Graph expansion executes exactly once after seed RRF. Entry seeds are the first
`graph_entry_k` units from deterministic seed-RRF output.

Path order:

```text
path_length ASC
source_unit_id ASC
target_unit_id ASC
relation_type_sequence ASC
node_id_sequence ASC
```

Graph-derived ranking:

1. Iterate ordered paths.
2. Lift each endpoint to a retrievable legal unit where required.
3. Rank the unit at its first deterministic occurrence.
4. Deduplicate later unit occurrences by canonical ID while retaining all paths.
5. Emit one graph ranked list.

No arbitrary boost and no direct addition of vector/BM25/graph floating-point
scores. Graph evidence participates only as an independent ranked list in final
RRF.

Parallel edges with distinct ontology/provenance identity remain distinct
evidence paths when the ontology treats them as distinct.

Point endpoint rules:

- keep Point in explanation/evidence path;
- lift context to parent Clause, or parent Article when no Clause exists;
- never make Point a vector target;
- retain original edge/path provenance;
- do not rewrite the evidence path endpoint during lifting.

## 11. Runtime Responsibilities

`src/retrieval/runtime/runtime.py` exclusively owns orchestration:

1. Validate request and contract version.
2. Parse temporal expression even with forced intent.
3. Classify intent unless forced.
4. Resolve temporal source/conflicts.
5. Route and resolve limits.
6. Inspect required capabilities.
7. Execute selected seed channels.
8. Seed RRF.
9. Select graph seeds.
10. Expand graph once.
11. Build graph ranked list.
12. Final RRF.
13. Apply strategy temporal behavior.
14. Optionally rerank.
15. Verify evidence/outcome.
16. Build context and metrics.

Metrics record actual executed channels, not merely configured channels.

## 12. Configuration and Startup Verification

Create retrieval-specific settings without importing `src.pipeline.config`:

```text
RETRIEVAL_CONTRACT_VERSION=retrieval-runtime-v2
RETRIEVAL_CANDIDATE_K=20
RETRIEVAL_FINAL_K=10
RETRIEVAL_GRAPH_ENTRY_K=5
RETRIEVAL_RRF_K=60
RETRIEVAL_RERANKER_ENABLED=false
RETRIEVAL_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RETRIEVAL_RERANKER_FP16=false
RETRIEVAL_HIERARCHY_VECTOR_ENABLED=false
RETRIEVAL_QUERY_MAX_LENGTH=4000
```

Model names are config, not domain constants. Shared Neo4j/embedding settings
belong to infrastructure/application config, not retrieval or pipeline ownership.
No document ID, raw code, pilot path, port, or filesystem path is a domain
default.

Factory verifies only dependencies needed by the enabled profile:

```text
vector disabled -> no vector index or embedding provider requirement
full-text disabled -> no full-text index requirement
reranker disabled -> do not load or verify reranker
```

Enabled vector requires matching indexes/dimension; enabled full-text requires
canonical index; enabled graph requires canonical policy support; enabled
reranker requires configured provider/model. Intent fallback provider is required
only when deterministic analysis cannot resolve intent.

Missing required dependency raises `RetrievalDependencyError`. No fake fallback
and no provider-error fallback to factual.

## 13. Lifecycle Ownership

`runtime/lifecycle.py` defines ownership abstractions;
`application/retrieval_factory.py` creates concrete resources.

```python
with create_retrieval_runtime(config) as runtime:
    context = runtime.retrieve(request)
```

Rules:

- Factory-owned resources close exactly once.
- External resources are not closed unless ownership is transferred.
- Partial construction closes resources in reverse acquisition order.
- Retrieval failure still closes owned resources.
- No resource is constructed during module import.
- Infrastructure sessions close on success and failure.

## 14. Typed Errors

```text
RetrievalRequestError
IntentAnalysisError
RetrievalRoutingError
TemporalRoutingError
RetrievalCapabilityError
RetrievalDependencyError
RetrievalExecutionError
RetrievalOutputError
```

Invalid request/filter/limit, invalid provider intent, routing failure, temporal
conflict, unsupported capability, missing dependency, execution violation, and
atomic output failure map to their respective types. No `except Exception: pass`,
swallowed errors, fake output, or stale output.

## 15. CLI Hardening

Example only, with no default Document ID:

```bash
uv run python -m src.retrieval.cli retrieve \
  --query "quyền thành lập và quản lý doanh nghiệp" \
  --document-id ldn_2020 \
  --top-k 20 \
  --final-k 5
```

Arguments:

```text
--query
--document-id (repeatable)
--doc-type (repeatable)
--legal-status (repeatable)
--query-date YYYY-MM-DD
--top-k
--final-k
--force-intent
--no-reranker
--output PATH
```

Output includes:

```text
contract_version
query
intent
strategy
decision_reason_code
decision_reason
force_intent_used
temporal_source
executed_channels
filters
retrieved_units
graph_paths
evidence
metrics
capability_status
```

Logs go to stderr; JSON goes to stdout without `--output`. Credentials, keys,
vectors, and sensitive provider payloads are never logged. Typed failure returns
non-zero and no fake JSON.

Atomic UTF-8 output:

```text
1. create temp file in destination directory;
2. write complete JSON;
3. flush;
4. fsync when repository convention requires it;
5. atomically replace destination;
6. remove temp file on every failure.
```

## 16. Evaluation Contract

The 30-query pilot target is development evaluation only.

Required wording:

```text
evaluation_scope = pilot_development
development latency distribution
Gate 7 = OPEN
M3-B13 = OPEN
Milestone A = NOT PASSED
Milestone B acceptance = NOT STARTED
```

Do not call small-sample latency p95 production evidence. Do not score
unsupported as quality failure. Do not use fixture data as legal gold.

Profiles use the same runtime, with explicit recorded evaluation overrides:

```text
vector_only
fulltext_only
vector_graph
hybrid
hybrid_reranked
```

Each case records forced-intent usage and supported/unsupported status. Every
report records:

```text
evaluation_scope = pilot_development
dataset_hash
source_commit
runtime_contract_version
router_config_hash
embedding_contract
reranker_contract
Neo4j graph snapshot hash
force_intent_used per case
supported/unsupported status
development latency distribution with sample size
Gate 7 = OPEN
M3-B13 = OPEN
Milestone A = NOT PASSED
Milestone B acceptance = NOT STARTED
```

Metrics for supported cases only:

```text
Recall@5
Recall@10
MRR
nDCG@5
no-results rate
graph-path hit rate
citation completeness
temporal validity violations
development latency p50/p95 with sample size
```

Unsupported counts/reasons are separate.

## 17. Python Implementation Quality

- Follow repository conventions and PEP 8.
- Fully type public interfaces.
- Do not duplicate logic.
- Do not hard-code `L59_2020`, model, port, path, raw code, or Document ID in
  runtime/domain code.
- Separate domain, orchestration, application composition, and infrastructure.
- Avoid over-engineering; keep one clear responsibility per function/class.
- Do not use `except Exception: pass`, swallow errors, or return fake results.
- Use structured logging instead of `print` in runtime code.
- Parameterize Cypher; never concatenate user input into Cypher.
- Do not run blocking retrieval in async routes; future backend integration must
  use an explicit thread boundary.
- Close driver/session/client/model resources according to ownership.
- Create no resource at module import.
- Use stable deterministic ordering/ties.
- Validate public DTOs and expose contract version.
- Do not modify tests to hide implementation bugs.

## 18. Test Contract

### 18.1 Static/dependency tests

- Retrieval imports no infrastructure/pipeline/apps/prototypes.
- Infrastructure imports no retrieval runtime/domain.
- Application factory is the only concrete assembly point.
- Module imports create no resources.
- Exactly one `IntentType` definition exists.

### 18.2 Router tests

- All six intents map explicitly with stable reason codes.
- Forced intent status is accurate.
- Forced intent does not bypass temporal/request/filter/capability validation.
- Request date conflict with parsed query date fails.
- Explicit unresolved time fails.
- Injected clock is used only for explicit current-validity wording.
- Forced validity without temporal point fails.
- Limit precedence/bounds are exact.
- Decisions are immutable/deterministic.

### 18.3 Runtime tests

- Selected seed channels execute; disabled channels do not.
- Graph expansion executes exactly once.
- Seed RRF and final RRF are distinct/deterministic.
- Graph ranked list enters final RRF exactly once.
- GRAPH never executes as seed search.
- Empty valid result returns `no_results`.
- Unsupported capability raises `RetrievalCapabilityError`.
- Dependency failure is distinct.
- Filters pass unchanged.
- Point lift preserves provenance and legal context.
- Parallel provenance paths remain distinct.
- Citation/deep links survive fusion/reranking.
- Context exposes contract version, forced-intent status, and temporal source.

### 18.4 Factory/lifecycle tests

- Enabled profile verifies only required dependencies.
- Disabled vector/full-text/reranker dependencies are not loaded/checked.
- Missing enabled dependency fails startup.
- Owned resource closes on success/failure.
- Partial construction cleanup is reverse order.
- External resource is not closed.

### 18.5 CLI tests

- Happy JSON output and stdout/stderr separation.
- Repeatable filters.
- Invalid input and typed failures return non-zero without fake output.
- Atomic replace happens only after complete success.
- Temp output is removed on failure.
- Logs contain no secrets/vectors.
- Output contains contract version and forced-intent status.

## 19. Integration Test Separation

### 19.1 Pilot read-only retrieval tests

- Run on guarded disposable M3 Neo4j.
- Read pilot graph only.
- Create/update/delete no graph or schema object.
- Capture legal graph and embedding digests before/after.
- Both digests must remain identical.
- Test only mechanics/capabilities present in pilot.

Acceptance: RR-04, RR-07, RR-11, RR-18, RR-20.

### 19.2 UUID fixture mechanics tests

- Explicitly mutating, never called read-only.
- Used only for mechanics absent from pilot.
- Unique UUID namespace for every fixture.
- Never use or match `ldn_2020`.
- Collect all cleanup matches first.
- If any identity lies outside current UUID namespace, fail without deleting.
- Guard cleanup to current UUID namespace.
- Never use fixture data as legal evaluation gold.

Acceptance: RR-01, RR-05, RR-14, RR-15, RR-16, RR-17, RR-19.

Suites use separate paths/markers/reports.

## 20. Execution Order

1. Freeze DTOs, ports, dependency direction, and composition root.
2. Freeze one orchestration pipeline and two-stage RRF.
3. Implement router matrix and temporal/capability rules.
4. Decompose `HybridRetriever`; leave runtime as sole orchestrator.
5. Implement selected seed channels and one graph expansion.
6. Add retrieval config.
7. Add application composition root and lifecycle ownership.
8. Add typed errors and outcome distinction.
9. Add CLI with atomic output.
10. Add router/runtime/factory/lifecycle/CLI unit tests.
11. Add pilot read-only integration tests and digest proof.
12. Add isolated UUID fixture mechanics only where needed.
13. Expand pilot development evaluation.
14. Run static, unit, format, diff, and integration verification.
15. Produce development report without status changes.

Implementation exit criteria by dependency:

```text
Steps 1-2:
- no dependency cycle;
- one IntentType;
- one composition root;
- one orchestration path;
- graph executes once.

Steps 3-5:
- router matrix/temporal/capability tests pass;
- two-stage RRF tests pass;
- no arbitrary graph boost;
- context audit metadata complete.

Steps 6-9:
- retrieval imports no pipeline config;
- disabled dependencies are untouched;
- lifecycle/CLI/atomic output tests pass;
- no resource created on import.

Steps 10-15:
- fast and integration suites pass;
- pilot digests unchanged;
- evaluation report uses mandatory pilot wording;
- Gate and milestone status unchanged.
```

Verification commands:

```bash
uv run pytest -q
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
git diff --check

RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest <pilot-read-only-suite> -q -m retrieval_readonly

RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest <fixture-mechanics-suite> -q -m retrieval_fixture
```

## 21. Acceptance Matrix

| ID | Requirement | Evidence |
|---|---|---|
| RR-01 | Six canonical intents route explicitly | Router matrix tests |
| RR-02 | Retrieval has no concrete infrastructure imports | Static import tests |
| RR-03 | Runtime executes selected seed channels only | Runtime tests |
| RR-04 | Filters use canonical Document identity | Unit/read-only integration |
| RR-05 | Temporal routing fails safely | Temporal tests |
| RR-06 | Graph units enter deterministic final RRF | Fusion tests |
| RR-07 | Citation/attribution/provenance/deep links survive | Context/integration tests |
| RR-08 | Resource ownership is correct | Lifecycle tests |
| RR-09 | CLI emits real result or typed failure | CLI tests |
| RR-10 | Evaluation profiles use one runtime | Evaluation report/tests |
| RR-11 | Read-only suite does not mutate pilot | Digest evidence |
| RR-12 | Gate 7/M3-B13 remain open | Status review |
| RR-13 | One composition root owns concrete assembly | Static/factory tests |
| RR-14 | Graph expansion executes exactly once | Call-count tests |
| RR-15 | Seed/final RRF are deterministic | Fusion/order tests |
| RR-16 | Temporal precedence/conflicts are tested | Router temporal tests |
| RR-17 | Unsupported differs from empty result | Capability tests |
| RR-18 | Read-only suite preserves legal/embedding digests | Digest evidence |
| RR-19 | Fixture cleanup cannot touch pilot | UUID guard tests |
| RR-20 | Runtime/CLI expose version and forced-intent status | DTO/CLI tests |

## 22. Stop Conditions

Stop and do not weaken the contract if:

- retrieval requires concrete infrastructure import;
- infrastructure requires retrieval runtime import;
- a second orchestration path remains;
- graph expansion runs more than once;
- user input would be concatenated into Cypher;
- temporal conflict would be ignored;
- forced intent would bypass validation;
- unsupported capability would become empty result;
- provider failure would become factual/fake output;
- read-only tests would mutate pilot;
- fixture cleanup could match outside UUID namespace;
- evaluation requires fabricated legal gold;
- any work would change Gate 7, M3-B13, Milestone A, or Milestone B status.

## 23. Intentionally Deferred

- Answer generation and reasoning model integration.
- Backend/FastAPI promotion and sync-to-async thread boundary.
- Gate 7 four-document execution and M3-B13 closure.
- Milestone A and Milestone B sign-off.
- Production latency/SLA claims.
- Amendment DAG reasoning beyond current ontology limitations.
- Reranker training/fine-tuning.

## 24. Completion Status

```text
Plan status: IMPLEMENTED FOR PILOT DEVELOPMENT
Retrieval runtime implementation: IMPLEMENTED
Intent router implementation: IMPLEMENTED
Runtime contract: retrieval-runtime-v2
Structured graph-path safety: IMPLEMENTED UNDER PLAN 14
Multi-hop retrieval: PROTOTYPE
Multi-hop answer generation: FAIL-CLOSED by default
Evaluation dataset: APPROVED (30-query pilot development dataset)
Official pilot development evaluation under runtime-v2: NOT STARTED
3-query smoke: DEVELOPMENT ONLY
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
Answer generation: IMPLEMENTED UNDER PLAN 11
Backend integration: IMPLEMENTED UNDER PLAN 10
```

Implementation evidence:

```text
fast tests: 220 passed, 6 integration tests deselected
pilot read-only retrieval integration: 1 passed; legal/embedding digests unchanged
UUID fixture mechanics integration: 1 passed; guarded cleanup
runtime CLI smoke: passed against disposable Neo4j
runtime-v1 development evaluation: SUPERSEDED BY runtime-v2 contract migration
runtime-v2 targeted regression tests: PASS
runtime-v2 disposable Neo4j integration: NOT RUN
runtime-v2 official evaluation: NOT STARTED
Recall@5: 0.6011904762
MRR: 1.0
nDCG@5: 0.7846601832
```

The metrics above are historical runtime-v1 development evidence and must not be
used as runtime-v2 acceptance evidence. The balanced 30-query dataset has
human-approved intent, graded gold
relevance, capability expectations, graph paths, hierarchy relations, and
temporal evidence. Official evaluation remains `NOT STARTED` until a clean
source commit and official-candidate artifact verification exist. Full profile
ablation and held-out evaluation remain open.
Therefore this plan is implemented for pilot development but is not Milestone B
acceptance and does not close Gate 7 or M3-B13.
