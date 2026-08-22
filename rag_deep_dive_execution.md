# Luồng Thực Thi RAG Chi Tiết Mức Code (Deep-Dive Execution Trace)

Tài liệu này bóc tách chi tiết từng hàm, từng tham số, và từng dòng dữ liệu di chuyển qua kiến trúc Graph-RAG, giải thích chính xác điều gì xảy ra ở cấp độ mã nguồn.

---

## Tầng 1: Retrieval (Thu thập dữ liệu)

Đầu vào: `query: str`
Entry point: `RetrievalRuntime.execute(query)`

### 1.1. Phân loại Query & Chiến thuật (Routing)

- **Hàm gọi:** `Router.route(query)`
- **Chi tiết:** Phân tích câu hỏi để gán nhãn.
- **Đầu ra:** `RetrievalDecision` chứa `intent` (VD: `IntentType.FACTUAL`), `strategy` (VD: `FACTUAL_HYBRID`), và thông tin mốc thời gian nếu có.

### 1.2. Tìm hạt giống (Seed Search)

- **Hàm gọi:** `VectorRetriever.search()`, `FulltextRetriever.search()`
- **Chi tiết:** Chạy song song (async). Vector search dùng thuật toán cosine similarity trên database Qdrant/Neo4j. Fulltext search dùng BM25.
- **Đầu ra:** 2 danh sách `RetrievedUnit` chứa các đoạn văn bản thô (điều/khoản) phù hợp nhất với từ khóa. Mỗi Unit có kèm `vector_score` hoặc `bm25_score`.

### 1.3. Mở rộng đồ thị (Graph Expansion)

- **Hàm gọi:** `GraphRetriever.expand(entry_ids, intent)`
  - _`entry_ids` lấy từ kết quả của Vector/Fulltext._
- **Chi tiết:** Lấy policy theo `intent`. VD hỏi Factual thì sẽ đi sâu 2 bước (`max_depth=2`), theo các quan hệ `REGULATES, DEFINES, REQUIRES, REFERS_TO`. Lệnh Cypher `MATCH path = (entry)-[*1..2]->(related)` được thực thi.
- **Đầu ra (Object `GraphExpansion`):**
  - `units`: Các node `citable` (Điều/Khoản) nằm ở các điểm chốt của mọi đường đi tìm được.
  - `paths`: Đầy đủ mảng `nodes` (kể cả node trung gian như Khái niệm pháp lý) và `edges` (tên cạnh nối).

### 1.4. Trộn kết quả & Lọc thời gian (Fusion & Temporal Filter)

- **Hàm gọi:** `ReciprocalRankFusion.fuse_channels()`
- **Chi tiết:** Dùng công thức RRF $Score = \frac{1}{k + rank_{vector}} + \frac{1}{k + rank_{bm25}} + \frac{1}{k + rank_{graph}}$ để trộn 3 rổ dữ liệu thành 1 danh sách phẳng duy nhất.
- **Hàm gọi (Tiếp theo):** `TemporalFilter.apply()`
- **Chi tiết:** Bỏ các Unit không còn hiệu lực so với ngày được hỏi (`query_date`).

### 1.5. Chấm điểm lại (Reranking)

- **Hàm gọi:** `BGEReranker.rerank(query, fused_units, top_n)`
- **Chi tiết:** Đưa từng cặp `[query, unit.content_raw]` qua model Cross-Encoder để tính toán sự chú ý (attention) từng từ một.
- **Đầu ra:** Danh sách bị cắt ngắn lấy đúng `top_n` (VD: Top 10) những Unit có điểm liên quan ngữ nghĩa `rerank_score` cao nhất.

### 1.6. Đóng gói Context Builder

- **Hàm gọi:** `ContextBuilder.build_context()`
- **Chi tiết:** Đóng gói toàn bộ Top 10 `retrieved_units` (có chữ) và TOÀN BỘ `graph_paths` (không cắt bớt) thành object `RetrievalContext` để bàn giao cho tầng Generation.

---

## Tầng 2: Generation (Sinh câu trả lời an toàn)

Đầu vào: `AnswerGenerationRequest(query, retrieval_context)`
Entry point: `AnswerGenerator.generate(request)`

### 2.1. Đánh giá tính đủ (Sufficiency Check)

- **Hàm gọi:** `EvidenceSufficiencyPolicy.evaluate(retrieval_context)`
- **Chi tiết:** Dựa vào `intent`, hệ thống chặn đứng LLM nếu dữ liệu tìm được quá vô lý. (Ví dụ: Hỏi so sánh mà tìm được mỗi 1 văn bản -> Trả luôn về lỗi Không thể trả lời, khỏi gọi LLM).

### 2.2. Validation & Đóng gói (Evidence Compaction)

- **Hàm gọi:** `EvidenceValidator.validate()`, sau đó `EvidenceCompactor.compact()`
- **Chi tiết:**
  1.  `Validator` vứt các Unit có dấu hiệu Hack/Prompt Injection.
  2.  `Compactor` gộp các Unit và Path có liên quan logic với nhau thành các `EvidenceBundle` (Gói chứng cứ).
  3.  **Lọc Path rác:** Đây là đoạn dùng lệnh `any(node_id not in retrieved_units for node_id in path_nodes)`. Nó ném bỏ bất kỳ Path nào mà có một điểm nối không nằm trong Top 10 Unit (tức là đã bị Reranker chê rác).
  4.  **Tính Budget:** Khấu trừ dần số lượng token, lấy các Bundle từ điểm cao xuống thấp, hễ Bundle nào cho vào mà làm tràn bộ nhớ LLM thì loại bỏ hoàn toàn (reason: `context_budget_exceeded`).

### 2.3. Lập Sổ Nam Tào & Ghép JSON (Context Projection)

- **Hàm gọi:** `ContextProjector.project()`, `ContextProjector.build_registry()`
- **Chi tiết:**
  1.  Tạo sổ `EvidenceRegistry`: Ghi danh sách đen/trắng, cấp cho mỗi Unit và mỗi Path một ID duy nhất (`K1_A5`, `path-0`). Khóa sổ lưu lại ở Backend.
  2.  Ghép thành JSON: Chuyển dữ liệu trong các Bundle an toàn thành một chuỗi JSON thuần.

### 2.4. Gọi LLM

- **Chi tiết:** Gửi cho Gemini/Claude một Prompt gồm: Hợp đồng đầu ra (Bắt ép cấu trúc JSON, ép trả về ID trích dẫn) + Cục JSON dữ liệu đã nén. Nhận về kết quả là một đoạn JSON từ LLM chứa câu trả lời.

### 2.5. Trạm kiểm soát (Grounding Validator)

- **Hàm gọi:** `GroundingValidator.validate_and_render()`
- **Chi tiết:** Trạm này check chéo kết quả LLM nộp về với "Sổ Nam Tào":
  1.  **Check ID Trích dẫn:** `if citation_id not in registry.allowed_citation_ids` -> Lỗi Bịa ID!
  2.  **Check Nguyên văn:** `if normalized(quoted_text) not in normalized(content_raw)` -> Lỗi Trích dẫn sai chữ/Diễn giải tóm tắt!
  3.  **Check ID Đường đi:** `if path_id not in registry.allowed_path_ids` -> Lỗi Bịa đường dẫn logic!
  4.  **Check Tính logic:** Nếu user hỏi bãi bỏ mà LLM đưa path không chứa chữ `REPEALS` -> Lỗi Dùng sai bằng chứng!

### 2.6. Vòng lặp tự sửa (Self-Correction Loop)

- Nếu `GroundingValidator` bắn ra lỗi, hệ thống không bỏ cuộc ngay.
- Nó ghép dòng báo lỗi đỏ lòm (Ví dụ: "Mày trích dẫn sai nguyên văn ở ID K1_A5") vào cuối Prompt cũ, gửi lại cho LLM ép làm lại (cho phép làm lại 1 lần).
- Nếu lần 2 vẫn dính chưởng -> Hệ thống tự động trả về `Cannot Answer` để bảo vệ an toàn pháp lý. Nếu qua cửa -> Trả về câu trả lời cho Frontend.

---

## Sơ Đồ Ánh Xạ Component Code (Codebase Mapping)

Dưới đây là danh sách đường dẫn tới file code cụ thể của từng Component tương ứng với luồng chạy ở trên:

### Tầng 1: Thu thập dữ liệu (Retrieval)

Nằm chủ yếu trong thư mục `src/retrieval/` và `src/infrastructure/`.

| Component                                           | Đường dẫn file                               |
| --------------------------------------------------- | -------------------------------------------- |
| **RetrievalRuntime** (Hệ thống điều phối chính)     | [`src/retrieval/runtime/runtime.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/runtime/runtime.py)           |
| **Router** (Phân loại câu hỏi)                      | [`src/retrieval/routing/router.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/routing/router.py)            |
| **ReciprocalRankFusion** (Trộn & chấm điểm RRF)     | [`src/retrieval/fusion.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/fusion.py)                    |
| **BGEReranker** (Chấm điểm lại)                     | [`src/retrieval/reranking/bge_reranker.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/reranking/bge_reranker.py)    |
| **GraphRetriever** (Xử lý Expansion & lọc đường đi) | [`src/retrieval/retriever/graph.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/retriever/graph.py)           |
| **Graph Expansion Cypher** (Câu lệnh truy vấn DB)   | [`src/infrastructure/neo4j/retriever_repo.py`](file:///home/lamdx4/Projects/graph-RAG/src/infrastructure/neo4j/retriever_repo.py) |
| **TemporalFilter** (Lọc hiệu lực thời gian)         | [`src/retrieval/temporal.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/temporal.py)                  |
| **ContextBuilder** (Gói dữ liệu thành Context)      | [`src/retrieval/context/context_builder.py`](file:///home/lamdx4/Projects/graph-RAG/src/retrieval/context/context_builder.py)   |

### Tầng 2: Sinh câu trả lời (Generation)

Nằm toàn bộ trong thư mục `src/generation/`.

| Component                                                  | Đường dẫn file                          |
| ---------------------------------------------------------- | --------------------------------------- |
| **AnswerGenerator** (Hệ thống điều phối, quản lý Retry)    | [`src/generation/service.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/service.py)             |
| **EvidenceSufficiencyPolicy** (Chặn câu hỏi thiếu dữ kiện) | [`src/generation/sufficiency.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/sufficiency.py)         |
| **EvidenceValidator** (Lọc Prompt Injection)               | [`src/generation/evidence_validation.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/evidence_validation.py) |
| **EvidenceCompactor** (Phân nhóm Bundle & Tính Budget)     | [`src/generation/evidence_compaction.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/evidence_compaction.py) |
| **ContextProjector** (Ép kiểu JSON & Tạo Sổ Nam Tào)       | [`src/generation/context_projection.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/context_projection.py)  |
| **GroundingValidator** (Kiểm duyệt gắt gao kết quả LLM)    | [`src/generation/grounding.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/grounding.py)           |
| **Output Contract & Prompt Models**                        | [`src/generation/models.py`](file:///home/lamdx4/Projects/graph-RAG/src/generation/models.py)              |
