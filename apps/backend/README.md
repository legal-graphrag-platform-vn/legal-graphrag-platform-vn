# Legal GraphRAG FastAPI Backend

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the component overview (structure,
endpoints, composition root, test evidence).

Backend exposes retrieval evidence and an opt-in grounded answer profile.
`POST /api/v1/query` remains retrieval-only. `POST /api/v1/chat` retrieves once,
generates a structured answer, validates every citation/path/temporal assertion,
and only then emits SSE answer chunks.

## Runtime Modes

### Mock

`APP_MODE=mock` loads deterministic fixtures for frontend development. It does
not create a Neo4j driver, embedding model, reranker, or retrieval runtime.

```bash
APP_MODE=mock PYTHONPATH=apps/backend \
  uv run uvicorn main:app --reload --port 8000
```

### GraphRAG

`APP_MODE=graphrag` constructs one retrieval runtime and one bounded executor
for the FastAPI lifespan. It fails startup when enabled retrieval dependencies
or required Neo4j configuration are unavailable; it never falls back to mock.
Install the optional provider dependencies before enabling answers or query
planning:

```bash
uv sync --group embedding --group llm
```

```bash
APP_MODE=graphrag \
NEO4J_URI=bolt://localhost:7688 \
NEO4J_USER=neo4j \
NEO4J_PASSWORD='<password>' \
BACKEND_RETRIEVAL_TIMEOUT_SECONDS=30 \
BACKEND_RETRIEVAL_MAX_CONCURRENCY=4 \
BACKEND_RETRIEVAL_SHUTDOWN_GRACE_SECONDS=5 \
ANSWER_GENERATION_ENABLED=true \
QUERY_PLANNING_ENABLED=false \
ANSWER_PROVIDER=gemini \
ANSWER_MODEL=gemini-3.1-flash-lite \
GEMINI_API_KEY='<key>' \
PYTHONPATH=apps/backend \
uv run uvicorn main:app --port 8000
```

Retrieval channel/model settings remain owned by `RetrievalConfig` and
`RetrievalApplicationSettings`, including `RETRIEVAL_*` and `EMBEDDING_*`.
There is no default document filter.

When `ANSWER_GENERATION_ENABLED=false`, GraphRAG `/query` remains available and
`/chat` returns a typed feature-unavailable error. The answer provider is never
constructed in that profile.

GraphRAG mode is pilot development on the current graph. Gate 7 and M3-B13
remain open, Milestone A is not passed, and Milestone B acceptance has not
started.

### Query-planning profile

`QUERY_PLANNING_ENABLED=false` is the default. In this profile the backend does
not construct a planner. Generic retrieval still runs, but MULTI_HOP has no
trusted reasoning requirement, so `/chat` must fail-closed; this is not planned
multi-hop support.

When the flag is enabled in development, the backend runs `prepare` on the
bounded retrieval worker, calls the planner asynchronously on the FastAPI event
loop only for the `MULTI_HOP` intent, then runs bind/exact execution on the
bounded worker. Other intents never call the planner. QG-1 currently still fails
its preregistered thresholds, so the flag is not enabled by default and this
profile must not be used for a production claim.

| Variable | Default | Range / enable semantics |
|---|---:|---|
| `QUERY_PLANNING_ENABLED` | `false` | `true` only for development/evaluation; requires vector + full-text and `GEMINI_API_KEY` |
| `QUERY_PLANNER_PROVIDER` | `gemini` | currently only `gemini` is supported |
| `QUERY_PLANNER_MODEL` | `gemini-3.1-flash-lite` | non-empty model string |
| `QUERY_PLANNER_TIMEOUT_SECONDS` | `30` | `0 < value <= 300` |
| `QUERY_PLANNER_MAX_CONCURRENCY` | `2` | `1..16` |
| `QUERY_PLANNER_MAX_RETRIES` | `2` | `0..5` |
| `QUERY_PLANNER_MAX_OUTPUT_TOKENS` | `1024` | `128..4096` |
| `QUERY_PLANNER_TEMPERATURE` | `0` | `0..1` |

Planner provider failures use stable API errors:

| HTTP | Code | Condition |
|---:|---|---|
| 504 | `QUERY_PLANNING_TIMEOUT` | planner exceeded timeout |
| 503 | `QUERY_PLANNING_UNAVAILABLE` | provider/config/dependency unavailable |
| 502 | `QUERY_PLANNING_OUTPUT_INVALID` | provider output failed strict plan schema |

Binding/no-path failures never call the answer provider. The runtime keeps a
typed `PlanReasonCode` in the retrieval context and the generation gate returns
cannot-answer.

## Query API

```http
POST /api/v1/query
Content-Type: application/json
```

```json
{
  "query": "Quyền thành lập doanh nghiệp được quy định thế nào?",
  "top_k": 5,
  "candidate_k": 20,
  "document_ids": ["ldn_2020"],
  "query_date": "2022-07-01",
  "enable_reranker": false
}
```

`top_k` is the API name for runtime `final_k`; `candidate_k` maps to runtime
`top_k`. Invalid cross-field limits and duplicate document IDs return the
stable `REQUEST_VALIDATION_ERROR` envelope. Typed retrieval failures use stable
4xx/5xx codes instead of fake empty results.

Timeout means the HTTP request stops waiting. Python cannot kill a sync call
already running in a worker thread; bounded concurrency and provider/database
timeouts prevent unbounded abandoned work.

## Chat SSE

The SSE order is `metadata`, validated `token` chunks, trusted `citation`
events, then `done`. No model token is sent before claim-level grounding passes.
Conversation history is bounded and cannot add evidence or rewrite retrieval.

## Verification

From repository root:

```bash
uv run pytest -q
uv run ruff check apps/backend src/generation src/retrieval src/infrastructure
uv run ruff format --check apps/backend src/generation src/retrieval src/infrastructure
git diff --check
```

### PostgreSQL conversation integration tests

The conversation fixtures reset the entire `public` schema. Run them only
against the dedicated disposable PostgreSQL service, never the development or
server database:

```bash
make conversation-db-up
make test-conversation-db
make conversation-db-down
```

The local test DSN is
`postgresql+asyncpg://graphrag_test:graphrag_test@127.0.0.1:55432/graphrag_conversations_test`.
The container stores PostgreSQL data in `tmpfs`, so stopping it discards the
test database. Override only the host port with
`CONVERSATION_TEST_POSTGRES_PORT`; if changed, also pass the matching
`CONVERSATION_TEST_DATABASE_URL` to `make test-conversation-db`.

Read-only disposable-Neo4j integration is opt-in and must target port `7688`:

```bash
RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest tests/integration/test_retrieval_online.py \
  -q -m retrieval_readonly
```
