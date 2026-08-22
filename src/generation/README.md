# Component: Generation (`src/generation/`)

> Tầng chịu trách nhiệm: nhận `RetrievalContext` (bằng chứng đã lọc, từ [Retrieval](../retrieval/README.md)) → validate + nén evidence → project vào context window → gọi LLM sinh câu trả lời có trích dẫn → **re-validate grounding** (chống bịa/chống prompt injection) → tự sửa 1 lần nếu grounding fail → render câu trả lời cuối cùng.

## Sơ đồ luồng

```
RetrievalContext
   │
   ▼
evidence_validation.py   — validate từng LegalEvidenceBlock (label hợp lệ, ID bắt buộc theo label,
   │                        chặn prompt-injection marker trong content)
   ▼
evidence_compaction.py   — nén/rút gọn evidence khi vượt budget
   │
   ▼
context_projection.py    — build system instruction + project evidence vào context window
   │                        (giới hạn context_max_chars)
   ▼
service.py: AnswerGenerator._render()
   ├─ gọi LLM provider (ports.py: AnswerProviderPort)
   ├─ grounding.py — verify từng citation: verbatim quote match, path hợp lệ, temporal assertion
   │                  hợp lệ so với allowlist evidence thật
   └─ nếu grounding raise lỗi (_GROUNDING_ERRORS) → self-repair: re-prompt kèm
      BEGIN_REPAIR_FEEDBACK/END_REPAIR_FEEDBACK, retry ĐÚNG 1 LẦN → nếu vẫn fail → cannot-answer
   │
   ▼
projected_validation.py / sufficiency.py — đánh giá đủ evidence để trả lời hay phải "cannot answer"
   │
   ▼
renderer.py               — render câu trả lời cuối (Markdown/structured) + AnswerCitation thật
```

## Các module chính

| File | Trách nhiệm |
|---|---|
| `service.py` | `AnswerGenerator` — orchestrator chính của tầng generation; `_render()` gọi LLM rồi grounding-validate; bọc self-repair loop (`_GROUNDING_ERRORS` tuple) quanh `_render()`, cap cứng 1 lần retry. |
| `evidence_validation.py` | `_validate_unit()` — kiểm tra từng evidence block: `Document` chỉ được dùng làm canonical temporal evidence; `Appendix/Article/Clause/Point` là các đơn vị nội dung pháp lý thông thường; đồng thời **chặn prompt-injection** bằng `_PROMPT_INJECTION_MARKERS`. |
| `evidence_compaction.py` | Nén evidence khi tổng dung lượng vượt ngân sách context (loại bớt/rút gọn, ưu tiên theo score). |
| `context_projection.py` | Build `SYSTEM_INSTRUCTION` + format evidence blocks đưa vào prompt LLM; giới hạn cứng bằng `context_max_chars`. |
| `grounding.py` | Lớp phòng thủ quan trọng nhất — validate câu trả lời LLM sinh ra so với evidence thật: <br>• `_is_verbatim_quote()`/`_normalize_for_match()` (NFC-normalize + collapse whitespace) kiểm tra `StatementCitation.quoted_text` phải là **substring nguyên văn** của evidence, không chỉ khớp citation ID. <br>• Validate graph path, temporal assertion trong câu trả lời so với allowlist đã retrieve. |
| `models.py` | DTO: `StatementCitation` (citation_id + quoted_text bắt buộc), `GroundedStatement.citations: list[StatementCitation]`, `LegalEvidenceBlock` (gồm canonical temporal `Document` và các content unit), `AnswerCitation` (citation hiển thị cuối cho FE). |
| `renderer.py` | Render câu trả lời cuối cùng (structured statements → text/markdown + citation list) cho FE hiển thị. |
| `sufficiency.py`, `projected_validation.py` | Đánh giá evidence đã project có đủ để trả lời không → nếu không, trigger nhánh "cannot answer" thay vì để LLM tự bịa. |
| `config.py` | `GenerationConfig` — knobs (context_max_chars, ngưỡng self-repair, model...). |
| `ports.py` | Interface `AnswerProviderPort`/`TextGenerationPort` mà [Infrastructure](../infrastructure/README.md) implement (Gemini/Ollama/OpenAI). |

## Nguyên tắc thiết kế quan trọng (defense-in-depth)

1. **Evidence validate** trước khi đưa vào prompt (label/ID hợp lệ + chặn prompt injection).
2. **Context projection** giới hạn cứng kích thước, không tràn context window.
3. **LLM generate** — mô hình sinh câu trả lời có trích dẫn (`StatementCitation`), bắt buộc kèm `quoted_text`.
4. **Grounding re-validate** sau khi LLM trả lời — không tin LLM tự báo cáo trích dẫn đúng; so khớp verbatim quote + path + temporal assertion với evidence thật đã retrieve.
5. **Self-repair đúng 1 lần** nếu grounding fail (tránh tốn token vô hạn) — re-prompt kèm feedback lỗi cụ thể; nếu lần 2 vẫn fail → trả cannot-answer thay vì trả câu trả lời không grounded.

Toàn bộ pipeline này follow triết lý **fail-closed**: bất kỳ bước nào không chắc chắn (thiếu evidence, citation không khớp, prompt injection nghi ngờ) đều dừng lại/từ chối thay vì đoán.

## Kiểm chứng (test evidence)

```
uv run pytest src/generation/tests/ -q
→ 63 passed
```

Các test then chốt chứng minh từng lớp phòng thủ hoạt động đúng như thiết kế (không phải chỉ code có mặt):

| Test | Chứng minh điều gì |
|---|---|
| `test_grounding_and_service.py::test_fabricated_quote_is_hard_failure` | Trích dẫn có `citation_id` đúng nhưng `quoted_text` không khớp verbatim với evidence → bị grounding từ chối, không lọt qua chỉ vì ID đúng. |
| `test_grounding_and_service.py::test_verbatim_quote_is_surfaced_on_the_rendered_citation` | `AnswerCitation` cuối cùng mang đúng đoạn trích thật đã verify, không phải văn bản LLM tự diễn giải. |
| `test_grounding_and_service.py::test_grounding_failure_self_repairs_on_second_attempt` | Khi grounding fail lần 1, hệ thống re-prompt và lần 2 thành công → trả lời được, không cannot-answer oan. |
| `test_grounding_and_service.py::test_grounding_failure_gives_up_after_one_repair_attempt` | Nếu lần repair vẫn fail, hệ thống dừng lại (đúng 1 lần retry), không lặp vô hạn tốn token. |
| `test_evidence_validation.py::test_evidence_containing_prompt_injection_marker_is_rejected` | Nội dung điều luật chứa chỉ thị lạ (giả lập prompt injection) bị loại trước khi vào prompt LLM. |
| `test_evidence_validation.py::test_ordinary_legal_text_mentioning_unrelated_english_words_is_not_flagged` | Kiểm tra không có false-positive: văn bản pháp luật hợp lệ chứa từ tiếng Anh thông thường không bị chặn nhầm. |
| `test_evidence_validation.py::test_appendix_evidence_with_no_article_or_clause_is_accepted` | Evidence thuộc Phụ lục (không có `article_id`/`clause_id`) được chấp nhận đúng theo ngoại lệ ontology, không crash. |

## Liên quan

- [Retrieval](../retrieval/README.md) — nguồn `RetrievalContext` đầu vào của tầng này.
- [Infrastructure](../infrastructure/README.md) — adapter LLM provider (Gemini/Ollama/OpenAI) implement `ports.py`.
- [Backend API](../../apps/backend/ARCHITECTURE.md) — nơi `AnswerGenerator` được compose vào `ConversationChatService` và trace qua `TracedAnswerGenerator`/`TracedAnswerProvider`.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
