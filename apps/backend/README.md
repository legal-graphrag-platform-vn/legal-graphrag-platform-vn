# Legal GraphRAG FastAPI Backend

Backend exposes retrieval evidence from the existing retrieval runtime. Plan 10
does not implement answer generation: `POST /api/v1/query` never returns an
`answer` field, and real `/chat` remains unavailable in GraphRAG mode.

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

```bash
APP_MODE=graphrag \
NEO4J_URI=bolt://localhost:7688 \
NEO4J_USER=neo4j \
NEO4J_PASSWORD='<password>' \
BACKEND_RETRIEVAL_TIMEOUT_SECONDS=30 \
BACKEND_RETRIEVAL_MAX_CONCURRENCY=4 \
BACKEND_RETRIEVAL_SHUTDOWN_GRACE_SECONDS=5 \
PYTHONPATH=apps/backend \
uv run uvicorn main:app --port 8000
```

Retrieval channel/model settings remain owned by `RetrievalConfig` and
`RetrievalApplicationSettings`, including `RETRIEVAL_*` and `EMBEDDING_*`.
There is no default document filter.

GraphRAG mode is pilot development on the current graph. Gate 7 and M3-B13
remain open, Milestone A is not passed, and Milestone B acceptance has not
started.

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

## Verification

From repository root:

```bash
uv run pytest -q
uv run ruff check apps/backend src/retrieval src/infrastructure/neo4j/retriever_repo.py
uv run ruff format --check apps/backend src/retrieval src/infrastructure/neo4j/retriever_repo.py
git diff --check
```

Read-only disposable-Neo4j integration is opt-in and must target port `7688`:

```bash
RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest tests/integration/test_retrieval_online.py \
  -q -m retrieval_readonly
```
