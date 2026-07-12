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
│   ├── interfaces.py          # RAGService Protocol
│   └── mock_rag_service.py    # Mock implementation (APP_MODE=mock)
├── mock_data/                 # JSON fixtures cho mock mode
└── tests/
    └── test_contracts.py      # 25 contract tests — chạy: pytest tests/ -v
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

### 3.4. Sync calls trong async routes

```python
from starlette.concurrency import run_in_threadpool

result = await run_in_threadpool(sync_function, arg1, arg2)
```

### 3.5. Comment bước (bắt buộc)

```python
# 1.   Validate input
# 2.   Fetch từ service
# 3.   Transform DTO
# 4.   Return response
```

### 3.6. Không viết Cypher trong routes

Cypher queries phải nằm trong `src/infrastructure/neo4j/`. Routes chỉ gọi service.

---

## 4. APP_MODE

| Mode | Mô tả |
|---|---|
| `mock` | Không cần Neo4j. Load fixture từ `mock_data/`. Dùng để dev FE. |
| `graphrag` | 🔒 Locked — cần Milestone A pass. Cần NEO4J_*, LLM_* config. |

---

## 5. Contract tests

```bash
cd apps/backend && PYTHONPATH=. pytest tests/ -v
# Expected: 25 passed
```

Tests cover: startup, SSE format, SSE unicode, query schema, document list/filter/detail/graph/article, ontology parity.
