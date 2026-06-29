# Implementation Timeline

> **Tổng thời gian**: 5 tháng (ước tính)  
> **Cập nhật**: cần điều chỉnh theo deadline thực tế của nhóm

---

## Tháng 1 — Foundation & Research

**Mục tiêu**: Hoàn thiện nền tảng lý thuyết và thiết kế

### Tuần 1-2: Literature Review
- [ ] Đọc Microsoft GraphRAG paper (Edge et al., 2024)
- [ ] Đọc "Unifying LLMs and KGs" survey (Pan et al., 2024)
- [ ] Đọc Temporal KG papers (TComplEx, RAGAS)
- [ ] Tổng hợp related work → viết mục 2 luận văn

### Tuần 3: Ontology Finalization
- [ ] Chốt toàn bộ Node Types (xem `02_ontology_specification.md`)
- [ ] Chốt toàn bộ Relation Types
- [ ] Viết Ontology Constraints
- [ ] Review với supervisor

### Tuần 4: Data Collection
- [ ] Thu thập 20 văn bản pháp luật (xem `08_dataset_and_scope.md`)
- [ ] Convert PDF → text, check quality
- [ ] Annotate thủ công 3 văn bản (gold standard cho RC5)
- [ ] Setup Neo4j + Vector Store locally

**Deliverable cuối tháng 1**: 
- Ontology document hoàn chỉnh
- 20 PDF đã thu thập
- 3 văn bản annotated (gold standard)

---

## Tháng 2 — Graph Construction Pipeline (RC2)

**Mục tiêu**: Pipeline hoạt động end-to-end, 20 văn bản được nhập vào graph

### Tuần 1: Hierarchy Parser
- [ ] Implement PyMuPDF-based parser
- [ ] Handle: Điều, Khoản, Điểm, Chương
- [ ] Handle edge cases: bảng biểu, phụ lục, footnotes
- [ ] Unit test với 5 văn bản

### Tuần 2: LLM Extraction
- [ ] Thiết kế prompt template (entity + relation extraction)
- [ ] Implement JSON Schema Validation
- [ ] Test với Gemini Flash API
- [ ] Collect extraction samples để tính precision/recall

### Tuần 3: Validation Pipeline
- [ ] Implement Ontology Validator (rule-based)
- [ ] Implement Confidence Scorer (self-consistency N=3)
- [ ] Implement Human Review Queue
- [ ] Integration test toàn pipeline

### Tuần 4: Data Ingestion
- [ ] Chạy pipeline với 20 văn bản
- [ ] Manual review + fix errors
- [ ] Tính Entity/Relation Precision & Recall (Level 1 evaluation)
- [ ] Document kết quả

**Deliverable cuối tháng 2**:
- Knowledge Graph trong Neo4j với 20 văn bản
- Kết quả Level 1 Evaluation (precision/recall)

---

## Tháng 3 — GraphRAG Core (RC3 + RC4)

**Mục tiêu**: Hệ thống retrieval + generation hoạt động

### Tuần 1: Vector Search + Intent Classifier
- [ ] Generate embeddings cho tất cả Articles/Clauses
- [ ] Setup ChromaDB / Qdrant
- [ ] Implement Intent Classifier (few-shot LLM)
- [ ] Implement Temporal Expression Extractor
- [ ] Test với 20 câu hỏi mẫu

### Tuần 2: Graph Traversal + Traversal Policy
- [ ] Implement Traversal Policy theo intent
- [ ] Implement Temporal Filter cho Cypher queries
- [ ] Test Time Travel Queries
- [ ] Validate traversal results với gold standard

### Tuần 3: Reranker + Context Builder
- [ ] Implement BM25 hybrid reranker (baseline)
- [ ] Implement Context Builder (chunks + graph paths)
- [ ] Implement Answer Generation với structured output
- [ ] End-to-end test: query → answer + citation

### Tuần 4: XAI + Reasoning Path
- [ ] Implement Reasoning Path extraction từ traversal
- [ ] Format reasoning path dạng human-readable
- [ ] Test Citation Completeness
- [ ] Tính Level 2-3 Evaluation (RAGAS)

**Deliverable cuối tháng 3**:
- GraphRAG system hoạt động end-to-end
- Kết quả Level 2-3 Evaluation

---

## Tháng 4 — Evaluation + UI (RC5)

**Mục tiêu**: Kết quả experiment đầy đủ, UI demo được

### Tuần 1: Ground Truth Dataset
- [ ] Tạo 100 câu hỏi general QA
- [ ] Tạo 50 câu hỏi temporal QA (có năm cụ thể)
- [ ] Tạo 20-30 câu XAI evaluation
- [ ] Review dataset (tự review cross-check)

### Tuần 2: Full Evaluation
- [ ] Chạy evaluation với Baseline 1 (BM25)
- [ ] Chạy evaluation với Baseline 2 (Naive RAG)
- [ ] Chạy evaluation với Proposed system
- [ ] Tính Level 4: Temporal Accuracy, Citation Completeness
- [ ] Tổng hợp kết quả → bảng so sánh

### Tuần 3: Frontend UI
- [ ] Setup React app
- [ ] Implement Chat Interface
- [ ] Implement Citation Panel
- [ ] Implement Graph Visualizer (D3.js)
- [ ] Implement Timeline/Temporal Filter UI

### Tuần 4: Integration & Demo
- [ ] Integrate frontend với backend API
- [ ] End-to-end testing
- [ ] Fix bugs, polish UI
- [ ] Prepare demo scenarios

**Deliverable cuối tháng 4**:
- Bảng kết quả evaluation đầy đủ
- Demo UI hoạt động

---

## Tháng 5 — Report + Defense

### Tuần 1-2: Viết Báo Cáo
- [ ] Chương 1: Giới thiệu + Research Questions
- [ ] Chương 2: Related Work
- [ ] Chương 3: Phương pháp (RC1-RC4)
- [ ] Chương 4: Kết quả thực nghiệm (RC5)
- [ ] Chương 5: Kết luận + Future Work

### Tuần 3: Review & Revision
- [ ] Supervisor review
- [ ] Fix comments
- [ ] Finalize appendix (ontology, dataset stats)

### Tuần 4: Chuẩn Bị Bảo Vệ
- [ ] Làm slides (15-20 trang)
- [ ] Rehearse demo
- [ ] Chuẩn bị câu trả lời cho các câu hỏi phổ biến

---

## Phân Công Nhóm (Placeholder — cần điền)

| Thành Viên | Phụ Trách |
|---|---|
| ? | RC2 — Graph Construction Pipeline |
| ? | RC3 — GraphRAG Retrieval |
| ? | RC4 — Temporal Logic |
| ? | RC5 — Evaluation Framework |
| ? | Frontend UI |
| ? | Báo Cáo + Literature Review |

---

## Rủi Ro và Phương Án Dự Phòng

| Rủi Ro | Khả Năng | Phương Án |
|---|---|---|
| LLM extraction chất lượng thấp | Cao | Tăng N trong self-consistency, thêm few-shot examples |
| PDF parsing phức tạp hơn dự kiến | Trung bình | Dùng Unstructured.io hoặc Azure Document Intelligence |
| Ground truth dataset thiếu | Cao | Giảm xuống 50 câu general + 30 temporal |
| Neo4j performance chậm với graph lớn | Thấp | Optimize Cypher query, add indexes |
| API cost vượt budget | Trung bình | Dùng local model (Ollama + Llama3) |
| Không đủ thời gian làm UI | Trung bình | Demo bằng Gradio thay vì React |
