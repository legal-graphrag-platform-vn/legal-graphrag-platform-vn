# Backend Developer Guidelines

Backend dùng **FastAPI** (không còn Flask).

---

## 1. Cấu trúc thư mục

```text
apps/backend/
├── main.py                    # FastAPI app factory — create_app(settings)
├── settings.py                # pydantic-settings — APP_MODE, NEO4J_*, LLM_*, CORS_ORIGINS
├── container.py               # DI Container — build_container(settings) → app.state.container
├── dependencies.py            # FastAPI Depends helpers — get_rag_service(request)
├── api/
│   ├── models.py              # Pydantic request/response schemas (contract)
│   └── routes/
│       ├── chat.py            # POST /api/v1/chat — SSE stream
│       ├── query.py           # POST /api/v1/query — retrieval (non-streaming)
│       └── documents.py       # GET /api/v1/documents, /articles
├── services/
│   ├── interfaces.py          # API and retrieval application ports
│   ├── graphrag_retrieval_service.py
│   ├── graphrag_answer_service.py
│   ├── retrieval_mapping.py
│   ├── retrieval_runner.py
│   └── mock_rag_service.py    # Mock implementation (APP_MODE=mock)
├── mock_data/                 # JSON fixtures cho mock mode
└── tests/
    └── ...                    # contract, lifecycle and boundary tests
```

---

## 2. Chạy backend

```bash
# Từ apps/backend/
PYTHONPATH=. uvicorn main:app --reload --port 8000
```

Hoặc từ project root với uv:

```bash
cd apps/backend && PYTHONPATH=. uv run uvicorn main:app --reload --port 8000
```

Docs: http://localhost:8000/docs

---

## 3. Quy tắc coding

### 3.1. App factory — không instantiate Settings nhiều lần

```python
# ✅ Đúng
app = create_app(Settings())

# ❌ Sai — Settings() trong mỗi route
@router.get("/")
def route():
    settings = Settings()  # KHÔNG làm thế này
```

### 3.2. DI — lấy service từ app.state

```python
def get_rag_service(request: Request) -> RAGService:
    return request.app.state.container.rag_service
```

### 3.3. SSE format — bắt buộc dùng named events

```text
event: metadata
data: {"sources": [...], "intent": "factual", "retrieval_mode": "mock"}

event: token
data: {"content": "Vốn "}

event: error
data: {"code": "STREAM_ERROR", "message": "..."}

event: done
data: {}
```

Dùng `encode_sse(event, data)` từ `api/models.py`. Không tự format string.

### 3.4. Sync retrieval trong async routes

Routes call `QueryService`. Only the application-scoped
`BoundedRetrievalRunner` may move the sync retrieval runtime to worker threads;
do not create a per-request executor or call the runtime directly from a route.
Answer providers are async and application-scoped. `/chat` must generate and
validate the complete structured candidate before emitting any token event.

### 3.5. Không viết Cypher trong routes

Cypher queries phải nằm trong `src/infrastructure/neo4j/`. Routes chỉ gọi service.

---

## 4. APP_MODE

| Mode | Mô tả |
|---|---|
| `mock` | Không cần Neo4j. Load fixture từ `mock_data/`. Dùng để dev FE. |
| `graphrag` | Pilot retrieval and optional grounded-answer development. |

GraphRAG development does not close Gate 7/M3-B13 or pass Milestone A. Answer
generation requires explicit `ANSWER_GENERATION_ENABLED=true`; no provider is
created in retrieval-only mode.

---

## 5. Contract tests

```bash
uv run pytest -q
```

Tests cover: startup, SSE format, SSE unicode, query schema, document list/filter/detail/graph/article, ontology parity.
