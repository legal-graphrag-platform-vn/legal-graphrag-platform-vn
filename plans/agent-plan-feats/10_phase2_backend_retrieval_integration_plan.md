# Phase 2 Backend Retrieval Integration Execution Plan

> **Purpose**: expose the implemented retrieval runtime through the existing
> FastAPI backend without adding answer generation, duplicating orchestration,
> or changing Milestone A status.

## 0. Mandatory Status

```text
Gate 7: OPEN
M3-B13: OPEN
Milestone A: NOT PASSED
Phase 2 retrieval development: ALLOWED on current pilot data
Retrieval runtime: IMPLEMENTED, pending official five-profile evidence
Backend retrieval integration: IMPLEMENTED
Answer generation: OUT OF SCOPE for this plan
Milestone B acceptance: NOT STARTED
```

This plan must not mark Gate 7, M3-B13, Milestone A, or Milestone B as passed.
`APP_MODE=graphrag` is a pilot/development integration until the four-document
corpus gate is resumed and accepted.

## 1. Objective

Implement the real `POST /api/v1/query` path:

```text
FastAPI request
-> validated backend DTO
-> GraphRAG retrieval service
-> RetrievalRuntimeHandle.retrieve(...)
-> API DTO mapping
-> deterministic RetrievalResponse
```

The endpoint returns retrieval evidence only. It must not call an answer LLM
and must not add an `answer` field.

## 2. Current Baseline

Existing backend:

```text
apps/backend/main.py
apps/backend/container.py
apps/backend/dependencies.py
apps/backend/settings.py
apps/backend/api/models.py
apps/backend/api/routes/query.py
apps/backend/services/interfaces.py
apps/backend/services/mock_rag_service.py
```

Existing retrieval composition root:

```text
src/application/retrieval_factory.py
src/retrieval/runtime/lifecycle.py
src/retrieval/runtime/runtime.py
src/shared/retrieval_contract.py
```

Important baseline constraints:

- `MockRAGService` remains functional for frontend development.
- `POST /api/v1/query` currently awaits `RAGService.retrieve(...)`.
- The retrieval runtime is synchronous and owns a Neo4j driver through
  `RetrievalRuntimeHandle`.
- The backend must not build a second retrieval pipeline.
- The backend must not import or call channel executors directly.

## 3. Scope

### In scope

- Real retrieval service for `APP_MODE=graphrag`.
- Backend settings required to construct retrieval runtime.
- App-lifespan ownership and cleanup of retrieval resources.
- Mapping API requests to the shared retrieval request contract.
- Mapping `RetrievalContext` to backend response DTOs.
- Typed retrieval error to HTTP response mapping.
- Thread boundary for synchronous retrieval.
- Request timeout, bounded concurrency, and cancellation behavior.
- Unit, API, lifecycle, and disposable-Neo4j integration tests.
- Backend README and environment documentation.

### Out of scope

- Answer generation or LLM provider calls.
- `/chat` real implementation.
- Prompt engineering.
- Frontend changes.
- Document browser repository implementation unless strictly needed by query.
- Gate 7/four-document corpus execution.
- Production deployment, authentication, rate limiting, or observability stack.
- Changing retrieval ranking, routing, graph expansion, reranker, or gold data.

## 4. Dependency Direction

Canonical dependency direction:

```text
apps/backend/api routes
-> apps/backend/services protocol
-> apps/backend/services/graphrag_retrieval_service.py
-> shared retrieval DTOs + RetrievalRuntimeHandle protocol

apps/backend/container.py
-> src/application/retrieval_factory.py
-> retrieval + infrastructure concrete implementations
```

Rules:

- Routes do not import Neo4j, retrieval channel executors, embedding models, or
  concrete repositories.
- `GraphRAGRetrievalService` receives an already-created runtime handle.
- `apps/backend/container.py` is the backend composition root and calls the
  existing retrieval composition root; it does not reassemble retrieval.
- `src/retrieval` must not import `apps/backend`.
- `src/infrastructure` must not import `apps/backend`.
- No global driver/model/runtime is created at module import.
- Test fakes implement the same service/runtime protocols.

## 5. Target Files

```text
apps/backend/
├── api/
│   ├── models.py
│   ├── error_handlers.py              # typed error -> HTTP response
│   └── routes/query.py
├── services/
│   ├── interfaces.py
│   ├── graphrag_retrieval_service.py
│   └── retrieval_mapping.py
├── container.py
├── dependencies.py
├── main.py
├── settings.py
└── tests/
    ├── test_retrieval_mapping.py
    ├── test_graphrag_retrieval_service.py
    ├── test_query_error_contract.py
    ├── test_backend_lifecycle.py
    └── test_query_integration.py
```

Equivalent file placement is acceptable if it follows current backend
conventions and keeps one responsibility per module.

## 6. Backend Runtime Modes

Keep the existing modes:

```text
APP_MODE=mock
APP_MODE=graphrag
```

### Mock mode

- Must not require Neo4j, embedding, reranker, or LLM dependencies.
- Must not instantiate `RetrievalRuntimeHandle`.
- Existing frontend contract remains stable.

### GraphRAG mode

- Constructs exactly one retrieval runtime per FastAPI app lifespan.
- Requires only dependencies enabled by the configured retrieval profile.
- Is explicitly labeled pilot/development while Milestone A is not passed.
- Must fail startup on missing mandatory configuration or indexes.
- Must not silently fall back to mock mode.

## 7. Settings Contract

Backend settings must expose configuration needed by the existing factories,
without duplicating retrieval defaults where avoidable.

Required GraphRAG settings:

```text
APP_MODE=graphrag
NEO4J_URI
NEO4J_USER
NEO4J_PASSWORD
BACKEND_RETRIEVAL_TIMEOUT_SECONDS
BACKEND_RETRIEVAL_MAX_CONCURRENCY
BACKEND_RETRIEVAL_SHUTDOWN_GRACE_SECONDS
```

Retrieval settings continue to use the canonical environment names owned by
`RetrievalConfig` and `RetrievalApplicationSettings`, including:

```text
RETRIEVAL_VECTOR_ENABLED
RETRIEVAL_FULLTEXT_ENABLED
RETRIEVAL_GRAPH_ENABLED
RETRIEVAL_RERANKER_ENABLED
RETRIEVAL_CANDIDATE_K
RETRIEVAL_FINAL_K
RETRIEVAL_GRAPH_ENTRY_K
RETRIEVAL_RERANKER_MODEL
RETRIEVAL_RERANKER_FP16
RETRIEVAL_RERANKER_MAX_LENGTH
RETRIEVAL_RERANKER_NORMALIZE
EMBEDDING_MODEL
EMBEDDING_PROVIDER
EMBEDDING_DIM
```

Rules:

- No default document ID.
- No hard-coded `L59_2020`, `ldn_2020`, port, model, or filesystem path.
- Credentials must never appear in validation errors or logs.
- Timeout must be positive and bounded.
- Maximum concurrency must be a positive bounded integer.
- The concurrency limit is application-scoped, not recreated per request.
- Backend must not redefine retrieval limit precedence.

## 8. API Request Contract

Extend `QueryRequest` only as required to represent the shared retrieval
contract. Recommended fields:

```python
class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=200)
    candidate_k: int | None = Field(default=None, ge=1, le=200)
    document_ids: list[str] = Field(default_factory=list)
    query_date: date | None = None
    force_intent: IntentType | None = None
    enable_reranker: bool | None = None
```

Final field names should match `src/shared/retrieval_contract.py`. Avoid a
second semantic alias such as both `temporal_date` and `query_date`; if API
compatibility requires an alias, define one canonical internal mapping and test
it explicitly.

Validation:

```text
top_k is the backward-compatible API name for runtime final_k
1 <= top_k <= candidate_k <= 200 when both are supplied
if candidate_k is omitted, runtime config supplies candidate_k
if top_k exceeds effective configured candidate_k, return request error
document_ids are canonical graph IDs
blank IDs are rejected
duplicate document IDs are rejected with HTTP 422
force_intent uses the shared enum
request query_date does not bypass temporal parsing/conflict rules
```

The backend must not clamp invalid values silently.

Pydantic/body validation and domain request validation use one stable error
envelope. FastAPI's default validation payload must be mapped to:

```python
class APIErrorResponse(BaseModel):
    code: Literal["REQUEST_VALIDATION_ERROR"]
    message: str
    details: list[ValidationIssue]
```

Validation details may expose field locations and safe messages, but never
credentials or internal exception representations.

## 9. API Response Contract

`RetrievalResponse` remains answer-free and should expose enough runtime audit
metadata to reproduce routing behavior.

Recommended contract:

```python
class RetrievalResponse(BaseModel):
    contract_version: str
    query: str
    intent: str
    strategy: str
    retrieval_mode: str
    executed_channels: list[str]
    force_intent_used: bool
    temporal_source: str
    decision_reason_code: str
    capability_status: str
    filters: dict[str, object]
    retrieved_units: list[RetrievedUnitDTO]
    graph_paths: list[GraphPathDTO]
    evidence: list[EvidenceDTO]
    metrics: dict[str, object]
```

The public source of truth is `RetrievalContext`. The backend mapper is a pure
projection and may only rename documented fields, serialize enums/dates, map
trusted source metadata, or omit internal-only fields.

It must not reclassify intent; recompute strategy, temporal source, capability,
or scores; rebuild graph paths; infer citations from content; query Neo4j to
fill missing retrieval metadata; or invent defaults that change meaning.

If required response data is absent from `RetrievalContext`, mapping fails with
a typed output-contract error. Fix the upstream contract rather than deriving
the value in the backend.

Mapping rules:

- Preserve canonical node IDs.
- Preserve `document_id`, Article/Clause ancestry, citation label, and deep link.
- Preserve graph path node order, relation order, and relation IDs.
- Preserve temporal validity metadata.
- Do not expose embeddings or full provider payloads.
- Do not invent URLs, citations, scores, or graph paths.
- Deterministic output order must match `RetrievalContext`.
- `Point` may appear in graph evidence but is lifted to Clause/Article as
  specified by retrieval runtime for result units.

## 10. Service Contract

Create one internal application port used by both the query API and Plan 11:

```python
class RetrievalApplicationPort(Protocol):
    async def retrieve_context(
        self,
        request: RetrievalRequest,
    ) -> RetrievalContext: ...
```

Add `GraphRAGRetrievalService` implementing this port. The query-facing
`RAGService.retrieve` maps the returned context to `RetrievalResponse`; answer
generation consumes the context directly. No code may reverse-map an API
response into `RetrievalContext`.

Responsibilities:

```text
1. Validate/map backend DTO into shared RetrievalRequest.
2. Execute synchronous runtime through an injected async runner.
3. Apply timeout/cancellation boundary.
4. Return the public RetrievalContext unchanged from the application port.
5. Map RetrievalContext to RetrievalResponse only at the query API boundary.
6. Propagate typed domain failures without converting them to empty results.
```

The service must not:

- perform intent routing itself;
- execute vector/full-text/graph channels itself;
- query Neo4j directly;
- construct or close the runtime per request;
- call an LLM;
- return fake data after dependency failures.

## 11. Async Boundary

`RetrievalRuntimeHandle.retrieve` is synchronous. It must never run directly on
the FastAPI event loop.

Canonical boundary uses one application-scoped bounded executor:

```python
executor = ThreadPoolExecutor(max_workers=settings.retrieval_max_concurrency)
future = loop.run_in_executor(executor, runtime.retrieve, retrieval_request)
try:
    context = await asyncio.wait_for(
        asyncio.shield(future),
        timeout=settings.retrieval_timeout_seconds,
    )
except TimeoutError:
    future.cancel()  # cancels only if queued; a running thread continues
    raise RetrievalTimeoutError(...)
```

An injected equivalent is acceptable for deterministic tests.

Timeout semantics must be documented truthfully:

```text
HTTP timeout stops waiting and returns 504.
Python cannot safely kill retrieval already running in a worker thread.
The worker may continue until the sync Neo4j/model call returns.
No retry is started after timeout.
Bounded executor size prevents timed-out workers growing without limit.
Pending work that has not started may be cancelled.
```

Provider/database-level timeouts should also be configured so abandoned workers
eventually finish.

Requirements:

- Configure a request timeout.
- Timeout returns a typed backend error and does not expose stack traces.
- Client cancellation stops waiting and does not start follow-up work.
- Do not swallow `CancelledError`.
- `BACKEND_RETRIEVAL_MAX_CONCURRENCY` bounds running calls per app instance.
- Queued requests remain inside the same request timeout budget.
- Request-local DTOs are never stored as mutable service state.
- Concurrent requests may share the immutable/runtime resources but not
  mutable request state.
- Do not close the runtime after each request.

## 12. Lifecycle Ownership

FastAPI lifespan owns the container. The container owns one retrieval runtime
handle and one bounded retrieval executor in GraphRAG mode.

Startup:

```text
validate backend settings
-> create RetrievalConfig and RetrievalApplicationSettings
-> create_retrieval_runtime(...)
-> verify enabled dependencies
-> construct GraphRAGRetrievalService
-> publish container to app.state
```

Shutdown:

```text
Container.close()
-> stop accepting new retrieval work
-> cancel queued work that has not started
-> wait up to shutdown grace for running workers
-> close RetrievalRuntimeHandle exactly once
-> shutdown bounded executor
-> close Neo4j driver through runtime callbacks
-> report cleanup error without leaking credentials
```

Partial startup failure must close every resource already created. Cleanup must
be idempotent.

Do not retain a second `_driver` field if the runtime handle already owns the
driver. There must be one clear owner.

If shutdown grace expires, report unfinished workers according to documented
backend policy. Do not claim that running threads were killed.

## 13. Typed Error Mapping

Map expected retrieval errors centrally, not with broad route-level handling.

Recommended mapping:

| Domain error | HTTP | Stable API code |
|---|---:|---|
| `RetrievalRequestError` | 422 | `RETRIEVAL_REQUEST_INVALID` |
| `TemporalRoutingError` | 422 | `TEMPORAL_ROUTING_INVALID` |
| `RetrievalCapabilityError` | 409 | `RETRIEVAL_CAPABILITY_UNSUPPORTED` |
| `RetrievalDependencyError` | 503 | `RETRIEVAL_DEPENDENCY_UNAVAILABLE` |
| `RetrievalExecutionError` | 502 | `RETRIEVAL_EXECUTION_FAILED` |
| request timeout | 504 | `RETRIEVAL_TIMEOUT` |
| unexpected failure | 500 | `INTERNAL_ERROR` |

Error response:

```python
class APIErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
```

Rules:

- Unsupported capability is not an empty result.
- Valid no-results remains HTTP 200 with `capability_status="no_results"`.
- Do not return exception repr, stack trace, password, URI credentials, vector,
  prompt, or provider response.
- Error codes are stable and tested.

## 14. Logging

Use structured logging fields:

```text
request_id
contract_version
intent
strategy
retrieval_mode
executed_channels
document_filter_count
latency_ms
result_count
error_code
```

Do not log:

```text
password/API key
full embeddings
full legal context by default
raw provider payload
stack trace in client response
```

## 15. Mock Compatibility

Mock mode remains available and must satisfy the same public API schema.

Rules:

- Mock response may use fixture data but must be deterministic.
- Mock service must not pretend that GraphRAG dependencies were checked.
- Response should identify `retrieval_mode="mock"` where the API contract
  permits it.
- Real and mock implementations must pass protocol/contract parity tests.
- Existing mock chat behavior remains unchanged in this plan.
- Existing frontend fields remain present: `query`, `retrieved_units`, `intent`,
  `retrieval_mode`, `graph_paths`, and `metrics`.
- New audit fields are additive and have deterministic mock fixture values.
- Mock and GraphRAG modes use the same validation/error envelope.
- `top_k` remains accepted and maps to runtime `final_k`.

## 16. Test Plan

### 16.1 DTO and mapping tests

- Valid request maps all filters and overrides.
- Empty/blank query rejected.
- Invalid limits rejected; no silent clamp.
- Duplicate and blank document IDs are rejected.
- `top_k > candidate_k` is rejected when both are supplied.
- `top_k` above effective configured candidate limit is a typed request error.
- Pydantic 422 failures use the stable API error envelope.
- Every `RetrievedUnit` field maps correctly.
- Graph path nodes, relations, relation IDs, and provenance survive mapping.
- Deep links use canonical IDs.
- Output ordering remains unchanged.
- No `answer` field appears.

### 16.2 Service tests

- Happy path returns mapped context.
- Empty result remains successful no-results.
- Unsupported capability propagates typed failure.
- Dependency and execution failures are not converted to empty results.
- Runtime is called once per request.
- Thread boundary is used.
- Timeout produces timeout error.
- Timeout does not claim to terminate a running worker.
- Worker concurrency never exceeds the configured maximum.
- Queued requests share the same timeout budget.
- Cancellation stops awaiting and schedules no retry.
- Concurrent calls do not share mutable request state.

### 16.3 Factory/lifecycle tests

- Mock startup creates no runtime/model/driver.
- GraphRAG startup assembles runtime exactly once.
- Enabled profile verifies only enabled dependencies.
- Partial startup failure cleans up executor and runtime/driver.
- Shutdown closes runtime exactly once.
- Shutdown behavior with one in-flight worker is tested.
- Repeated close is safe.
- No resource is created on module import.

### 16.4 API tests

- Query happy path is HTTP 200 and schema-valid.
- Request validation is HTTP 422.
- Capability error is distinguishable from no-results.
- Dependency failure is HTTP 503.
- Execution failure is HTTP 502.
- Timeout is HTTP 504.
- Unexpected error does not leak internal details.
- Async route does not call blocking runtime directly.

### 16.5 Disposable Neo4j integration

- Use `localhost:7688`, not development port 7687.
- Use explicit integration opt-in.
- Query pilot graph read-only.
- Capture legal and embedding digests before/after.
- Assert both digests unchanged.
- Verify at least one factual query returns canonical Article/Clause citations.
- Verify document filter works without ID-prefix assumptions.
- Verify no-results and one supported temporal request.
- Integration test must not create or delete pilot data.

## 17. Static Architecture Tests

Add tests that fail if:

- API routes import Neo4j or retrieval concrete adapters.
- Service imports channel implementations directly.
- Retrieval/infrastructure imports backend modules.
- More than one backend composition path constructs retrieval runtime.
- Module import creates a driver/model/client.

## 18. Execution Order

```text
1. Freeze backend request/response/error DTOs.
2. Freeze retrieval-to-API mapping rules.
3. Implement GraphRAGRetrievalService with injected runtime and async runner.
4. Implement centralized typed error mapping.
5. Extend settings without duplicating retrieval policy.
6. Update container to assemble one runtime in graphrag mode.
7. Implement lifecycle cleanup and partial-failure handling.
8. Update query route only as needed for DTO/error boundary.
9. Add unit and API tests.
10. Add static dependency tests.
11. Run fast tests and static checks.
12. Run read-only disposable-Neo4j backend integration tests.
13. Update backend README and environment examples.
14. Produce development integration evidence.
```

## 19. Verification Commands

```bash
uv run pytest -q
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
git diff --check
```

Backend contract tests should be runnable from repository root with a stable
command. If current imports require `PYTHONPATH`, fix/package the test command
explicitly rather than relying on the developer shell.

Disposable integration example:

```bash
RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest tests/integration -q -m retrieval_readonly
```

Do not run against port 7687.

## 20. Acceptance Matrix

| ID | Requirement | Evidence |
|---|---|---|
| BI-01 | One backend composition path uses existing retrieval factory | Static test + code review |
| BI-02 | `/api/v1/query` returns real `RetrievalContext` mapping | API test |
| BI-03 | Response contains no answer generation | Schema test |
| BI-04 | Sync retrieval runs outside async event loop | Service/API test |
| BI-05 | Timeout does not falsely claim worker termination | Failure tests |
| BI-06 | Typed retrieval errors map to stable HTTP errors | API tests |
| BI-07 | No-results differs from unsupported capability | Contract tests |
| BI-08 | Runtime/driver lifecycle closes exactly once | Lifecycle tests |
| BI-09 | Mock mode requires no GraphRAG dependency | Startup test |
| BI-10 | Document/date/intent filters reach runtime unchanged | Mapping test |
| BI-11 | Citations, deep links, paths, and provenance survive mapping | Mapping test |
| BI-12 | Cypher is absent from routes/services | Static test |
| BI-13 | Pilot read-only integration preserves graph digests | Integration evidence |
| BI-14 | Full tests, Ruff, format, and diff checks pass | Command output |
| BI-15 | App-scoped executor enforces configured concurrency | Concurrency test |
| BI-16 | API mapper is a pure RetrievalContext projection | Mapping/static test |
| BI-17 | Mock frontend fields and stable 422 schema remain compatible | API tests |

## 21. Stop Conditions

Stop and report instead of weakening the contract when:

- retrieval official source state is unknown or tests are failing;
- retrieval contract/source commit is not frozen for the integration run;
- GraphRAG mode can only work by hard-coding pilot IDs;
- backend needs a second orchestration path;
- sync retrieval cannot be moved off the event loop;
- runtime cleanup ownership is ambiguous;
- typed failure can only be made green by returning fake/empty data;
- integration target is not proven disposable/read-only;
- implementation would require answer generation changes.

Pending official retrieval evaluation does not by itself block pilot backend
integration. Pilot integration is allowed when:

```text
retrieval public contract is frozen
source commit is recorded
fast tests pass
required pilot dependency smoke/integration checks pass
reports keep official evaluation and milestone status pending
```

It is not allowed to call the integration production-ready or close Milestone B
before official evaluation is completed.

## 22. Deliverables

- Real GraphRAG retrieval service.
- Updated backend container/settings/query API contracts.
- Centralized typed error mapping.
- Mapping, service, API, lifecycle, and architecture tests.
- Read-only disposable-Neo4j integration evidence.
- Updated backend README/config documentation.

## 23. Completion Status Template

```text
Backend retrieval integration: IMPLEMENTED
Fast tests: PASS
Runtime-v2 read-only integration tests: NOT RUN
Answer generation: IMPLEMENTED UNDER PLAN 11
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
Known limitations: ...
```

## 24. Handoff to Answer Generation

Plan 11 may start implementation only after this plan provides a stable service
boundary that can return a validated `RetrievalContext` for a request. It does
not require Gate 7 to be closed for pilot development, but no final milestone
claim is allowed while Gate 7/M3-B13 remain open.

## 25. Historical Implementation Result (runtime-v1, 2026-07-14)

```text
Backend retrieval integration: IMPLEMENTED
Fast tests: PASS (313 tests; integration excluded by default)
Read-only backend/retrieval integration: PASS (2 tests on disposable port 7688)
Ruff check: PASS
Ruff format check: PASS
git diff --check: PASS
Source commit: the commit containing this implementation result
Development evidence: results/retrieval/backend_retrieval_integration_development.md

Answer generation: IMPLEMENTED LATER UNDER PLAN 11
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```

This result permits Plan 11 pilot implementation against the stable
`RetrievalApplicationPort.retrieve_context()` boundary. It does not promote the
backend to production, close corpus gates, or constitute Milestone B evidence.

## 26. Current Alignment (runtime-v2, 2026-07-17)

```text
Backend retrieval integration: IMPLEMENTED
Answer generation: IMPLEMENTED UNDER PLAN 11
Retrieval contract: retrieval-runtime-v2
Graph-path direction and temporal safety: IMPLEMENTED UNDER PLAN 14
Runtime-v2 read-only Neo4j regression: NOT RUN
Official runtime-v2 evaluation: NOT STARTED
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
```

The runtime-v1 test counts above remain historical evidence. They must not be
used as runtime-v2 acceptance without rerunning the read-only integration and
evaluation workflows against the current contract.
