# Component: Shared Contracts (`src/shared/`)

> Tầng "không phụ thuộc ai" — chứa các kiểu dữ liệu, enum, và luật ontology mà mọi tầng khác ([Retrieval](../retrieval/README.md), [Generation](../generation/README.md), [Pipeline](../pipeline/ARCHITECTURE.md), backend) cùng import. Đây là nền tảng để các tầng giao tiếp không lệch schema với nhau, và là nơi ontology pháp lý được mã hoá thành ràng buộc kiểm tra được bằng máy thay vì chỉ nằm trong tài liệu.

## `retrieval_contract.py` — contract versioned dùng chung retrieval ↔ backend

| Kiểu | Ý nghĩa |
|---|---|
| `IntentType` | 6 giá trị: `FACTUAL, VALIDITY, HIERARCHY, COMPARISON, DEFINITION, MULTI_HOP` — toàn bộ hệ thống chỉ định tuyến theo 6 intent này. |
| `RetrievalChannel` | `VECTOR, FULLTEXT, GRAPH` — 3 kênh retrieval hybrid. |
| `RetrievalStrategyType` | Chiến lược gắn theo intent (`FACTUAL_HYBRID`, `VALIDITY_TEMPORAL`, `COMPARISON_TEMPORAL`...). |
| `RetrievalCapability` | Năng lực hạ tầng cần có để phục vụ 1 loại truy vấn (`SCOPED_TEMPORAL_METADATA`, `CORPUS_COMPLETE_CURRENT_VALIDITY`, `VERSION_CHAIN_VALIDITY`, `STRUCTURAL_HIERARCHY`, `GUIDES_RELATIONS`, `SEMANTIC_MULTI_HOP_GRAPH`...) — router kiểm tra capability này còn thiếu thì raise lỗi thay vì trả kết quả không đủ căn cứ. |
| `TemporalSource` | Nguồn gốc điểm thời gian dùng để lọc: `NONE, REQUEST, QUERY_EXPRESSION, INJECTED_CURRENT_DATE, INJECTED_DEFAULT_CURRENT_DATE` — phục vụ observability. |
| `RetrievalDecisionReasonCode` | Mã lý do quyết định routing (`VALIDITY_CURRENT_DATE`, `FORCED_INTENT`, `INTENT_CLASSIFIER_LLM`...) — dùng cho log/trace, không phải cho logic nghiệp vụ. |
| `RetrievalFilters`, `RetrievalRequest` | DTO đầu vào chuẩn hoá cho 1 lượt truy vấn. |

`src/retrieval/models.py` mở rộng các kiểu này (vd `TemporalQuery`, `RetrievalDecision`) trên nền `retrieval-runtime-v2` (`contract_version: Literal[...]`) — đánh version tường minh để phát hiện lệch schema giữa retrieval và backend khi 1 trong 2 bên thay đổi mà bên kia chưa cập nhật.

## `ontology/` — luật cấu trúc pháp lý mã hoá thành code

| File | Trách nhiệm |
|---|---|
| `hierarchy.py` | Hằng số độ sâu cây tài liệu: `MAX_DOCUMENT_TO_ARTICLE_DEPTH=7`, `MAX_DOCUMENT_TO_RETRIEVAL_UNIT_DEPTH=8`, `MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH=9`, `MAX_DOCUMENT_HIERARCHY_DEPTH=9`. Các truy vấn Cypher dùng wildcard `[:CONTAINS*1..MAX_DOCUMENT_HIERARCHY_DEPTH]` trong [Infrastructure](../infrastructure/README.md) tuân theo chính hằng số này, tránh truy vấn tràn/lệch độ sâu khi ontology có cấu trúc lồng sâu như Appendix chứa Part/Chapter/Article riêng. |
| `contract.py` | Định nghĩa hợp đồng dữ liệu graph payload (node/relation type hợp lệ) mà `payload_builder.py` ([Pipeline](../pipeline/ARCHITECTURE.md)) và `Neo4jWriter` ([Infrastructure](../infrastructure/README.md)) phải tuân theo trước khi ghi. |
| `extraction_validator.py` | Validate output LLM extraction đúng ontology (loại entity/relation cho phép, không để LLM tự sinh `CONTAINS`). |
| `payload_consistency_validator.py` | Kiểm tra tính nhất quán nội tại của 1 payload trước khi ghi Neo4j (endpoint tồn tại, không tham chiếu treo). |
| `validators.py` | Tập hợp validator dùng chung khác. |

## Vì sao tầng này quan trọng để đọc trước

Ontology pháp lý (`plans/legal_ontology.md`) định nghĩa: **Appendix (Phụ lục) là 1 đơn vị nguồn luật do Document/AttachedInstrument sở hữu trực tiếp, và bản thân Appendix có thể chứa Part/Chapter/Section/Article riêng** (đánh số theo phạm vi Appendix, có thể trùng số với Document gốc nhưng không trùng ID — `Article.id = {owner_id}_art{N}` với `owner_id` có thể là Document, AttachedInstrument, hoặc Appendix). Đây chính là lý do:

- `retrieval/citation.py` phải disambiguate label khi Article/Clause nằm trong Appendix trùng số với Document gốc — xem [Retrieval](../retrieval/README.md).
- `generation/evidence_validation.py` phải có nhánh riêng miễn `article_id`/`clause_id` cho Appendix — xem [Generation](../generation/README.md).
- `infrastructure/neo4j/document_browser_repo.py` không cần sửa Cypher traversal cho Appendix (wildcard `CONTAINS*` đã tự bao phủ) mà chỉ cần thêm CASE-label mapping — xem [Infrastructure](../infrastructure/README.md).

Nói cách khác: **1 ràng buộc ontology duy nhất đã tạo ra hiệu ứng lan toả nhất quán qua 3 tầng khác nhau** — minh chứng cho giá trị của việc tách riêng ontology thành shared contract thay vì lặp lại giả định về cấu trúc dữ liệu ở từng nơi.

## Liên quan

- [Retrieval](../retrieval/README.md), [Generation](../generation/README.md), [Pipeline](../pipeline/ARCHITECTURE.md), [Infrastructure](../infrastructure/README.md) — 4 tầng cùng phụ thuộc vào các định nghĩa ở đây.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
