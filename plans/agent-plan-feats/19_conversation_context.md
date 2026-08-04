Plan 19 — Conversation Context Resolution before Retrieval

  Status: IMPLEMENTED (backend + minimal frontend). This plan is the AUTHORITY for
  conversation context resolution, server-owned history, idempotency, advisory
  locking, deterministic reference resolution and structured rewriting. It
  supersedes the "follow-up query rewriting/retrieval is deferred" clause of Plan
  11 §"Conversation history policy for v1".

  Deviations recorded during implementation (see backend README "Conversation
  context store"):
  - SSE always returns HTTP 200; an in-flight duplicate turn is signalled by
    `done {status: "processing", retry_after_ms}` rather than a literal HTTP 202.
  - The structured rewriter's Gemini fallback port is wired with `llm=None`
    (rule-only) for the MVP; the adapter is deferred, not the port.
  - `Neo4jCanonicalLookup` is wired but its live verification against a seeded
    graph is deferred.
  - Fine-tuning remains out of the MVP.

  ## 1. Mục tiêu và invariant

  Luồng chính thức:

  Authenticate signed browser principal
  → idempotency check bằng client_turn_id
  → acquire conversation advisory lock
  → persist user turn
  → load server-owned HistoryContext
  → deterministic reference resolution
      ├── clarification
      └── standalone query
          → retrieval đúng một lần
          → generation bằng cùng query
          → grounding
          → persist answer, citations và focuses
  → release lock
  → buffered SSE từ dữ liệu đã persist

  Invariant:

  - PostgreSQL là source of truth cho transcript và context.
  - conversation_id chỉ là identity; mọi thao tác phải kiểm tra owner.
  - client_turn_id ngăn retry tạo duplicate turn/provider call.
  - Resolver deterministic; LLM chỉ rewrite từ canonical candidate đã resolve.
  - Retrieval và generation luôn dùng cùng standalone_query.
  - Clarification không retrieval, generation hoặc cập nhật focus.
  - Chỉ citations sau grounding thành công mới trở thành focus.
  - Không sửa context_projection.py, ontology hoặc retrieval runtime.
  - Fine-tuning nằm ngoài MVP.

  ## 2. API, authorization và idempotency

  ### Request contract

  class ChatRequest:
      conversation_id: UUID
      client_turn_id: UUID
      message: str
      document_ids: list[str]
      query_date: date | None
      force_intent: IntentType | None
      enable_reranker: bool | None

  Loại bỏ history; không giữ compatibility branch nhận history từ client.

  ### Signed anonymous principal

  Backend cấp cookie graphrag_anon_principal chứa:

  version
  principal UUID
  issued_at
  HMAC-SHA256 signature

  Contract:

  - Secret ANONYMOUS_PRINCIPAL_SIGNING_KEY tối thiểu 32 bytes, bắt buộc khi grounded chat được bật.
  - Cookie HttpOnly, SameSite=Lax, Path=/, TTL 180 ngày; Secure cấu hình bật ở deployment.
  - Frontend dùng credentials: "include" cho mọi API request.
  - CORS tiếp tục dùng explicit origin và allow_credentials=True.
  - Principal hợp lệ được map thành:
      - owner_kind = ANONYMOUS
      - owner_principal_id = principal UUID

  - Conversation thuộc principal khác trả CONVERSATION_NOT_FOUND, không tiết lộ conversation có tồn tại.
  - Tất cả repository operations bắt buộc nhận và kiểm tra owner.

  ### Idempotency

  Database enforce:

  UNIQUE (conversation_id, client_turn_id)

  Trước khi xử lý:

  - Turn COMPLETED, CANNOT_ANSWER hoặc NEEDS_CLARIFICATION: replay response đã persist bằng buffered SSE.
  - Turn PROCESSING: trả HTTP 202 với metadata và done(status=processing, retry_after_ms=1000).
  - Turn FAILED: replay typed persisted error; muốn chạy lại phải dùng client_turn_id mới.
  - Race khi hai request cùng ID được chặn bởi unique constraint và re-read turn hiện hữu.
  - Không branch retry nào được gọi Neo4j hoặc model lần thứ hai.

  Frontend tạo client_turn_id một lần khi tạo user message và tái sử dụng đúng ID cho transport retry.

  ## 3. PostgreSQL và concurrency

  Thêm SQLAlchemy asyncio, asyncpg, Alembic, PostgreSQL 16 vào compose thường và DATABASE_URL=postgresql+asyncpg://.... Không thay disposable M3 compose.

  Migration tạo đúng sáu bảng:

  1. conversations
      - id, owner_kind, owner_principal_id
      - next_user_turn_no
      - timestamps

  2. conversation_turns
      - id, conversation_id, client_turn_id
      - user_turn_no
      - status: PROCESSING|COMPLETED|CANNOT_ANSWER|NEEDS_CLARIFICATION|FAILED
      - resolution_status: RESOLVED|AMBIGUOUS|UNRESOLVED
      - resolution_reason_code
      - standalone_query
      - error_code
      - validated response_snapshot JSONB để replay
      - timestamps
      - unique (conversation_id, client_turn_id)

  3. conversation_messages
      - id, turn_id, conversation_id
      - role, kind, content, ordinal, timestamp
      - content không giữ processing lifecycle

  4. message_citations
      - assistant message ID, unit_id, citation ordinal
      - canonical document/unit metadata snapshot
      - unique (message_id, unit_id)

  5. grounded_focuses
      - unique (conversation_id, node_id)
      - node/document type, canonical labels và document metadata
      - last_grounded_user_turn_no
      - citation_order

  6. pending_clarifications
      - unique conversation_id
      - source turn, mode SELECT|RESTATE, question
      - candidates JSONB, tối đa 5 item, schema-validated khi đọc/ghi

  Repository port:

  find_turn_by_client_id
  begin_turn_and_load_context
  persist_clarification
  persist_grounded_answer
  mark_turn_failed
  clear_pending
  replay_turn

  ### Lock boundary

  Lock key là signed 64-bit integer tạo deterministically từ tám byte đầu của SHA-256(conversation_id.bytes).

  Acquire session-level advisory lock
  → short begin-turn transaction
  → commit
  → retrieval/Gemini ngoài transaction
  → short finalize transaction
  → release advisory lock trong finally

  - Không giữ SQL transaction mở trong lúc gọi Neo4j/Gemini.
  - Acquire bằng pg_try_advisory_lock polling đến deadline 1 giây.
  - Hết deadline trả typed CONVERSATION_BUSY.
  - PostgreSQL connection giữ session lock trong toàn lượt và luôn được trả về pool sau unlock.
  - Pool mặc định 6 connections, max_overflow=0; startup validate pool size không nhỏ hơn configured answer concurrency.
  - Conversation khác nhau vẫn chạy đồng thời.
  - Cancellation/failure đánh dấu turn FAILED nếu begin-turn đã commit, rồi release lock.
  - Startup verify connectivity và Alembic revision; không tự động migrate production database.

  ## 4. Context resolution và answer orchestration

  ### HistoryContext

  class HistoryContext:
      recent_messages: tuple[HistoryMessage, ...]
      grounded_focuses: tuple[GroundedFocus, ...]
      pending_clarification: PendingClarification | None

  - Persist toàn transcript.
  - Effective recent history lấy tối đa 6 completed messages/4.000 ký tự, theo chronological order.
  - Exclude PROCESSING và FAILED.
  - Recent messages chỉ phục vụ hiểu/rewrite ngôn ngữ; không thêm candidate, filter hoặc evidence.

  Focus policy:

  MAX_GROUNDED_FOCUSES = 5
  FOCUS_TTL_USER_TURNS = 5

  expired khi:
  current_user_turn_no - last_grounded_user_turn_no > 5

  - Upsert chỉ từ AnswerResponse.citations sau grounding.
  - Deduplicate node_id; focus được dùng lại refresh user-turn number.
  - Stable order:

  last_grounded_user_turn_no DESC
  → citation_order ASC
  → node_id ASC

  - cannot_answer, clarification và failure không cập nhật focus.

  ### Candidate universe

  Nếu có pending:

  candidate universe = pending.candidates snapshot

  Không được mở rộng bằng history hoặc current explicit mention.

  Nếu không có pending:

  candidate universe =
  explicit canonical candidates từ current message
  + effective grounded focuses cho anaphora

  Explicit resolution:

  - Parser deterministic nhận số văn bản, tên/năm luật, Điều, Khoản, Điểm.
  - Read-only canonical lookup port truy vấn Neo4j bằng parameterized query và xác minh parent chain.
  - Không suy canonical identity từ ID prefix.
  - Một explicit match được ưu tiên hơn anaphoric focus.
  - Nhiều explicit match tạo AMBIGUOUS.
  - Explicit structural mention không tồn tại tạo UNRESOLVED/REFERENT_NOT_FOUND.
  - Câu độc lập không có context-dependent reference dùng nguyên message, không bắt buộc candidate lookup.

  Anaphora resolution:

  - Nhận diện “điều này”, “khoản đó”, “văn bản trên”, “quy định vừa nêu”, “nó” và các biến thể normalized.
  - Lọc focus theo expected legal-unit type.
  - Một match: RESOLVED.
  - Nhiều match: AMBIGUOUS; recency không tự phá ambiguity.
  - Không match: UNRESOLVED/REFERENT_NOT_FOUND.
  - Không có anaphora: UNRESOLVED/NO_REFERENCE_REQUIRED, đi tiếp như standalone.

  Pending clarification:

  - SELECT: chỉ nhận số thứ tự hoặc normalized candidate label; input sai hỏi lại cùng snapshot.
  - RESTATE: dùng khi không có candidate; lượt sau phải là câu độc lập.
  - “Hủy”/“bỏ qua” clear pending và không retrieval.
  - Question được tạo deterministic từ candidate labels, không gọi model.

  ### Rule-assisted structured rewriter

  - Standalone query: không gọi model.
  - Referential rewrite đơn giản: rule template chèn canonical citation/document label.

  - Trường hợp cần diễn đạt tiếng Việt tự nhiên: Gemini structured-output fallback.
  - Model input chỉ gồm current message, bounded recent messages và đúng resolved candidate.
  - Output:

  class RewriteCandidate:
      resolved_candidate_id: str
      standalone_query: str

  Validation:

  - ID phải bằng allowlisted resolved candidate ID.
  - Query không rỗng, tối đa 4.000 ký tự.
  - Query phải chứa canonical anchor tương ứng: số văn bản và Điều/Khoản/Điểm nếu có.
  - Unknown ID, mất anchor, malformed output, timeout hoặc dependency failure đều fail typed trước retrieval.
  - Model không phân loại pháp luật, không tạo facts và không tự chọn candidate.

  ### Service flow

  1. Authenticate owner và idempotency pre-check.
  2. Acquire advisory lock; re-check idempotency.
  3. Transaction tạo conversation/turn, allocate user_turn_no, persist user message và load context; commit.
  4. Resolve reference hoặc persist clarification.
  5. Rewrite standalone query.
  6. Effective document filters:
      - standalone: giữ explicit request filters;
      - resolved candidate: intersect request IDs với resolved document ID;
      - empty intersection: CONVERSATION_FILTER_CONFLICT;
      - không kế thừa query_date từ history.

  7. Retrieval đúng một lần bằng standalone query.
  8. Generation đúng một lần bằng cùng query và empty generation history.
  9. Grounding.
  10. Transaction persist assistant message, used citations, response snapshot, clear pending và update focuses; commit.
  11. Release lock.
  12. Reconstruct SSE chunks từ persisted snapshot.

  Small talk không có pending được persist nhưng không cập nhật focus. Pending luôn có precedence hơn small-talk bypass.

  ## 5. Frontend, tests và documentation

  ### Frontend tối thiểu

  - ChatSession.id là conversation_id.
  - Mỗi user Message giữ client_turn_id.
  - Không gửi local history.
  - Transport retry giữ nguyên client-turn ID.
  - Hiển thị processing, needs_clarification và badge “Cần làm rõ”.
  - Clarification không render source cards; người dùng trả lời bằng số/tên.
  - LocalStorage chỉ là UI cache, không phải context authority.
  - Server list/sync/delete conversation deferred; đổi wording xóa hiện tại thành “xóa khỏi thiết bị”.

  ### Test matrix

  - Principal: valid/tampered/expired cookie, secure attributes, cross-owner access, missing signing key.
  - Idempotency: completed replay, processing 202, failed replay, simultaneous duplicate ID và không có provider call thứ hai.
  - PostgreSQL: migrations, owner constraints, six-table relations, transaction rollback, JSONB candidate validation.
  - Locking: deterministic key, finite timeout, different conversations concurrent, no open transaction trong provider call, unlock on cancellation/failure.

  - Resolver: explicit document/article/clause lookup, explicit-plus-focus precedence, anaphora, ambiguity, expired focus, pending scope, restate và cancel.
  - Rewriter: rule fast path, structured fallback, unknown ID, missing anchor, malformed/timeout/dependency failure.
  - Service: same query for retrieval/generation, clarification makes zero downstream calls, filter conflict, citation-only focus update, buffered persist-before-SSE.
  - API/SSE: required IDs, reject legacy history, processing/clarification/completed sequences, replay parity, Unicode và typed errors.
  - Frontend: cookie credentials, stable IDs across retry/session switch, clarification display và no source cards.
  - Lifecycle: PostgreSQL/provider startup and cleanup, partial-startup rollback.
  - CI: disposable PostgreSQL service, Alembic upgrade, marked repository integration suite, full Python/frontend quality gates.

  Documentation:

  - Plan 19 trở thành authority cho conversation context.
  - Cập nhật Plan 11 để bỏ “follow-up rewriting deferred”.
  - Cập nhật architecture execution map, backend/frontend README, environment và migration instructions.
  - Giữ nguyên ontology version, retrieval-runtime-v2, answer-generation-v1 và context_projection.py.

  Verification:

  alembic upgrade head trên disposable PostgreSQL
  uv run pytest -q
  uv run ruff check apps/backend src tests
  uv run ruff format --check <changed Python files>
  npm test
  npm run lint
  npm run format:check
  npm run build
  git diff --check