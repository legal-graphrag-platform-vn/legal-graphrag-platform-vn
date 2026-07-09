# Project Phases — Legal GraphRAG

> **Mô hình**: Phase Gate — mỗi phase chỉ được bắt đầu khi phase trước đã pass toàn bộ Exit Criteria.  
> **Triết lý**: Thà chậm mà chắc hơn code nhanh rồi sửa lại từ đầu.

---

## Tổng Quan

```
Phase 0          Phase 1          Phase 2          Phase 3          Phase 4          Phase 5          Phase 6
Foundation  ───► Graph Build ───► Retrieval   ───► Generation  ───► Evaluation  ───► Deployment ───► Report & Defense
(1-2 tuần)       (3-4 tuần)       (3-4 tuần)       (2 tuần)         (3 tuần)         (2 tuần)         (2 tuần)

                  RC2               RC3 + RC4         RC4 + XAI        RC5              Demo             Luận văn
```


---

## Phase 0 — Foundation (Nền Tảng)

### Mục Tiêu
Thiết lập môi trường, chốt ontology, và xác nhận mọi giả định kỹ thuật trước khi viết bất kỳ dòng code nghiệp vụ nào.

> [!CAUTION]
> Đây là phase quan trọng nhất. Sai ở đây = sửa lại toàn bộ sau này.

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P0-1 | Setup Docker Compose: Neo4j 5.11+ Community | DevOps |
| P0-2 | Verify Neo4j vector index: chạy `CREATE VECTOR INDEX` thử | DevOps |
| P0-3 | Kiểm tra raw web text của tất cả văn bản trong corpus | Data |
| P0-4 | Review và sign-off `legal_ontology.md` | Cả nhóm |
| P0-5 | Viết `tests/test_ontology_consistency.py` và chạy pass | Backend |
| P0-6 | Chốt toàn bộ `09_open_questions.md` Q1-Q15 còn lại, hoặc gán owner + deadline cho câu chưa thể chốt ngay | Cả nhóm |
| P0-7 | Setup repo structure: `src/`, `tests/`, `data/`, `scripts/` | Lead |
| P0-8 | Pre-built concept list ~50 entries (ADR-14, Q14) | Data |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C0-1 | Neo4j 5.11+ Community chạy được Vector Index | `CREATE VECTOR INDEX test_idx FOR (n:Test) ON n.v OPTIONS {...}` không lỗi |
| C0-2 | 100% văn bản trong corpus có `source.txt` và `metadata.json` | Script check: raw crawl tồn tại cho mọi `doc_id` |
| C0-3 | 5/5 unit tests trong `test_ontology_consistency.py` pass | `pytest tests/test_ontology_consistency.py` → 5 passed |
| C0-4 | RELATION_ENUM == set(CONSTRAINTS.keys()) | Test C0-3 đã bao gồm |
| C0-5 | Tất cả Q1-Q15 trong `09_open_questions.md` đã có Decision hoặc owner + deadline rõ ràng | Decision Log điền đầy đủ |
| C0-6 | `legal_ontology.md` được sign-off bởi cả nhóm | Git commit có message "chốt ontology" |

---

## Phase 1 — Graph Construction Pipeline (RC2)

### Mục Tiêu
Xây dựng pipeline tự động chuyển đổi văn bản pháp luật từ web crawl sang Knowledge Graph trong Neo4j với quality control hai tầng và confidence scoring.

> **RC2**: Automated Legal Knowledge Graph Construction with Quality Control

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P1-0 | Document Crawler: crawl web text + metadata (Step 0) | Data |
| P1-1 | Hierarchy Parser: raw text → structured JSON (Điều/Khoản/Điểm) | Backend |
| P1-2 | LLM Entity Extraction prompt + JSON Schema validation | AI/ML |
| P1-3 | LLM Relation Extraction prompt + Ontology Validation | AI/ML |
| P1-4 | Rule-based Confidence Scorer (ADR-06) | Backend |
| P1-5 | Decision Gate: Auto-accept / Human Review / Reject | Backend |
| P1-6 | Neo4j Writer: tạo nodes + relationships + embedding | Backend |
| P1-7 | Annotate 3 văn bản gold standard (ground truth triples) | Data |
| P1-8 | Calibrate confidence threshold trên 3 văn bản gold | AI/ML |
| P1-9 | Chạy pipeline trên 4 văn bản bắt buộc | Cả nhóm |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C1-1 | Hierarchy Parser detect đúng ranh giới Điều/Khoản/Điểm | Manual check: so sánh output parser với `source.txt` gốc trên 2 văn bản |
| C1-2 | Relation Extraction Precision ≥ 0.75 | Đo trên 3 văn bản gold standard |
| C1-3 | Relation Extraction Recall ≥ 0.65 | Đo trên 3 văn bản gold standard |
| C1-4 | REFERS_TO và REQUIRES không bị reject bởi validator | Unit test `test_refers_to_not_rejected()` + `test_requires_not_rejected()` pass |
| C1-5 | Graph có ≥ 500 nodes và ≥ 300 relations hợp lệ | Cypher: `MATCH (n) RETURN count(n)` và `MATCH ()-[r]->() RETURN count(r)` |
| C1-6 | Confidence threshold được chọn dựa trên PR curve | PR curve plot tồn tại trong `results/phase1_pr_curve.png` |
| C1-7 | Pipeline chạy không crash trên 4 văn bản bắt buộc | Pipeline exit code 0, log không có unhandled exception |
| C1-8 | Vector embedding được lưu vào Neo4j cho Article và Clause | `MATCH (a:Article) WHERE a.embedding IS NOT NULL RETURN count(a)` > 0 |

---

## Phase 2 — Retrieval & Temporal Reasoning (RC3 + RC4)

### Mục Tiêu
Xây dựng Unified Hybrid Retrieval Pipeline: semantic search → intent-based graph traversal → temporal filter trong một workflow coherent.

> **RC3**: Intent-based Graph Traversal Policy  
> **RC4**: Temporal-aware Legal Reasoning

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P2-1 | Intent Classifier: 6 classes với few-shot LLM | AI/ML |
| P2-2 | Traversal Policy table: intent → relations → depth | AI/ML + Backend |
| P2-3 | Neo4jRetriever: unified Cypher (vector + traversal + temporal) | Backend |
| P2-4 | Temporal filter logic: time-travel query theo `effective_from/to` | Backend |
| P2-5 | RetrieverInterface: abstract class + mock cho testing | Backend |
| P2-6 | Context assembler: merge retrieved nodes thành coherent context | Backend |
| P2-7 | 20 test queries cho intent classification (annotated) | Data |
| P2-8 | 10 temporal test queries (annotated với expected version) | Data |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C2-1 | Intent Classifier accuracy ≥ 0.80 trên 20 test queries | Manual annotation + confusion matrix |
| C2-2 | Traversal Policy table có đủ 6 intent → relation mapping | Review `05_graphrag_retrieval.md` policy table |
| C2-3 | Temporal query resolve đúng version trên 10 test cases | Manual verify: "Điều X tại ngày Y" → correct node returned |
| C2-4 | `AMENDS` cross-level (Article→Clause) được traverse đúng | Test query với văn bản đã có sửa đổi cross-level |
| C2-5 | End-to-end: query → context ≤ 3 giây (local, không tính LLM) | `time python retrieve.py --query "..."` |
| C2-6 | `RetrieverInterface` có mock implementation cho unit test | `pytest tests/test_retriever.py` pass |
| C2-7 | `GUIDES` resolve được Law→Circular (direct) | Test query với văn bản có Luật giao thẳng cho Thông tư |

---

## Phase 3 — Generation & XAI (RC4 + RC5 prep)

### Mục Tiêu
Xây dựng generation layer với citation tracing và explainable reasoning path. Đây là "mặt tiền" của hệ thống — output mà người dùng và hội đồng nhìn thấy.

> **RC4** (tiếp): Explainable citation từ graph path  
> **RC5** (chuẩn bị): XAI evaluation cases

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P3-1 | Prompt engineering: legal QA với context từ Phase 2 | AI/ML |
| P3-2 | Citation extractor: map câu trả lời → Article/Clause IDs | Backend |
| P3-3 | XAI explanation: format reasoning path thành human-readable | Backend |
| P3-4 | Response formatter: answer + citations + reasoning path | Backend |
| P3-5 | 20 XAI test cases (query + expected reasoning path) | Data |
| P3-6 | Human review: 3 người check 20 XAI cases | Cả nhóm |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C3-1 | ≥ 80% câu trả lời có ít nhất 1 citation đúng | Manual check trên 30 random queries |
| C3-2 | Reasoning path trace được về đúng Article/Clause gốc | `source_article` property trên REQUIRES được cite đúng |
| C3-3 | ≥ 15/20 XAI test cases pass human review | Review session với cả nhóm |
| C3-4 | Response format nhất quán: answer + citations + path | Code review + visual check |
| C3-5 | System không hallucinate Article ID không tồn tại trong graph | Verify mọi cited ID bằng Neo4j lookup |

---

## Phase 4 — Evaluation Framework (RC5)

### Mục Tiêu
Xây dựng bộ ground truth và chạy toàn bộ evaluation framework 4 tầng. So sánh với baseline Vector RAG. Chạy ablation studies.

> **RC5**: 4-Level Evaluation Framework với Ground Truth tự xây

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P4-1 | Hoàn thiện ground truth: ≥ 50 QA + ≥ 25 temporal QA | Data |
| P4-2 | Implement Baseline: Naive Vector RAG (token-based chunk) | Backend |
| P4-3 | Level-1: Relation Extraction Precision/Recall | AI/ML |
| P4-4 | Level-2: QA Faithfulness + Context Recall (RAGAS) | AI/ML |
| P4-5 | Level-3: Temporal Accuracy trên 25 temporal queries | AI/ML |
| P4-6 | Level-4: Citation Completeness + XAI Coherence | AI/ML |
| P4-7 | Ablation 1: Graph expansion ON vs OFF | Backend + AI/ML |
| P4-8 | Ablation 2: Traversal depth 1 vs 2 vs 3 | Backend + AI/ML |
| P4-9 | Ablation 3: Temporal filter ON vs OFF | Backend + AI/ML |
| P4-10 | Ablation 4: Intent-based vs fixed traversal | Backend + AI/ML |
| P4-11 | Compile kết quả vào bảng so sánh | AI/ML |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C4-1 | Ground truth ≥ 50 QA + ≥ 25 temporal QA + ≥ 20 XAI | Count trong ground truth file |
| C4-2 | Baseline Vector RAG chạy được trên cùng ground truth | Baseline script exit code 0 với metrics output |
| C4-3 | Proposed system beats baseline trên ≥ 3/4 metrics | Bảng so sánh có số thực |
| C4-4 | Temporal Accuracy của proposed > baseline (expected: >2x) | Level-3 metric so sánh |
| C4-5 | 4 ablation experiments có kết quả đo được | Results file tồn tại với số liệu thực |
| C4-6 | Không có số liệu "estimate" hay "hypothesis" trong kết quả | Review kỹ báo cáo — chỉ số thực từ experiment |
| C4-7 | Concept/Entity evaluation dùng pre-defined list (Q14) | `entity_normalizer.py` tồn tại và được dùng trong eval |

---

## Phase 5 — UI & Deployment

### Mục Tiêu
Đóng gói hệ thống để demo và bảo vệ. UI đơn giản nhưng đủ để trình bày các contribution một cách trực quan.

> **Quyết định từ Q2a**: Gradio/Streamlit nếu nhóm < 3 người hoặc thời gian < 1 tháng.

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P5-1 | Docker Compose: Neo4j + API server + Frontend | DevOps |
| P5-2 | API: FastAPI endpoints cho query, temporal query | Backend |
| P5-3 | UI: Query input + Answer + Citations + Reasoning path | Frontend |
| P5-4 | UI: Graph visualizer (basic — pyvis hoặc Cytoscape.js) | Frontend |
| P5-5 | UI: Timeline slider cho temporal query | Frontend |
| P5-6 | Demo script: 5 câu hỏi đại diện cho 5 RC | Cả nhóm |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C5-1 | `docker-compose up` khởi động toàn bộ system không lỗi | Cold start từ zero trên máy sạch |
| C5-2 | End-to-end: query → answer với citation ≤ 10 giây | Đo thời gian với 5 câu hỏi demo |
| C5-3 | UI hiển thị được reasoning path dạng graph | Visual check |
| C5-4 | Temporal query: slider hoặc input date hoạt động | Functional test với temporal queries |
| C5-5 | Demo 5 câu hỏi chạy không lỗi | Dry run trước ngày bảo vệ |

---

## Phase 6 — Report & Defense

### Mục Tiêu
Viết luận văn hoàn chỉnh với đầy đủ bằng chứng thực nghiệm. Chuẩn bị trả lời hội đồng dựa trên ADR documents.

### Việc Cần Làm

| Task | Mô Tả | Người Phụ Trách |
|---|---|---|
| P6-1 | Literature Review: Vietnamese Legal NLP (Q15) | Leader |
| P6-2 | Viết Chapter 2 (Related Work) với positioning rõ ràng | Leader |
| P6-3 | Viết Chapter 3 (Methodology) từ ADR documents | Cả nhóm |
| P6-4 | Viết Chapter 4 (Experiments) từ Phase 4 results | AI/ML |
| P6-5 | Viết Chapter 5 (Conclusion + Future Work) | Leader |
| P6-6 | Mock defense: thử trả lời 10 câu hỏi hội đồng điển hình | Cả nhóm |
| P6-7 | Final review: đảm bảo số liệu trong báo cáo = số liệu thực | Cả nhóm |

### ✅ Exit Criteria — Phải Pass Tất Cả

| # | Tiêu Chí | Cách Verify |
|---|---|---|
| C6-1 | Related work đề cập ít nhất 3 paper về Vietnamese legal NLP | Kiểm tra references |
| C6-2 | Mọi số liệu trong Chapter 4 có thể reproduce được | Chạy lại script, kết quả match |
| C6-3 | Contribution framing là vendor-neutral (ADR-11) | Review Chapter 3 |
| C6-4 | Mock defense pass: trả lời được 8/10 câu hỏi hội đồng | Internal mock session |
| C6-5 | 17 ADRs trong `00_architecture_decisions.md` đã có justification | Dùng làm reference khi bảo vệ |

---

## Phase Gate Summary

```
Phase 0    Phase 1    Phase 2    Phase 3    Phase 4    Phase 5    Phase 6
 6 criteria  8 criteria  7 criteria  5 criteria  7 criteria  5 criteria  5 criteria
    ↓           ↓           ↓           ↓           ↓           ↓           ↓
 PASS ALL → PASS ALL → PASS ALL → PASS ALL → PASS ALL → PASS ALL → DEFENSE
```

---

## Tracking Template

Sau mỗi phase, điền vào bảng này:

| Phase | Bắt Đầu | Kết Thúc | # Criteria Pass | # Criteria Fail | Ghi Chú |
|---|---|---|---|---|---|
| Phase 0 | ? | ? | ? / 6 | ? | |
| Phase 1 | ? | ? | ? / 8 | ? | |
| Phase 2 | ? | ? | ? / 7 | ? | |
| Phase 3 | ? | ? | ? / 5 | ? | |
| Phase 4 | ? | ? | ? / 7 | ? | |
| Phase 5 | ? | ? | ? / 5 | ? | |
| Phase 6 | ? | ? | ? / 5 | ? | |

> **Quy tắc**: Nếu fail bất kỳ criterion nào trong một phase → **không được chuyển sang phase tiếp theo**.  
> Fix xong, verify lại, rồi mới tiếp tục.
