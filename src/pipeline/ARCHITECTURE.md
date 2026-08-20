# Component: Extraction Pipeline (`src/pipeline/`)

> Tài liệu kiến trúc/thiết kế. Để chạy lệnh cụ thể (crawl/parse/extract/write/embed, lấy API key, xử lý reference liên văn bản...) xem [README.md](README.md) và [REPORT.md](REPORT.md) trong thư mục này.

> Tầng chịu trách nhiệm: biến văn bản pháp luật thô (HTML/text) thành đồ thị tri thức (Neo4j) — crawl → parse cấu trúc → trích xuất entity/relation bằng LLM → validate/scoring → ghi Neo4j → sinh embedding.

## Luồng dữ liệu

```
crawl (crawler/)          → data/raw/<code>/source.txt + metadata.json
   │
   ▼
parse (parser/hierarchy_parser.py) → data/processed/<code>/hierarchy.json (cây Part/Chapter/.../Article/Clause/Point)
   │
   ▼
extract (pipeline/orchestrator.py: run_pipeline)
   ├─ Pass 1 LLM: extract_entities (Document/Concept/Entity/Action)
   ├─ Pass 2 LLM: extract_relations (dùng context Pass-1 + structural context)
   ├─ Rule-based: structural_references.py (REFERS_TO xác định), diagram_parser.py (AMENDS/REPEALS/REPLACES/GUIDES)
   ├─ entity_normalization.py — chuẩn hoá/khử trùng lặp entity ID trước khi ghi
   └─ scoring/confidence_scorer.py — chấm điểm confidence từng relation → auto-accept/review/reject
   → extract.jsonl, accepted.jsonl, review.jsonl, rejected.jsonl, entity_index.json
   │
   ▼
write (persistence/payload_builder.py → src/infrastructure/neo4j/writer.py)  — ghi node/relation vào Neo4j
   │
   ▼
embed (src/infrastructure/embedding/embedding_generator.py → embedding_writer.py) — BGE-M3 embedding cho Article/Clause/Appendix
```

## CLI (`src/pipeline/main.py`, Typer)

| Nhóm lệnh | Ý nghĩa |
|---|---|
| `crawl`, `crawl-search` | Tải HTML/text thô từ LuatVietnam/VBPL |
| `parse`, `batch-parse` | Parse `source.txt` → `hierarchy.json` |
| `extract`, `batch-extract` | Chạy `run_pipeline` per-document: LLM extraction + rule-based + validate + scoring |
| `normalize-extraction` | Rebuild decision artifacts từ checkpoint có sẵn, **không** gọi LLM lại (`provider_calls_allowed=False`) |
| `write`, `batch-write` | Ghi payload đã validate vào Neo4j (`mode=structural` chỉ cấu trúc, `mode=full` gồm cả semantic) |
| `embed`, `batch-embed` | Sinh embedding BGE-M3, ghi vào 3 vector index |
| `reconcile-external-references`, `batch-reconcile` | Đối chiếu reference liên văn bản với registry bất biến |
| `ingest`, `batch-ingest-all`, `ingest-folder` | Chain toàn bộ các bước trên end-to-end (hỗ trợ `--retry-failed`, `--limit`, `--skip-existing`, `--doc-by-doc`) |
| `validate-data`, `validate-payload`, `graph-quality`, `graph-snapshot`, `vector-smoke`, `init-schema`/`verify-schema`, `clear-database` | Công cụ hỗ trợ/kiểm định |

## LLM extraction

- **Provider dispatch** (`extraction/providers/`): `gemini` (Google GenAI, structured output qua `response_schema`), `ollama` (local, `/api/chat`, `format: json`), `minimax`/`qwen`/`openai` (dùng chung `OpenAICompatibleProvider`). Chọn qua env `LLM_PROVIDER`.
- **Schema trích xuất** (`extraction/models.py`): entity `Document/Concept(LegalConcept)/Entity(LegalSubject)/Action(LegalAction)`; relation giới hạn `CONTAINS, AMENDS, REPEALS, REPLACES, GUIDES, REFERS_TO, DEFINES, REGULATES, REQUIRES` — LLM bị cấm tự sinh `CONTAINS` (orchestrator hard-reject nếu có).
- **Retry**: Gemini dùng `tenacity` (8 lần, backoff tới 180s, rate-limit toàn cục qua `gemini_min_request_interval_seconds`); Ollama/OpenAI-compatible retry 3 lần trên lỗi HTTP/JSON/Validation.
- **Checkpoint/resume**: `article_extractions.jsonl` per-document (fingerprint theo structural context + text + provider/model/prompt version) giúp resume không gọi lại LLM; `extraction_blocked.json` ghi lý do dừng cứng.
- **Progress ledger toàn corpus**: `data/processed/batch_progress.json` (`batch_progress_ledger.py`) — track theo từng document × từng step (`parse`/`extract`/`pipeline`) trạng thái SUCCESS/FAILED + lỗi, dùng cho resume batch và `--retry-failed`.

## Thiết kế đáng chú ý

- **Synthetic articles**: văn bản `SOURCE_PRESERVED` (parser không tìm được Điều nào) → orchestrator tự chunk phần chưa parse thành các "Điều giả" (`SYNTHETIC_ARTICLE_NUMBER_PREFIX{i}`) để vẫn extract được, bỏ qua kiểm tra source-span cấu trúc.
- **Context passthrough**: `ArticleExtractionContext` (raw_doc_code, graph_id, ID cấu trúc Article/Clause/Point) được serialize và tiêm vào cả 2 prompt để LLM bắt buộc dùng lại ID cấu trúc thật thay vì tự bịa; endpoint được re-resolve lại với `StructuralRegistry`/`DocumentRegistry` sau đó.
- **Entity normalization** (`entity_normalization.py`): chuẩn hoá ID entity ngữ nghĩa (bỏ dấu, snake_case) + khử trùng lặp trước Pass 2/persist; loại bỏ entity kiểu structural mà LLM lỡ sinh ra.
- **Decision gate**: relation tự động accept/review/reject theo tính hợp lệ schema+ontology+consistency và ngưỡng confidence; relation xác định (RULE/ENTITY_LINKING/DIAGRAM/provider) bỏ qua chấm điểm, auto-accept nếu hợp lệ.
- **Atomic artifact writes** (`artifact_store.py`): stage rồi publish atomic, tránh hỏng file khi crash giữa chừng — quan trọng vì job chạy nền, máy reboot bất kỳ lúc nào (xem cronjob watchdog bên dưới).

## Vận hành thực tế (corpus 1832 văn bản)

- Chạy nền: `nohup uv run python -m src.pipeline.main batch-extract --manifest data/luatvietnam_v1.json --raw-dir data/raw --workers 3 --retry-failed & disown`
- `EXTRACTION_MAX_WORKERS=3` (giảm từ 10 do tranh chấp GPU với Ollama gây timeout hàng loạt), `OLLAMA_MODEL=qwen2.5:3b`.
- **Cronjob watchdog** (`scripts/batch_extract_watchdog.sh`) — tự khởi động lại job khi máy reboot/crash: check `pgrep` job đang chạy + Ollama health (`curl /api/tags`), nếu không có job chạy và Ollama sống thì tự chạy lại `batch-extract --retry-failed`. Cài qua `crontab`: `@reboot` + `*/5 * * * *`.

## Config knobs chính (`config.py`, pydantic-settings, env-driven)

`LLM_PROVIDER`, `GEMINI_API_KEY`/`GEMINI_MODEL`/`GEMINI_MIN_REQUEST_INTERVAL_SECONDS`, `OLLAMA_MODEL`/`OLLAMA_BASE_URL`, `EXTRACTION_MAX_WORKERS`, `CONFIDENCE_THRESHOLD_AUTO`(0.8)/`CONFIDENCE_THRESHOLD_REVIEW`(0.55), `NEO4J_URI/USER/PASSWORD`, `EMBEDDING_MODEL`(`BAAI/bge-m3`)/`EMBEDDING_PROVIDER`/`EMBEDDING_DIM`.

## Kiểm chứng (test evidence)

```
uv run pytest src/pipeline/tests/ -q
→ 371 passed
```

Bao phủ parser (hierarchy splitting), extraction (context passthrough cho synthetic article, entity normalization, structural reference resolution), scoring, và validation. Đây là bộ test đơn vị/tích hợp cục bộ (không gọi LLM thật, provider được fake/mocked) — **không chứng minh chất lượng trích xuất thực tế trên corpus 1832 văn bản**, vốn phụ thuộc vào model `qwen2.5:3b` chạy qua Ollama và được theo dõi riêng qua `data/processed/batch_progress.json`.

## Liên quan

- [Infrastructure](../infrastructure/README.md) — `Neo4jWriter`/`Neo4jEmbeddingWriter` thực thi bước write/embed cuối pipeline; xem mục "Trạng thái dữ liệu Neo4j" ở đó — Neo4j mới có pilot corpus (1 document, L59_2020), **chưa** ghi corpus 1832 văn bản đầy đủ.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
