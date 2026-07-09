# Implementation Timeline — Legal GraphRAG

> **Cập nhật**: 2026-07-07  
> **Đánh giá**: Research ⭐⭐⭐⭐⭐ | Engineering ⭐⭐⭐⭐☆ | Hoàn thành ⭐⭐⭐⭐☆  
> **Triết lý**: Ưu tiên giá trị nghiên cứu → Experiment → Portal.
> **Depends on**: [legal_ontology.md v1.4.0](./legal_ontology.md)

---

## Research Contributions

| # | Contribution |
|---|---|
| **RC1** | Legal Ontology cho luật doanh nghiệp Việt Nam |
| **RC2** | Ontology-guided Graph Construction Pipeline |
| **RC3** | Temporal Ontology-based Hybrid Graph Retrieval |
| **RC4** | Explainable Legal QA với Citation + Reasoning Path |
| **RC5** | Evaluation Framework cho Legal GraphRAG |

> Đây là 5 chương chính của luận văn.

---

## Trạng Thái Hiện Tại

```
Phase 0 — Foundation          ✅ DONE
Phase 1 — Pipeline M1+M2      ✅ DONE  (Crawler → Parser → NER → Relation → Validator → Scorer → JSONL)
Phase 1 — Pipeline M3         ❌ CHƯA  (Neo4j Writer, Embedding)
Milestone A — Graph Build     ❌ CHƯA
Phase 2 — Hybrid Retrieval    ❌ CHƯA
Milestone B — Retrieval       ❌ CHƯA
Phase 3 — LLM + Citation      ❌ CHƯA
Milestone C — QA              ❌ CHƯA
Phase 4 — Evaluation          ❌ CHƯA
Milestone D — Evaluation      ❌ CHƯA
Phase 5 — Portal              ❌ CHƯA
```

**Tiến độ tổng thể**: ~28%

---

## Ưu Tiên Theo Contribution Nghiên Cứu

| Module | Mức độ cần | Ghi chú |
|---|---|---|
| Crawler + Parser + Extraction | ⭐⭐⭐⭐⭐ | Core RC2 — **Đã xong** |
| Ontology + Graph Builder | ⭐⭐⭐⭐⭐ | Core RC2 — **M3 cần làm ngay** |
| Graph Quality Evaluation | ⭐⭐⭐⭐⭐ | Bắt buộc trước khi sang retrieval |
| Hybrid Retrieval (Ablation) | ⭐⭐⭐⭐⭐ | Core RC3 |
| LLM + Citation + Reasoning | ⭐⭐⭐⭐⭐ | Core RC4 |
| Evaluation (5 levels + Human) | ⭐⭐⭐⭐⭐ | Core RC5 — quan trọng hơn Portal |
| Error Analysis | ⭐⭐⭐⭐⭐ | Bắt buộc cho bảo vệ |
| Web Portal | ⭐⭐⭐⭐☆ | Demo — sau research |
| RabbitMQ / PostgreSQL / MinIO | ❌ BỎ | Không contribution — không làm |

---

## Phase 1 — Graph Construction Pipeline ✅ DONE (M1 + M2)

> Phạm vi đã hoàn thành: Crawler → Parser → NER → Relation Extraction → Ontology Validation → Confidence Scoring → JSONL.

### Bug cần fix trước M3

- [ ] **Bug `properties={}`**: `orchestrator.py` truyền `properties={}` cứng → temporal relations (`AMENDS`, `REPLACES`, `REPEALS`) luôn bị reject sai vì thiếu `effective_from`. Phải truyền properties thực từ LLM output.
- [ ] **URL crawler**: cập nhật URL vbpl.vn đúng format (đã phát hiện 404).

---

## Phase 1 — M3: Neo4j Writer + Embedding ❌ → Milestone A

**Mục tiêu**: Đưa JSONL vào Neo4j, sinh embedding, hoàn thiện Knowledge Graph.

### Tuần 1: Neo4j Writer

- [ ] Implement `src/writer/neo4j_writer.py`
  - Map JSONL → Cypher `MERGE` (document, article, clause, point nodes)
  - Tạo relationships từ validated relations
  - Gắn `effective_from`, `effective_to`, `legal_status`, `doc_type` đúng schema
- [ ] Chạy writer với LDN2020 JSONL output
- [ ] Verify: `MATCH (a:Article) RETURN count(a)` → đúng 218

### Tuần 2: Embedding Generator + Vector Index

- [ ] Dùng embedding model chính: `bkai-foundation-models/vietnamese-bi-encoder` (768-dim, khớp Neo4j vector index)
- [ ] Fallback nếu chất lượng không đủ: `BAAI/bge-m3` sau khi verify dimension và cập nhật vector index nếu khác 768
- [ ] Implement `src/writer/embedding_generator.py` — batch processing, 768-dim
- [ ] Load vào Neo4j vector index (`article_embedding`, `clause_embedding`)
- [ ] Verify: `CALL db.index.vector.queryNodes(...)` trả về kết quả

### Tuần 3: Graph Quality Evaluation ← *Thêm mới — không bỏ qua*

> [!IMPORTANT]
> Không nhảy ngay sang retrieval. Phải đo chất lượng graph trước.

- [ ] Đo **Entity count** theo từng label (Document, Article, Clause, Point, LegalConcept, LegalSubject, LegalAction)
- [ ] Đo **Relation count** theo từng type (CONTAINS, AMENDS, ...)
- [ ] Đo **Ontology violation rate** — số relations bị reject / tổng relations extracted
- [ ] Đo **Coverage** — % Điều có ít nhất 1 relation ngoài CONTAINS
- [ ] Đo **Duplicate rate** — node trùng ID
- [ ] Đo **Orphan nodes** — node không có edge nào
- [ ] Đo **Graph density** và **Average degree**
- [ ] Đo **Connected components** — graph có connected không hay bị tách rời
- [ ] Viết báo cáo Graph Quality (đưa vào luận văn Chương 4)

### 🏁 Milestone A — Graph Build Success

| # | Tiêu chí | Verify |
|---|---|---|
| A-1 | 218 Article nodes | `MATCH (a:Article) RETURN count(a)` = 218 |
| A-2 | Relations được ghi | `MATCH ()-[r]->() RETURN type(r), count(r)` |
| A-3 | Vector search hoạt động | Top-5 query trả về đúng Article |
| A-4 | Schema constraints 0 violation | `SHOW CONSTRAINTS` |
| A-5 | Graph Quality Report hoàn chỉnh | File report tồn tại |

---

## Phase 2 — Hybrid Retrieval ❌ → Milestone B

**Mục tiêu**: RC3 — Temporal Ontology-based Hybrid Graph Retrieval.

### Chia nhỏ thành sub-phase để Ablation Study

```
2.1  Vector Retrieval only
  ↓
2.2  Vector + Graph Expansion
  ↓
2.3  Vector + Graph + Temporal Filter
  ↓
2.4  Hybrid Fusion (+ BM25)
  ↓
2.5  + Reranker (Cross Encoder)
  ↓
  ↓
Evidence Verifier
```

> Mỗi sub-phase đều benchmark riêng → đây chính là **Ablation Study** cho luận văn.

### Triển khai

- [ ] **2.1** Intent Classifier: phân loại 6 lớp `factual / validity / hierarchy / comparison / definition / multi_hop`
- [ ] **2.1** Vector Retriever: `queryNodes` trên `article_embedding` / `clause_embedding`
- [ ] **2.2** Graph Expansion: từ vector results, traverse `CONTAINS`, `AMENDS`, `REFERS_TO` để lấy context liên quan
- [ ] **2.3** Temporal Filter: Cypher filter theo `effective_from` / `effective_to` tại thời điểm T trong query
- [ ] **2.4** BM25 Fulltext fusion (Neo4j fulltext index đã có trong schema)
- [ ] **2.5** Cross Encoder Reranker (default candidate: `bge-reranker-v2-m3`; ablation candidate: `Qwen3-Reranker-0.6B`)
- [ ] Evidence Verifier: check retrieved context chứa evidence thực
- [ ] **Benchmark từng bước** với **50 câu hỏi dev split** → Recall@5, MRR, nDCG  
  *(50 = dev split của 100 QA total; test split 50 còn lại dùng trong Phase 4 final eval)*

### 🏁 Milestone B — Retrieval Success

| # | Tiêu chí |
|---|---|
| B-1 | Recall@5 ≥ 0.7 trên 50 câu hỏi |
| B-2 | Temporal query trả về đúng văn bản hiệu lực tại ngày được hỏi |
| B-3 | Graph traversal tìm được AMENDS, REPLACES đúng |
| B-4 | Ablation study table hoàn chỉnh (5 dòng: 2.1 → 2.5) |

---

## Phase 3 — LLM + Citation + Reasoning Path ❌ → Milestone C

**Mục tiêu**: RC4 — Explainable Legal QA, không hallucinate, citation cụ thể.

- [ ] Answer Generator với retrieved context làm grounding
- [ ] **Strict Citation**: mỗi câu trả lời phải có `[Điều X, Khoản Y, Luật Z]`
- [ ] **Reasoning Path**: serialize graph traversal → human-readable explanation
- [ ] Anti-hallucination check: câu trả lời phải nằm trong retrieved context
- [ ] End-to-end test: query → retrieval → answer + citation + reasoning path

### 🏁 Milestone C — QA Success

| # | Tiêu chí |
|---|---|
| C-1 | Faithfulness ≥ 0.8 (RAGAS) |
| C-2 | 100% câu trả lời có ít nhất 1 citation |
| C-3 | Reasoning path không rỗng |

---

## Phase 4 — Evaluation Framework ❌ → Milestone D

**Mục tiêu**: RC5 — Chứng minh GraphRAG tốt hơn baseline với số liệu rõ ràng.

> [!IMPORTANT]
> Đây là phần hội đồng quan tâm nhất. Thiếu evaluation = không có contribution.

### Evaluation 5 Levels

**Level 1 — Parser**
- Hierarchy Accuracy: số Điều nhận diện đúng / tổng Điều thật

**Level 2 — Extraction**
- NER F1 (so với ground truth annotated)
- Relation F1

**Level 3 — Graph**
- Ontology violation rate
- Coverage rate
- Graph density metrics (từ Milestone A)

**Level 4 — Retrieval**
- Recall@5, Recall@10
- MRR (Mean Reciprocal Rank)
- nDCG@10

**Level 5 — Generation**
- Faithfulness (RAGAS)
- Answer Relevancy (RAGAS)
- Context Recall (RAGAS)
- Citation Accuracy (custom)
- Temporal Accuracy (custom)

### Dataset Evaluation

- [ ] Current committed scope: **50 câu hỏi general QA** từ corpus đã chọn
- [ ] Target full scope nếu còn thời gian: **100 câu hỏi general QA** từ LDN2020 + 2-3 văn bản khác
  *Split: 50 dev (dùng Phase 2-3 tune) + 50 test (hold-out, dùng Phase 4 final eval)*
- [ ] Current committed scope: **25 câu hỏi temporal** (có thời điểm cụ thể)
- [ ] Target full scope nếu còn thời gian: **50 câu hỏi temporal**
  *Split: 25 dev + 25 test*
- [ ] Tạo **Ground Truth** (câu trả lời đúng + citation đúng) cho 150 câu  
  *Minimum accepted/current committed scope: 50 general + 25 temporal. Target full scope: 100 general + 50 temporal.*
- [ ] Review cross-check

### Baselines So Sánh

| Baseline | Mô tả |
|---|---|
| Naive RAG | Main baseline: Vector search + LLM, không có graph |
| BM25 | Optional ablation: full-text search thuần nếu còn thời gian |
| **Proposed: GraphRAG** | Vector + Graph + Temporal + Reranker |

### Expected Metrics

| Metric | Naive RAG | Optional BM25 | GraphRAG |
|---|---|---|---|
| Faithfulness | ~0.60 | - | **≥ 0.80** |
| Answer Relevancy | ~0.65 | - | **≥ 0.75** |
| Context Recall | ~0.60 | ~0.50 | **≥ 0.70** |
| Temporal Accuracy | ~0.40 | ~0.30 | **≥ 0.85** |
| Citation Completeness | 0 | 0 | **1.0** |

### Human Evaluation

- [ ] Chọn **15-30 câu hỏi** đại diện từ current committed scope hoặc target full scope
- [ ] **3 người đánh giá** (cùng ngành luật hoặc kỹ thuật) dùng Likert 1-5
- [ ] Tiêu chí: Correctness, Helpfulness, Citation Usefulness
- [ ] Tính Kappa agreement giữa các evaluators

### Error Analysis ← *Bắt buộc*

> Hội đồng luôn hỏi: *"Những trường hợp nào hệ thống chưa làm tốt?"*

- [ ] Phân tích failure cases từng tầng:
  - Parser fail (text extraction nhận nhầm "Điều")
  - LLM hallucination (relation không có trong văn bản)
  - Ontology reject (vi phạm constraint)
  - Retrieval miss (top-K không chứa ground truth)
  - LLM answer sai (faithfulness thấp)
- [ ] Ghi cụ thể ví dụ + nguyên nhân + hướng cải thiện

### Feedback Loop (Đơn Giản)

- [ ] Ghi nhận feedback "câu trả lời sai" từ UI
- [ ] Admin review → flag node/relation sai trong Neo4j
- [ ] Re-run extraction cho văn bản bị flag

### 🏁 Milestone D — Evaluation Success

| # | Tiêu chí |
|---|---|
| D-1 | Bảng so sánh 3 baselines × 5 metrics hoàn chỉnh |
| D-2 | Ablation study 5 dòng (retrieval sub-phases) |
| D-3 | Human evaluation 30 câu × 3 người |
| D-4 | Error Analysis report hoàn chỉnh |
| D-5 | Graph Quality metrics được report |

---

## Phase 5 — Portal ❌

**Mục tiêu**: Demo được 5 tính năng core.

```
Portal
├── Search          — full-text + semantic search
├── Chat            — AI Q&A với citation + reasoning path
├── Timeline        — lịch sử sửa đổi (AMENDS / REPLACES)
├── Graph Explorer  — visualize knowledge graph (D3.js / Cytoscape)
└── Document Reader — đọc điều khoản + highlight + quan hệ liên quan
```

**Document Reader** (giống LexisNexis):
- Mở Điều X → highlight khoản được hỏi
- Hiển thị quan hệ: các điều viện dẫn, các điều sửa đổi
- Link trực tiếp đến văn bản nguồn

### Triển khai

- [ ] Backend API (FastAPI): `/search`, `/chat`, `/graph`, `/timeline`, `/document`
- [ ] Frontend (React/Vite):
  - [ ] Chat interface với citation panel + reasoning path
  - [ ] Graph Explorer (D3.js hoặc Cytoscape.js)
  - [ ] Timeline view
  - [ ] Search page
  - [ ] Document Reader với highlight + related nodes
- [ ] Graph Visualization Metrics (hiển thị trong Explorer):
  - Node count, Edge count, Graph density, Average path length
- [ ] Integrate frontend ↔ backend ↔ Neo4j
- [ ] End-to-end demo scenarios (chuẩn bị cho bảo vệ)

---

## Lộ Trình (Còn ~72% công việc)

| Phase | Thời gian | Milestone | Deliverable đo được |
|---|---|---|---|
| M3: Neo4j Writer + Embedding | Tuần 1-2 | - | 218 nodes, vector search OK |
| Graph Quality Evaluation | Tuần 3 | **Milestone A** | Quality report |
| Phase 2: Hybrid Retrieval | Tuần 4-6 | **Milestone B** | Recall@5 ≥ 0.7, ablation table |
| Phase 3: LLM + Citation | Tuần 7-8 | **Milestone C** | Faithfulness ≥ 0.8 |
| Phase 4: Evaluation | Tuần 9-10 | **Milestone D** | 3 baselines + human eval + error analysis |
| Phase 5: Portal | Tuần 11-13 | - | Demo 5 tính năng |
| Báo cáo + Bảo vệ | Tuần 14-16 | - | Luận văn hoàn chỉnh |

---

## Đã Bỏ (Không Làm)

> [!NOTE]
> Các thành phần dưới đây bị loại khỏi scope vì không tạo contribution nghiên cứu. Đây là đề tài nghiên cứu, không phải enterprise backend.

- ~~RabbitMQ / Celery~~ — không contribution
- ~~PostgreSQL~~ — không cần cho research
- ~~Object Storage (MinIO)~~ — local folder đủ dùng

---

## Rủi Ro và Phương Án Dự Phòng

| Rủi Ro | Khả năng | Phương án |
|---|---|---|
| LLM API quota hết (Gemini 20 req/ngày) | **Cao** | Qwen3 via OpenRouter (free, không limit) |
| Text extraction ~43% recall | Đã biết | Dùng crawler web text là nguồn chính |
| Embedding chậm trên CPU | Trung bình | API (Google/Cohere) hoặc batch offline |
| Ground truth thiếu | Cao | Giữ current committed scope 50 general + 25 temporal |
| Không đủ thời gian làm React | Trung bình | Demo bằng Gradio thay thế |
| Human evaluators khó tìm | Trung bình | Dùng GPT-4 làm judge thay thế (LLM-as-judge) |

---

*Xem thêm: `11_project_phases.md` (Exit Criteria chi tiết) | `01_research_contributions.md` (RC1-RC5 chi tiết)*
