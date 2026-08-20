# Component: Infrastructure (`src/infrastructure/`)

> Tầng adapter — implement các port trừu tượng mà [Retrieval](../retrieval/README.md), [Generation](../generation/README.md), [Pipeline](../pipeline/ARCHITECTURE.md) định nghĩa, để nói chuyện với hệ thống thật: Neo4j (đồ thị + vector index) và LLM provider (Gemini/Ollama/OpenAI-compatible).

## `src/infrastructure/neo4j/`

| File | Trách nhiệm |
|---|---|
| `writer.py` | `Neo4jWriter`/`GraphIngestionService` — MERGE node/relation từ `ValidatedGraphPayload` đã validate (từ chối raw dict). |
| `embedding_writer.py` | `Neo4jEmbeddingWriter` — verify 3 vector index (`appendix_embedding`, `article_embedding`, `clause_embedding`) tồn tại/ONLINE/đúng dimension; ghi `embedding`, `embedding_model`, `embedding_dimension`, `embedding_content_hash`... lên node. |
| `retriever_repo.py` | `Neo4jRetrieverRepo` — **read path chính lúc query-time**: `vector_search` (union nhiều index qua `db.index.vector.queryNodes`), `fulltext_search`, `fetch_canonical_anchors`, `graph_expansion` (traversal có lọc temporal/status), `lookup_structural_endpoints`, `lookup_exact_paths`, `inspect_capabilities`/`inspect_dependencies` (gate kênh retrieval theo index có sẵn hay không). |
| `document_browser_repo.py` | `Neo4jDocumentBrowserRepo` — read-only cho Explorer UI: `list_documents`, `get_document` (hierarchy qua `CONTAINS*`), `get_article`, `get_graph`, `graph_edges`, quan hệ liên văn bản (AMENDS/REPEALS/REFERS_TO...). |
| `reference_writer.py` | `Neo4jExternalReferenceWriter`/`Neo4jProviderTemporalWriter` — ghi có transaction-guard cho `REFERS_TO` bundle và relation temporal (`AMENDS`/`REPEALS`), verify quyền sở hữu endpoint trước khi MERGE. |
| `hierarchy_reconciler.py` | `SectionHierarchyReconciler` — xoá `CONTAINS` edge cũ đã bị làm phẳng (Chapter→Article...) sau khi verify chain mới (Chapter→Section→Article...) đã tồn tại. |
| `graph_snapshot.py` | Sinh snapshot JSON tất định (node/relation projection, sha256 hash, embedding coverage) — bằng chứng nghiệm thu (Gate 4). |
| `schema_initializer.py` / `schema_verifier.py` | Áp dụng & verify `infra/neo4j/init/01_schema_init.cypher` (constraint, fulltext/vector index; vector index bắt buộc 1024-dim, cosine). |
| `vector_smoke.py` | Chạy 3 câu hỏi pháp lý tiếng Việt cố định qua `article_embedding`/`clause_embedding` để smoke-test. |
| `m3_runtime.py` | Safety guard cho Neo4j test instance dùng-một-lần (`bolt://localhost:7688`, không credential trong URI, cần opt-in flag mới cho phép reset phá hủy). |

## `src/infrastructure/embedding/embedding_generator.py`

- Model mặc định **`BAAI/bge-m3`**, provider `flag_embedding` (`FlagEmbeddingModel`/`BGEM3FlagModel`), dimension 1024; có hỗ trợ thay thế `sentence_transformers`.
- **Chỉ dùng dense embedding**: `encode(..., return_dense=True, return_sparse=False, return_colbert_vecs=False)` — sparse và ColBERT của BGE-M3 bị tắt hẳn, không được implement/expose ở đâu trong codebase (hạn chế đã ghi nhận).
- Chỉ nhắm Article/Clause + Appendix "lá" (Appendix chứa Article con thì bị skip, tránh double-embed).

## Adapter LLM khác

| File | Trách nhiệm |
|---|---|
| `llm/gemini_answer_provider.py` | `GeminiAnswerProvider` — implement `AnswerProviderPort` (sinh câu trả lời có cấu trúc). |
| `llm/gemini_text_provider.py` | `GeminiTextProvider` — implement `TextGenerationPort` (text thuần, dùng cho temporal parser fallback, intent classifier...). |
| `llm/ollama_text_provider.py` | `OllamaTextProvider` — bản local qua Ollama HTTP. |
| `llm/text_generation_factory.py` | `build_text_generator()` — chọn Gemini/Ollama theo env `LLM_PROVIDER`. |
| `llm/errors.py` | `TextGenerationError` và các subclass dùng chung. |

## Ports & wiring (ai implement port nào)

- `src/application/retrieval_factory.py` — điểm lắp ráp duy nhất: bọc `Neo4jRetrieverRepo` để thoả `VectorSearchPort`/`FullTextSearchPort`/`GraphExpansionPort`/`CapabilityInspectionPort` (định nghĩa trong `src/retrieval/ports.py`), bọc `EmbeddingGenerator` thành `EmbeddingPort`, và `build_text_generator` thành `IntentClassifierPort`.
- `src/application/answer_factory.py` — bọc `GeminiAnswerProvider` thành `AnswerProviderPort` (`src/generation/ports.py`).

Đây là kiến trúc ports-and-adapters chuẩn: [Retrieval](../retrieval/README.md)/[Generation](../generation/README.md) không import trực tiếp bất kỳ thứ gì trong `src/infrastructure` — chỉ biết interface, việc lắp ráp cụ thể nằm ở `src/application`.

## Trạng thái dữ liệu Neo4j (quan trọng)

Neo4j **đã** được ghi cho **pilot corpus** (không phải toàn bộ 1832 văn bản): theo `results/milestone_a/L59_2020_summary.md`, đã chạy `write`/`embed` cho L59_2020 trên Neo4j dùng-một-lần (`bolt://localhost:7688`) — 1 Document, 218 Article, 897 Clause (2333 node / 2723 relation), 100% embedding coverage Article/Clause, vector-index smoke test pass. Tuy nhiên tài liệu đó tự ghi rõ: **"four-document corpus remains open"** và **"Milestone A remains NOT PASSED and Phase 2 remains BLOCKED"** — cần đủ tối thiểu 4 văn bản + reconcile reference liên văn bản mới coi là đạt. `batch-write` cho toàn bộ corpus 1832 văn bản **chưa chạy**.

## Liên quan

- [Retrieval](../retrieval/README.md) — bên tiêu thụ các port này ở query-time.
- [Pipeline](../pipeline/ARCHITECTURE.md) — bên gọi `Neo4jWriter`/`Neo4jEmbeddingWriter` lúc ingest.
- [Shared Contracts](../shared/README.md) — hierarchy depth constants (`MAX_DOCUMENT_HIERARCHY_DEPTH=9`...) mà Cypher traversal trong `retriever_repo.py`/`document_browser_repo.py` tuân theo.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
