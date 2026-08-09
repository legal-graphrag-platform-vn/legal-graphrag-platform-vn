# Plan 21 — Structured Trace Logging cho luồng chat (AI-aware Debugging)

Status: PHASE 1 + 2 IMPLEMENTED (server-side + Loki/Grafana); Phase 3 pending
Dependencies: `Plan 19 (19_conversation_context.md)`, ADR-27 (Query Processing)
Created At: 2026-08-09
Branch: `feature/add-log`

Implementation notes (Phase 1, 2026-08-09):
- New package `apps/backend/observability/`: `trace.py` (contextvar trace binding,
  JSON logging on the `chat.trace` logger, `log_event`, `TraceConfig`, `redact`,
  `truncate`), `llm.py` (`TracedTextGenerator` wrapping `TextGenerationPort`),
  `__init__.py` (exports).
- `settings.py`: `log_level`, `chat_trace_llm_io` (off|redacted|full),
  `chat_trace_max_raw`.
- `main.py`: `configure_logging` + `configure_trace` at app build.
- `api/routes/chat.py`: `bind_trace` per request + `request.received` /
  `stream.error` events + `clear_trace` in finally.
- `conversation/service.py`: `query_processor.call`, **`query_processor.failed`**
  (stops swallowing — logs raw_output + validation_detail),
  **`generation.cannot_answer`** (surfaces dropped `insufficiency_reason`),
  `retrieval.fanout`, `answer.failed`, `turn.finished`.
- `container.py`: query-processor text generator wrapped with
  `TracedTextGenerator` (stage=`query_processor`).
- Verified: observability smoke test emits JSON events; `test_conversation_service`
  (12) + `test_contracts` (26, builds app) pass; ruff clean.

Implementation notes (Phase 2 — Loki/Grafana sink, 2026-08-09):
- `trace.py` `configure_logging(level, log_file=...)` adds a RotatingFileHandler
  so trace JSON is also written to a file Promtail can tail; `settings.py`
  `chat_trace_log_file` (env `CHAT_TRACE_LOG_FILE`); wired in `main.py`.
- New opt-in stack `infra/docker-compose.observability.yml` (name
  `graphrag-observability`): `loki` (3100), `promtail` (tails
  `data/logs/*.log`), `grafana` (host 3001, anonymous admin, light theme).
- Config: `infra/observability/loki-config.yml` (single-binary, tsdb/filesystem,
  7-day retention), `promtail-config.yml` (json pipeline → labels stage/status,
  trace_id kept as field), Grafana provisioning (Loki datasource uid=loki +
  dashboard provider) and dashboard `grafana/dashboards/chat-trace.json`
  (timeline filtered by `$trace_id` + an errors/cannot_answer panel).
- Data dirs `infra/data/{logs,loki,grafana}` created (contents gitignored).
- `infra/.env.example`: LOKI_PORT / GRAFANA_PORT / GRAFANA_ADMIN_PASSWORD +
  backend CHAT_TRACE_* hints.
- Validated: `docker compose config` valid, all YAML/JSON parse. Live bring-up
  pending (Docker Desktop was not running at implementation time).

### How to run (Phase 2)
```bash
# 1. Start the log stack
docker compose -f infra/docker-compose.observability.yml up -d
# 2. Point the backend at the trace file, then restart the backend:
#    apps/backend/.env → CHAT_TRACE_LOG_FILE=infra/data/logs/chat-trace.log
# 3. Send a chat turn, then open Grafana:
#    http://localhost:3001  → dashboard "Chat Trace"
#    Explore query: {job="chat-trace"} | json | trace_id=~"<turn_id>"
```

## Bối cảnh

Luồng xử lý chat (`POST /api/v1/chat`) gọi Gemini ở **hai điểm** — Query Processor
(five-field contract) và Answer Generation — cộng retrieval fan-out nhiều
subquery. Khi một turn lỗi hoặc trả `cannot_answer`, hiện **không biết lỗi ở
stage nào và AI đã suy luận ra sao**.

Điểm đau cụ thể đã xác định trong code: các lỗi AI **đã mang sẵn context** nhưng
đang bị nuốt.
- `QueryProcessingParseError` đính kèm `raw_output` (`src/retrieval/nlu/query_processor.py`).
- `QueryProcessingContractError` đính kèm chi tiết field validate sai.
- Cả hai bị bắt tại `apps/backend/conversation/service.py:204` và map thẳng sang
  `QUERY_PROCESSING_FAILED` **không log gì** → mất toàn bộ raw output của Gemini.

Hạ tầng logging hiện tại: chỉ có `logging.getLogger(__name__)` rải rác, **không**
có central config, **không** structlog, **không** trace correlation.

## Phạm vi

**Giai đoạn này chỉ làm SERVER-SIDE LOG.** Việc surface lý do ra **client** (đưa
`insufficiency_reason` / error detail vào response cho UI) **để sau**, là một item
tách riêng (xem mục 9). Mục tiêu trước mắt: dev đọc log server là biết được vì sao
một turn lỗi hoặc `cannot_answer`.

## Mục tiêu

1. **Where** — biết turn lỗi ở stage nào (query processor / subquery retrieval
   nào / generation).
2. **Why cannot_answer** — thấy `insufficiency_reason` mà generator sinh ra (hiện
   đang bị drop, xem mục 4).
3. **How AI reasoned** — thấy prompt gửi đi + raw output + kết quả parse của mỗi
   lần gọi Gemini.
4. **Correlate** — mọi log của một request nối bằng một `trace_id`, dựng lại
   timeline theo thứ tự + latency từng bước.
5. Bật/tắt và điều chỉnh độ chi tiết bằng env; không phá contract, không tốn
   performance ở mức mặc định.

## Non-goals

- Không dựng APM/tracing phân tán (OpenTelemetry) ở giai đoạn này.
- Không đổi business logic của service/retrieval/generation.
- Không log full prompt ở mức mặc định (size + dữ liệu người dùng).
- **Không đổi response/SSE contract ra client** — client giữ nguyên; chỉ thêm log
  ở server (client surfacing để sau, mục 9).

---

## 1. Nền tảng: trace_id + structured event

- **`contextvars.ContextVar`** giữ `trace_id` (= `turn_id`), `conversation_id`,
  `owner_id`; bind một lần ở route. Nhờ asyncio contextvar, mọi log trong task
  con (kể cả các subquery chạy trong `asyncio.gather`) tự mang `trace_id` mà
  không phải truyền tay.
- **Module mới `apps/backend/observability/trace.py`**:
  - `bind_trace(turn_id, conversation_id, owner_id)`
  - `log_event(stage, status, **fields)` → phát **1 dòng JSON**:
    `{ts, trace_id, conversation_id, stage, status, latency_ms, ...fields}`
  - `TurnTrace` — collector gom các event của một turn để persist (mục 4).
- **Central logging config** ở `apps/backend/main.py` (hiện chưa có): JSON
  formatter, level theo `LOG_LEVEL`. Giữ stdlib `logging`; structlog là optional,
  không bắt buộc.

## 2. Stage taxonomy (bám đúng code flow)

| stage | ghi ở đâu | fields chính |
|---|---|---|
| `request.received` | `api/routes/chat.py` | message_chars, has_history |
| `turn.replayed` | `service._replay_snapshot` | source=idempotency/lock_recheck |
| `lock.acquired` / `lock.busy` | `service._resolve_snapshot` | wait_ms |
| `context.loaded` | sau `begin_turn_and_load_context` | recent_msgs, grounded_focuses |
| `query_processor.call` | bọc LLM (mục 3) | status, plan_type, subquery_count, latency, provider, model |
| `query_processor.failed` | except tại `service.py:204` | **error_type, raw_output(trunc), validation_detail** |
| `retrieval.subquery` | trong `asyncio.gather` | subquery_id, intent, unit_count, graph_paths, latency + `metrics` từ runtime |
| `retrieval.merge` | sau `merge_contexts` | merged_units, dedup_removed |
| `generation.call` | bọc LLM (mục 3) | citation_count, cannot_answer, confidence, latency, provider, model |
| `generation.cannot_answer` | `_finish_answer` | **insufficiency_reason**, sources_count, subquery intents |
| `generation.failed` | except | error_type, message |
| `turn.finished` | `_finish_answer` / `_persist_*` | final_status, citation_count, total_latency_ms |

Kết quả — đọc log một turn ra đúng timeline:

```text
trace=abc lock.acquired 5ms
trace=abc context.loaded recent=3 focuses=2
trace=abc query_processor.call READY plan=parallel subq=2 831ms gemini
trace=abc retrieval.subquery q1 intent=definition units=6 210ms
trace=abc retrieval.subquery q2 intent=factual   units=5 240ms
trace=abc retrieval.merge units=9 removed=2
trace=abc generation.call citations=2 cannot_answer=false 1180ms gemini
trace=abc turn.finished completed citations=2 2500ms
```

## 3. Lõi giá trị: bọc LLM boundary (provider-agnostic)

Thay vì rải log khắp nơi, **decorate `TextGenerationPort`** bằng một
`LoggingTextGenerator` (wrap trong `apps/backend/container.py`, một chỗ phủ cả
Query Processor, rewriter, và answer generator):

```text
LlmCallTrace {
  stage, provider, model, params{temperature, response_format},
  request:  { prompt_chars, prompt_sha256, prompt_preview | prompt_full(gated) },
  response: { latency_ms, raw_text(trunc|full gated), finish_reason, usage{in,out} },
  outcome:  ok | dependency_error | output_error,
}
```

- Trả lời trực tiếp "**AI suy luận ra sao**": thấy input Gemini nhận và **raw
  text** nó trả về trước khi parse.
- Không sửa `QueryProcessor`/generator; chỉ bọc ở tầng port → clean, không đụng
  business logic.

## 4. Chốt điểm đau: hai chỗ lý do đang bị "vứt đi"

Hai giá trị chẩn đoán quan trọng nhất đã được tính ra nhưng **bị bỏ trước khi tới
đâu cả** — server-log chính là nơi cứu chúng:

- **QP error swallowing** — tại `apps/backend/conversation/service.py:204`,
  **trước** khi map sang `QUERY_PROCESSING_FAILED`, gọi
  `log_event("query_processor.failed", error_type=..., raw_output=exc.raw_output[:MAX], validation_detail=...)`.
  Biến "lỗi mù" thành "lỗi có raw output của Gemini + field validate sai".

- **`cannot_answer` reason bị drop** — generator sinh
  `AnswerResponse.insufficiency_reason` (`src/generation/models.py:269`, điền tại
  `grounding.py:42` / `service.py:88`) nhưng `_finish_answer`
  (`conversation/service.py:449`) **không đọc field này** → nó không vào snapshot,
  DB, hay client. Thêm
  `log_event("generation.cannot_answer", insufficiency_reason=answer.insufficiency_reason, sources_count=..., subquery_intents=...)`
  ngay tại `_finish_answer` khi `answer.cannot_answer`. Đây là **cách duy nhất
  hiện thấy được vì sao "không thể trả lời"** mà không đổi contract ra client.
- **Bảng mới `turn_debug_trace`** (Alembic migration): lưu `TurnTrace` JSON (chuỗi
  event + LLM I/O) cho **turn FAILED** (và mọi turn khi `CHAT_TRACE_PERSIST=all`).
  Tra cứu offline theo `turn_id` / `conversation_id` không cần bới log file.
  - *Phương án thay thế*: nhét vào `response_snapshot["debug"]`. **Khuyến nghị bảng
    riêng** để snapshot sạch và giữ được trace cả turn thành công khi cần debug.

## 5. Kiểm soát: level, redaction, size, config

| env | default | tác dụng |
|---|---|---|
| `LOG_LEVEL` | INFO | INFO = milestones + latency; DEBUG = kèm LLM I/O |
| `CHAT_TRACE_LLM_IO` | `redacted` | `off` \| `redacted` (preview 500 ký tự + sha256) \| `full` |
| `CHAT_TRACE_PERSIST` | `failed` | `off` \| `failed` \| `all` |
| `CHAT_TRACE_MAX_RAW` | 2000 | cap ký tự raw_output lưu |

- **Redaction hook** cho `user_prompt` (câu hỏi user có thể chứa thông tin cá
  nhân) — mặc định chỉ lưu preview + hash; `full` chỉ dùng khi debug cục bộ.
- Milestones (INFO) luôn bật, rẻ; full AI I/O gate sau DEBUG/flag để không phình
  log và không tốn.

## 5b. Log sink & nơi xem — Grafana Loki (quyết định)

Không dừng ở terminal. Sink chính = **Grafana Loki** (bạn đã quen Grafana).

- App in **JSON log** trên logger `chat.trace` (đã có ở Phase 1) → **Promtail /
  Docker log driver** đẩy vào **Loki** → xem/lọc trong **Grafana** theo
  `trace_id`, `stage`, `provider`, `status`.
- Vì sao Loki chứ không Jaeger/OTel: pain là **đọc nội dung AI** (raw output,
  `insufficiency_reason`) = dữ liệu LOG, Loki chứa/đọc text blob tốt và gần như
  free vì log đã có; Jaeger tối ưu latency-waterfall (thứ cần ít nhất) và bắt
  instrument span nhiều. Chi tiết trade-off: xem thảo luận trong session/ADR-27.
- **Postgres `turn_debug_trace`** (Phase 3) vẫn giữ làm **hồ sơ bền** tra theo
  `turn_id` cho turn FAILED (Loki có retention giới hạn) — bổ trợ, không thay Loki.
- **Đường mở rộng waterfall**: sau này cắm **Tempo** (cùng nhà Grafana, chung UI,
  trace-to-logs) thay vì Jaeger — không đổi UI, không vứt gì.

Compose (Phase 2): thêm service `loki` + `grafana` (+ `promtail`) vào `infra`,
provision Loki làm datasource mặc định của Grafana.

## 6. Phân rã công việc (phased)

**Phase 1 — Quick win (nửa ngày), server-log cho đúng ba ca đau:**
- `observability/trace.py` (contextvar + `log_event` JSON) + JSON logging config ở
  `main.py`.
- Bind `trace_id` ở `chat.py`.
- Log `query_processor.failed` kèm `raw_output` / `validation_detail` (fix
  swallowing tại `service.py:204`).
- Log `generation.cannot_answer` kèm `insufficiency_reason` tại `_finish_answer`.
- Đảm bảo `generation.failed` / retrieval error có log (một phần đã có qua
  `logging.exception` ở `chat.py:56`).
- → Đủ để biết: QP lỗi (Gemini trả gì), vì sao `cannot_answer`, và lỗi
  retrieval/generation.

**Phase 2 — Full timeline:**
- Rải `log_event` các stage ở `service.py` (context, subquery, merge, generation,
  finished) + surface `metrics` từ `src/retrieval/runtime/runtime.py`.
- `LoggingTextGenerator` bọc port trong `container.py` (LLM I/O có cấu trúc).

**Phase 3 — Persist & tra cứu:**
- Migration `turn_debug_trace` + ghi `TurnTrace` cho turn FAILED.
- (tuỳ chọn) endpoint/CLI đọc trace theo `turn_id`.

## 7. Instrumentation map (file → điểm chèn)

| File | Điểm chèn |
|---|---|
| `apps/backend/main.py` | central JSON logging config, đọc `LOG_LEVEL` |
| `apps/backend/observability/trace.py` | **mới** — contextvar, `log_event`, `TurnTrace` |
| `apps/backend/api/routes/chat.py` | `bind_trace`, `request.received`, error paths |
| `apps/backend/conversation/service.py` | stage events + fix swallowing tại `:204` |
| `apps/backend/container.py` | wrap `TextGenerationPort` = `LoggingTextGenerator` |
| `src/retrieval/runtime/runtime.py` | surface `metrics` dict ra trace (không đổi logic) |
| `apps/backend/alembic/versions/*` | migration `turn_debug_trace` (Phase 3) |

## 8. Acceptance (đo bằng chính pain hiện tại)

- Turn lỗi QP → tìm `turn_id` → thấy ngay: prompt gửi Gemini, raw output, field
  validate fail.
- Turn `cannot_answer` bất ngờ → server-log có `insufficiency_reason` + từng
  subquery intent + unit_count → biết vì sao thiếu căn cứ và retrieval rỗng ở
  subquery nào.
- Grep `trace_id` ra full timeline có latency từng bước.

## 9. Client surfacing — DEFERRED (ngoài phạm vi giai đoạn này)

Sau khi server-log ổn, một plan/PR riêng sẽ đưa lý do ra client:
- Thêm `insufficiency_reason` vào `ChatMetadataData` / `ChatDoneData`
  (`api/models.py`) và điền tại `_finish_answer` → UI hiển thị vì sao "không thể
  trả lời".
- (tuỳ chọn) map error code → thông điệp thân thiện hơn cho từng loại lỗi.

Việc này **đổi response contract ra client** nên tách khỏi giai đoạn server-log để
không lẫn phạm vi. Không làm ở Plan 21 phần này.
