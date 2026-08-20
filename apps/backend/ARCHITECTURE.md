# Component: Backend API (`apps/backend/`)

> Tài liệu kiến trúc/thiết kế. Để chạy server (mock/graphrag mode), xem SSE contract, biến môi trường, hoặc chạy test tích hợp — xem [README.md](README.md) trong thư mục này.

> FastAPI app — nơi lắp ráp (compose) [Retrieval](../../src/retrieval/README.md) + [Generation](../../src/generation/README.md) + [Infrastructure](../../src/infrastructure/README.md) thành các HTTP endpoint thật, quản lý hội thoại nhiều lượt, auth, và observability.

## Cấu trúc

| Thư mục/File | Trách nhiệm |
|---|---|
| `main.py` | FastAPI app factory (`create_app`) — wire settings, lifespan startup/shutdown, CORS, error handlers, đăng ký route. |
| `container.py` | `Container`/`build_container()` — **composition root** của toàn app (chế độ `mock` vs GraphRAG đầy đủ). |
| `dependencies.py` | FastAPI `Depends` accessor lấy service từ `request.app.state.container`. |
| `settings.py` | `Settings` tập trung, env-driven, tạo 1 lần trong `main.py`. |
| `api/routes/` | Các HTTP endpoint (xem bảng dưới). |
| `api/models.py` | Pydantic request/response schema, bao gồm encode cho SSE. |
| `api/error_handlers.py` | Error envelope ổn định cho toàn API. |
| `services/` | `interfaces.py` (port: `QueryService`, `ChatService`, `RAGService`...), `graphrag_retrieval_service.py`, `retrieval_runner.py`, `document_browser_service.py`, `mock_rag_service.py`, `retrieval_mapping.py`. |
| `conversation/service.py` | `ConversationChatService` (826 dòng) — orchestrator chính của 1 lượt chat. |
| `resolution/` | Resolve tham chiếu mơ hồ (anaphora), tra cứu canonical entity trên Neo4j, clarification, rewrite câu hỏi. |
| `query_processing/` | Adapter cho `QueryProcessor` (5-field) + fan-out logic. |
| `persistence/` | SQLAlchemy engine/model/repository cho conversation store, debug trace store, advisory locking. |
| `auth/` | Hash mật khẩu, ký cookie principal (user đăng ký vs guest ẩn danh). |
| `providers/` | Client LLM (Gemini/OpenAI/Ollama) phía backend. |
| `observability/` | `trace.py` (log JSON có redaction), `llm.py`, `rag.py` (telemetry retrieval/generation). |
| `alembic/` | Migration DB (conversation store, users/accounts, turn debug trace). |

## HTTP endpoints (`/api/v1`)

| Route group | Endpoint | Ý nghĩa |
|---|---|---|
| `auth` | `POST /auth/register`, `/login`, `/logout`, `GET /me`, `POST /claim-guest` | Đăng ký/đăng nhập/đăng xuất, lấy user hiện tại, gộp hội thoại guest ẩn danh vào tài khoản đã đăng ký |
| `chat` | `POST /chat` | Hội thoại grounded, streaming SSE |
| `query` | `POST /query` | Chỉ retrieval, không sinh câu trả lời — trả `RetrievalContext` thô |
| `documents` | `GET /documents`, `/documents/{id}`, `/documents/{id}/graph`, `/articles/{id}` | Document browser (Explorer UI) phân trang + tra cứu điều luật/đồ thị |
| `conversations` | `GET ""`, `GET /{id}`, `PATCH /{id}`, `POST /{id}/generate-title`, `DELETE /{id}` | CRUD lịch sử hội thoại |

## Composition (`container.build_container()`)

Chế độ `mock`: trả về `MockRAGService` cho mọi thứ (dev/test không cần Neo4j thật).

Chế độ thật:
1. Build `RetrievalConfig`/`RetrievalApplicationSettings` → gọi `src.application.retrieval_factory.create_retrieval_runtime` (Neo4j-backed) → `runtime`.
2. Bọc `runtime` bằng `BoundedRetrievalRunner` + `GraphRAGRetrievalService`; có thể build thêm Gemini query planner (cho MULTI_HOP).
3. Nếu `answer_generation_enabled`: build `GenerationConfig`/`AnswerApplicationSettings` → `src.application.answer_factory.create_answer_generator`, bọc thêm `TracedAnswerProvider`/`TracedAnswerGenerator` (observability).
4. `_build_conversation_chat()` compose `ConversationChatService` từ: Postgres conversation store, `ReferenceResolver`/`StructuredRewriter` (dùng driver canonical-lookup Neo4j riêng), retrieval service, answer generator, và tuỳ chọn `QueryProcessorAdapter` (bọc `src.retrieval.nlu.query_processor.QueryProcessor`).
5. Toàn bộ đặt trên `app.state.container` lúc FastAPI lifespan startup, có cleanup đối xứng khi `close()`/khởi tạo lỗi.

Đây chính là điểm nối giữa 3 tầng [Retrieval](../../src/retrieval/README.md), [Generation](../../src/generation/README.md), [Infrastructure](../../src/infrastructure/README.md) thành 1 service thật.

## Conversation service — 1 lượt chat diễn ra thế nào

```
Xác thực + idempotency pre-check
   → acquire advisory lock (per conversation)
   → begin turn + load history context
   → resolve reference (anaphora/explicit) — deterministic
   → clarification-or-rewrite câu hỏi
   → (tuỳ chọn) decompose câu hỏi thành nhiều sub-query
   → retrieval (GraphRAGRetrievalService)
   → generation (1 pass, có self-repair nội bộ ở AnswerGenerator)
   → grounding validation
   → persist turn vào Postgres
   → release lock
   → replay lại dưới dạng buffered SSE từ snapshot đã lưu
```

Test coverage: unit thuần (`test_conversation_service.py`, mock resolver/retrieval/generator) + integration thật với Postgres (`tests/conversation/test_service_integration.py`, fake retrieval/generation) + auth-linked history (`test_auth_history.py`) + repository/schema/startup.

## Observability (`observability/rag.py`)

Log JSON có redaction qua `observability.trace.log_event` ở từng bước RAG:
- `log_retrieval_result`/`log_retrieval_failure` — event `retrieval.route`/`.seed`/`.graph`/`.ranking`/`.subquery` (intent, temporal resolution, số hit, latency, top units).
- `TracedAnswerGenerator` — event `generation.context`/`.call`/`.grounding`/`.projection` (số unit/evidence/citation, lý do cannot-answer/insufficiency, latency).
- `TracedAnswerProvider` — event `generation.llm` (prompt/system-instruction/raw output đã redact, số citation/statement/reasoning-path).

Thay đổi gần nhất (commit `a0e2bdf`, 2026-08-20): sửa `TracedAnswerProvider.generate_structured` đổi `statement.citation_ids` → `statement.citations` khi tính `citation_reference_count` — theo kịp schema `StatementCitation` mới ở [Generation](../../src/generation/README.md).

## Kiểm chứng (test evidence)

```
uv run pytest apps/backend/tests/ -q
→ 223 passed, 38 skipped
```

Test skip chủ yếu là các test tích hợp yêu cầu Postgres/Neo4j thật đang không sẵn có trong môi trường chạy test hiện tại (đánh dấu qua `pytest.mark.skipif`), không phải test bị vô hiệu hoá tuỳ tiện.

## Liên quan

- [Retrieval](../../src/retrieval/README.md), [Generation](../../src/generation/README.md), [Infrastructure](../../src/infrastructure/README.md) — 3 tầng được compose tại đây.
- [Frontend](../frontend/ARCHITECTURE.md) — client tiêu thụ các endpoint `/chat`, `/documents`, `/conversations`.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
