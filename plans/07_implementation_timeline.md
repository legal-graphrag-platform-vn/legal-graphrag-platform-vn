# Implementation Timeline — Legal GraphRAG

> **Cập nhật**: 2026-07-17
> **Đánh giá**: Research ⭐⭐⭐⭐⭐ | Engineering ⭐⭐⭐⭐☆ | Hoàn thành ⭐⭐⭐⭐☆  
> **Triết lý**: Ưu tiên giá trị nghiên cứu → Experiment → Portal.
> **Depends on**: [legal_ontology.md v1.5.1](./legal_ontology.md)

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
Phase 1 — Pipeline M3 pilot   ✅ SIGNED OFF (L59_2020)
Gate 7 — Corpus 4 văn bản     ⏳ OPEN (M3-B13)
Milestone A — Graph Build     ❌ NOT PASSED (chờ Gate 7)
Phase 2 — Hybrid Retrieval    🟡 IMPLEMENTED ON PILOT (runtime-v2)
Milestone B — Retrieval       ❌ CHƯA
Phase 3 — LLM + Citation      🟡 IMPLEMENTED ON PILOT; QA acceptance chưa chạy lại
Milestone C — QA              ❌ CHƯA
Phase 4 — Evaluation          🟡 DEVELOPMENT DATASET/TOOLING; official evaluation chưa chạy
Milestone D — Evaluation      ❌ CHƯA
Phase 5 — Portal              🟡 PILOT UI/API đã có; deployment acceptance chưa đạt
```

> Phase 2/3 development trên pilot được phép trong khi Gate 7 còn mở. Trạng thái
> implementation không đồng nghĩa với Milestone A, B hoặc C đã pass.

---

## Ưu Tiên Theo Contribution Nghiên Cứu

| Module | Mức độ cần | Ghi chú |
|---|---|---|
| Crawler + Parser + Extraction | ⭐⭐⭐⭐⭐ | Core RC2 — **Đã xong** |
| Ontology + Graph Builder | ⭐⭐⭐⭐⭐ | Core RC2 — **pilot signed off; corpus còn mở** |
| Graph Quality Evaluation | ⭐⭐⭐⭐⭐ | Pilot đã có; phải chạy lại ở corpus level |
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

## Phase 1 — M3: Neo4j Writer + Embedding 🟡 Pilot Complete, Corpus Open

**Mục tiêu**: Đưa JSONL vào Neo4j, sinh embedding, hoàn thiện Knowledge Graph.

### Tuần 1: Neo4j Writer

- [x] Implement `src/infrastructure/neo4j/writer.py`
  - Map JSONL → Cypher `MERGE` (document, article, clause, point nodes)
  - Tạo relationships từ validated relations
  - Gắn `effective_from`, `effective_to`, `legal_status`, `doc_type` đúng schema
- [x] Chạy writer idempotently với `L59_2020`
- [x] Verify pilot có đúng 218 Article và projection hash khớp payload

### Tuần 2: Embedding Generator + Vector Index

- [x] Migrate primary embedding contract theo ADR-20: `BAAI/bge-m3` via `FlagEmbedding`, 1024-dim
- [ ] Giữ `bkai-foundation-models/vietnamese-bi-encoder`, 768-dim làm baseline/ablation; không dùng chung vector index với BGE-M3
- [x] Implement `src/pipeline/embedding/embedding_generator.py` and `src/infrastructure/neo4j/embedding_writer.py` — batch processing, dimension validation
- [x] Đồng bộ `EMBEDDING_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_DIM` với ontology và Neo4j schema
- [x] Drop/recreate vector indexes 1024-dim và re-embed pilot Article/Clause
- [x] Load vào Neo4j vector index (`article_embedding`, `clause_embedding`)
- [x] Verify pilot vector smoke trên Article/Clause

### Tuần 3: Graph Quality Evaluation ← *Thêm mới — không bỏ qua*

> [!IMPORTANT]
> Không nhảy ngay sang retrieval. Phải đo chất lượng graph trước.

- [x] Đo pilot counts, relation breakdown, ontology violations và embedding coverage từ Neo4j
- [x] Đo duplicate IDs, relation identities, orphan metrics và connected components trên pilot
- [x] Viết pilot graph-quality/evidence report
- [ ] Chạy lại các metric ở phạm vi corpus 4 văn bản và reconcile external references

### 🏁 Milestone A — Graph Build Success

| # | Tiêu chí | Verify |
|---|---|---|
| A-1 | 218 Article nodes | `MATCH (a:Article) RETURN count(a)` = 218 |
| A-2 | Relations được ghi | `MATCH ()-[r]->() RETURN type(r), count(r)` |
| A-3 | BGE-M3/1024 vector search hoạt động | Config/model/index dimension parity pass; Top-5 query trả về Article phù hợp |
| A-4 | Schema constraints 0 violation | `SHOW CONSTRAINTS` |
| A-5 | Graph Quality Report hoàn chỉnh | File report tồn tại |

---

## Phase 2 — Hybrid Retrieval 🟡 Implemented on Pilot → Milestone B Pending

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

- [x] **2.1** Intent Router: phân loại 6 lớp `factual / validity / hierarchy / comparison / definition / multi_hop`
- [x] **2.1** Vector Retriever: `queryNodes` trên `article_embedding` / `clause_embedding`
- [x] **2.2** Graph Expansion: structured `GraphNodeRef`/`GraphEdge`, giữ canonical direction
- [x] **2.3** Temporal Filter: kiểm tra node và relationship validity trước `RetrievalContext`
- [x] **2.4** BM25 full-text + deterministic two-stage RRF fusion
- [x] **2.5** Optional `bge-reranker-v2-m3` adapter, disabled unless enabled by profile
- [x] Backend retrieval API và answer-generation pipeline trên pilot
- [ ] Chạy lại official retrieval/answer evaluation theo `retrieval-runtime-v2`
- [ ] Chạy read-only disposable-Neo4j integration regression cho runtime-v2
- [ ] Hoàn tất corpus 4 văn bản trước khi công nhận Milestone B
- [x] Evidence Verifier: structured evidence/path contracts and fail-closed validation
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

## Phase 3 — LLM + Citation + Reasoning Path 🟡 Implemented on Pilot → Milestone C Pending

**Mục tiêu**: RC4 — Explainable Legal QA, không hallucinate, citation cụ thể.

- [x] Answer Generator chỉ nhận validated/projected `RetrievalContext`
- [x] Claim-level citations bị giới hạn bởi evidence registry
- [x] Structured reasoning paths giữ edge direction và temporal metadata
- [x] Grounding validator reject citation/path ngoài allowlist
- [x] Context compaction, mandatory bundles và post-projection sufficiency
- [x] Backend `/chat` integration với structured provider output
- [ ] Chạy lại real-provider smoke và reviewed QA evaluation theo runtime-v2
- [ ] Chứng minh Milestone C metrics trên corpus/evaluation được duyệt

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

## Phase 5 — Portal 🟡 Pilot Implemented, Acceptance Pending

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

- [x] Backend FastAPI: `/query`, `/chat`, document/detail/graph/article endpoints
- [x] Frontend Next.js/React pilot:
  - [x] Chat interface với citation/source details
  - [x] Graph Explorer trên document subgraph
  - [x] Document list/detail và article deep links
  - [ ] Timeline view cho corpus có quan hệ sửa đổi
  - [ ] Dedicated search page ngoài chat/query flow
- [ ] Graph Visualization Metrics (hiển thị trong Explorer):
  - Node count, Edge count, Graph density, Average path length
- [x] Integrate pilot frontend ↔ FastAPI backend ↔ Neo4j
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
