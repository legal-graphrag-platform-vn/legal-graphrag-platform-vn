# Component: Retrieval (`src/retrieval/`)

> Tầng chịu trách nhiệm: nhận câu hỏi → phân loại intent + parse temporal → route sang chiến lược truy vấn phù hợp → chạy hybrid search (vector + fulltext + graph) → fusion + rerank → trả về `RetrievalContext` (bằng chứng đã lọc theo hiệu lực pháp luật) cho tầng [Generation](../generation/README.md).

## Sơ đồ luồng

```
RetrievalRequest
   │
   ▼
IntentRouter (routing/router.py)
   ├─ classify_intent_by_rule() / NLU classifier (nlu/classifier.py, query_processor.py)
   ├─ TemporalParser.parse() (query/temporal_parser.py)
   └─ CapabilitySnapshot check → RetrievalDecision (strategy, required_capability, temporal_source)
   │
   ▼
Hybrid retrieval (retriever/hybrid.py)
   ├─ vector.py   — BGE-M3 dense vector search (Neo4j vector index)
   ├─ fulltext.py — Lucene BM25 fulltext search
   └─ graph.py    — Neo4j CONTAINS/relation graph traversal
   │
   ▼
fusion/reciprocal_rank_fusion.py  — RRF merge của 3 kênh
   │
   ▼
context/temporal_filter.py  — lọc unit theo effective_from/effective_to, hoặc preserve_versions
   │
   ▼
reranking/ (bge_reranker.py)  — rerank lại top-K
   │
   ▼
evidence/verifier.py  — gắn is_eligible cho từng evidence item
   │
   ▼
RetrievalContext  →  sang Generation
```

Với intent `MULTI_HOP`: query đi qua `planning/` (LLM sinh `UnlinkedSemanticPlan` → `binder.py`/`linker.py` resolve về ID thật trong graph, fail-closed nếu không bind được → `executor.py` (`PlannedPathExecutor`) thực thi và re-validate lại topology).

## Các module chính

| File | Trách nhiệm |
|---|---|
| `routing/router.py` | `IntentRouter` — trung tâm quyết định: intent, temporal source, capability yêu cầu, có bật rerank/graph không. Chứa các regex dùng chung (`_AMENDMENT_WORDING`, `_GUIDES_WORDING`) để tránh lệch giữa intent-classification và capability-selection. |
| `query/temporal_parser.py` | `TemporalParser` — parse biểu thức thời gian tiếng Việt theo thứ tự ưu tiên: ngày cụ thể → tháng/năm → "hiện hành/còn hiệu lực" (`CURRENT_VALIDITY_WORDING`) → "trước và sau khi sửa đổi" (`_VERSION_SPAN_WORDING`, set `spans_all_versions`) → duration expressions (loại trừ) → fallback LLM nếu có `llm_client`. |
| `query/query_analyzer.py` | Phân tích câu hỏi bổ trợ cho routing/NLU. |
| `nlu/classifier.py`, `nlu/query_processor.py` | Intent classifier LLM dùng khi rule-based confidence thấp; `query_processor.py` xử lý follow-up/anchor cho hội thoại nhiều lượt. |
| `retriever/vector.py` | Vector search trên Neo4j — dùng embedding BGE-M3 (dense-only), 3 index riêng theo cấp: `appendix_embedding`, `article_embedding`, `clause_embedding`. |
| `retriever/fulltext.py` | BM25 qua Lucene fulltext index của Neo4j. |
| `retriever/graph.py` | Graph traversal theo relation type (`CONTAINS`, `REFERS_TO`, version-chain...), tôn trọng `MAX_DOCUMENT_HIERARCHY_DEPTH=9`. |
| `retriever/hybrid.py` | Điều phối chạy song song 3 kênh trên theo `seed_channels` mà router quyết định. |
| `retriever/policies.py` | Policy lựa chọn kênh/tham số theo intent. |
| `fusion/reciprocal_rank_fusion.py` | RRF: hợp nhất rank list của vector/fulltext/graph thành 1 danh sách candidate_k. |
| `reranking/base.py`, `bge_reranker.py` | Cross-encoder rerank lại `candidate_k` → `final_k`. |
| `context/temporal_filter.py` | `TemporalFilter.filter()` — lọc unit theo hiệu lực thời gian; nếu `preserve_versions=True` (COMPARISON/VALIDITY) thì giữ lại toàn bộ các version thay vì chỉ 1 bản hiệu lực. |
| `context/context_builder.py` | Ráp `RetrievedUnit` + `GraphPath` + `EvidenceItem` thành `RetrievalContext`. |
| `evidence/verifier.py` | Gắn cờ `is_eligible` cho từng `EvidenceItem` dựa trên nguồn/score. |
| `planning/` (binder, linker, executor, patterns, prompts) | Xử lý riêng cho `MULTI_HOP`: LLM plan → bind ID thật (fail-closed) → thực thi path đã re-validate topology. |
| `runtime/runtime.py`, `lifecycle.py` | Runtime lifecycle (khởi tạo/đóng kết nối, DI wiring cho retrieval). |
| `citation.py` | `build_citation_label()` — build label hiển thị (vd "Điều 5 Khoản 2, Phụ lục 1") kèm disambiguation khi Article/Clause nằm trong Appendix trùng số với Document gốc. |
| `models.py` | DTO nội bộ: `TemporalQuery`, `RetrievedUnit`, `GraphPath`, `RetrievalDecision`, `RetrievalContext`... xây trên [`src/shared/retrieval_contract.py`](../shared/README.md) (contract versioned, dùng chung với backend). |

## Nguyên tắc thiết kế quan trọng (fail-closed)

- **VALIDITY/COMPARISON bắt buộc phải có temporal point** (ngày cụ thể, "hiện hành", hoặc `spans_all_versions`) — nếu không có, router raise `TemporalRoutingError` thay vì âm thầm trả kết quả có thể sai hiệu lực pháp luật.
- **Query thường (FACTUAL/DEFINITION/HIERARCHY...) không có tín hiệu thời gian tường minh vẫn mặc định lọc theo "hôm nay"** (`TemporalSource.INJECTED_DEFAULT_CURRENT_DATE`) — tránh lộ điều khoản đã hết hiệu lực/bị thay thế cho phần lớn câu hỏi thông thường.
- **`spans_all_versions`**: dành riêng cho so sánh tương đối theo sự kiện ("trước và sau khi sửa đổi") — không có ngày cụ thể nên không set `resolved_from/resolved_to`, mà đi qua nhánh `preserve_versions` của `TemporalFilter` để mọi version tới được LLM so sánh trực tiếp.
- **MULTI_HOP plan luôn bind lại ID thật và re-validate topology** trước khi thực thi — không tin tưởng ID do LLM tự sinh.

## Kiểm chứng (test evidence)

Xác minh thực đo bằng `pytest`, không phải khẳng định chủ quan:

```
uv run pytest src/retrieval/tests/test_router.py src/retrieval/tests/test_temporal_parser.py -q
→ 30 passed
```

Bộ test này bao phủ cả 6 intent (`FACTUAL/DEFINITION/HIERARCHY/VALIDITY/COMPARISON/MULTI_HOP`), 2 nhánh fail-closed (VALIDITY thiếu temporal point, COMPARISON thiếu temporal point/`spans_all_versions`), và regex dùng chung giữa intent-classification và capability-selection (`_AMENDMENT_WORDING`, `_GUIDES_WORDING`, `CURRENT_VALIDITY_WORDING`, `_VERSION_SPAN_WORDING`).

Toàn bộ `src/retrieval/tests/` (đo chung với `src/generation/tests/`): **325 passed, 5 failed**. 5 fail thuộc `test_artifact_verification.py` và `test_development_evaluation.py`, nguyên nhân là thiếu file dữ liệu `data/processed/L59_2020/hierarchy.json` trên máy chạy test — không liên quan đến logic routing/temporal, không phải regression.

## Liên quan

- [Generation](../generation/README.md) — nơi tiêu thụ `RetrievalContext` để sinh câu trả lời có trích dẫn.
- [Infrastructure](../infrastructure/README.md) — adapter Neo4j/embedding thực thi các port mà `retriever/*.py` gọi tới.
- [Shared Contracts](../shared/README.md) — `retrieval_contract.py`, nguồn contract versioned dùng chung giữa retrieval và backend.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
