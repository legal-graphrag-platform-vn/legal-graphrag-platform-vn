# 5 Đóng Góp Nghiên Cứu (Research Contributions)

> **Trạng thái**: Research framing document.
> File này chỉ mô tả RC1-RC5 ở mức high-level. Mọi schema, validator rule, model choice, dataset size, và implementation contract phải lấy từ các file source-of-truth tương ứng.

> [!CAUTION]
> **Không dùng file này làm implementation contract.**
> Xem **[legal_ontology.md v1.6.0](./legal_ontology.md)** cho ontology, **[04_graph_construction_pipeline.md](./04_graph_construction_pipeline.md)** cho pipeline, và **[08_dataset_and_scope.md](./08_dataset_and_scope.md)** cho dataset scope.
>
> | Nội dung | Trạng thái |
> |---|---|
> | RC1-RC5 mô tả tổng quan | ✅ Vẫn đúng |
> | Ontology labels and relation rules | `legal_ontology.md` |
> | Extraction strategy | `04_graph_construction_pipeline.md` — two-pass extraction |
> | Confidence scoring | ADR-06 — rule-based |
> | Dataset size | `08_dataset_and_scope.md` — current committed vs target full scope |

---

> Đây là nền tảng học thuật của đề tài. Mỗi RC cần có **implementation**, **experiment**, và **kết quả đo được**.

---


## RC1 — Ontology Chuyên Biệt cho Pháp Luật Doanh Nghiệp Việt Nam

### Mô tả
Thiết kế ontology 3 tầng làm nền tảng biểu diễn tri thức pháp lý:

```
Tầng 1: Conceptual Model
         (Thế giới pháp luật VN là gì? Các khái niệm, thực thể, quan hệ)
         ↓
Tầng 2: Formal Ontology
         (Node types, Relation types, Constraints, Axioms)
         ↓
Tầng 3: Neo4j Schema
         (Implementation cụ thể trong graph database)
```

### Tại Sao Đây Là Contribution?
- Việt Nam chưa có chuẩn ontology pháp luật chính thức.
- Đề tài đề xuất ontology domain-specific cho luật **doanh nghiệp** — có thể mở rộng sang lĩnh vực khác.
- So sánh được với chuẩn quốc tế (Akoma Ntoso, LKIF).

### Node Types (Draft — cần thảo luận)

| Node Label | Ý Nghĩa | Ví Dụ |
|---|---|---|
| `Document` | Văn bản pháp luật | Luật Doanh nghiệp 2020, NĐ 01/2021 |
| `Article` | Điều | Điều 17 — Điều kiện thành lập |
| `Clause` | Khoản | Khoản 1 Điều 17 |
| `Point` | Điểm | Điểm a Khoản 1 Điều 17 |
| `LegalConcept` | Khái niệm pháp lý | Vốn điều lệ, Cổ đông sáng lập |
| `LegalSubject` | Chủ thể pháp lý | Công ty TNHH, Doanh nghiệp tư nhân |
| `LegalAction` | Hành vi pháp lý | Thành lập, góp vốn, giải thể |

### Relation Types (Current — xem `legal_ontology.md`)

| Relation | Ngữ Nghĩa | Head → Tail |
|---|---|---|
| `CONTAINS` | Cấu trúc phân cấp | Document → Chapter → Article → Clause → Point |
| `AMENDS` | Sửa đổi | Document/Article/Clause → Document/Article/Clause |
| `REPLACES` | Thay thế hoàn toàn | Document → Document |
| `GUIDES` | Hướng dẫn thi hành | Document → Document |
| `REFERS_TO` | Viện dẫn | Article/Clause/Point → Article/Clause/Point/Document |
| `DEFINES` | Định nghĩa khái niệm | Article/Clause → LegalConcept |
| `REGULATES` | Điều chỉnh chủ thể/hành vi | Article/Clause → LegalSubject/LegalAction |
| `REQUIRES` | Yêu cầu điều kiện | LegalSubject → LegalConcept/Obligation |
| `REPEALS` | Bãi bỏ | Document → Document/Article/Clause |

### Constraints (Ontology Rules)

```python
# Structural chain, with direct Document→Article fallback when no Chapter exists
CONTAINS: Document | Chapter | Article | Clause → Chapter | Article | Clause | Point

# AMENDS bắt buộc có effective_from
AMENDS: Document | Article | Clause → Document | Article | Clause

# GUIDES chỉ hợp lệ theo GUIDES_WHITELIST
GUIDES: Document(type=Law) → Document(type=Decree)

# DEFINES chỉ từ Article/Clause → LegalConcept
DEFINES: Article | Clause → LegalConcept
```

### Scope Notes
- `Definition` is not a standalone node in Phase 1; it is represented through `LegalConcept` and `DEFINES`.
- `Procedure` is future work/runtime reasoning, not a persisted Phase 1 node.
- Annex handling remains future work unless the selected corpus requires it.

---

## RC2 — Graph Construction Pipeline với LLM + Validation

### Mô tả
Pipeline tự động chuyển đổi web crawl / raw text → Knowledge Graph:

```
Web Crawl
 ↓
[1] Hierarchy Parser       — raw text + rule-based chunking
 ↓
[2] LLM Extraction         — Structured output (JSON) từ LLM
 ↓
[3] JSON Schema Validation  — Kiểm tra format
 ↓
[4] Ontology Validation     — Kiểm tra đúng ontology
 ↓
[5] Confidence Scoring      — Đánh giá độ tin cậy
 ↓
[6] Human Review Queue      — Nếu confidence < threshold
 ↓
Neo4j
```

### Contribution
- Đề xuất pipeline kết hợp LLM extraction + rule-based validation.
- Confidence scoring để phân loại auto-accept / human-review.
- Có thể đo được: Precision/Recall so với ground truth.

### Phương Pháp Confidence Scoring (ADR-06)

| Phương Pháp | Mô Tả | Pros | Cons |
|---|---|---|---|
| **Rule-based multi-criteria** | Chấm điểm theo schema, ontology, evidence, entity resolution, direction | Explainable, 1 lần gọi LLM, dễ calibrate threshold | Cần thiết kế rule rõ ràng |
| Self-consistency | Chạy LLM nhiều lần, đếm majority vote | Không cần thêm model | Tốn API cost xN, khó giải thích chi tiết |
| **Log-probability** | Dùng token log-probs | Nhanh, 1 lần gọi | Không phải LLM nào cũng hỗ trợ |
| **Critic LLM** | LLM thứ 2 đánh giá output LLM 1 | Chất lượng cao | Chi phí cao nhất |

> **Đề xuất hiện tại**: Rule-based confidence theo ADR-06. Extraction chạy two-pass entity + relation extraction; confidence scorer không được override lỗi schema hoặc ontology.

### LLM Extraction Prompt (Draft)

```
Cho đoạn văn bản pháp luật sau:
[TEXT]

Hãy trích xuất:
1. Tất cả entities (Document, Article, Clause, Concept, Entity, Action)
2. Tất cả relations giữa các entities

Trả về JSON theo schema:
{
  "entities": [{"id": str, "type": str, "label": str, "properties": {}}],
  "relations": [{"head": str, "relation": str, "tail": str, "confidence": float}]
}

Chỉ sử dụng các relation types: AMENDS, REPLACES, GUIDES,
REFERS_TO, DEFINES, REGULATES, REQUIRES, REPEALS, CONTAINS
```

### Câu Hỏi Mở Cho Nhóm
- [ ] Threshold để đưa vào Human Review là bao nhiêu? (calibrate bằng PR curve)
- [ ] Human Review tool cần UI riêng không, hay dùng Neo4j Browser?

---

## RC3 — Hybrid GraphRAG với Intent-based Traversal Policy

### Mô tả
Hệ thống retrieval thay vì chỉ vector search, sẽ:
1. Phân loại intent của câu hỏi
2. Chọn traversal strategy phù hợp
3. Mở rộng context theo graph relations

```
User Query
    ↓
[1] Intent Classifier + Temporal Extractor
    ↓
[2] Hybrid Retriever
    ├── Vector Search (tìm entry point trong graph)
    └── Graph Expansion (theo Traversal Policy)
    ↓
[3] Reranker
    ↓
[4] Context Builder (chunks + graph paths)
    ↓
[5] LLM Generation
    ↓
Answer + Citation + Reasoning Path
```

### Traversal Policy (Cần Chốt)

| Intent Type | Ví Dụ Câu Hỏi | Relations Traversed | Max Depth |
|---|---|---|---|
| `factual` | "Điều kiện thành lập công ty TNHH là gì?" | `REGULATES`, `DEFINES`, `REQUIRES` | 2 |
| `validity` | "Điều 17 còn hiệu lực không?" | `AMENDS`, `REPLACES`, `REPEALS` | 3 |
| `hierarchy` | "Văn bản nào hướng dẫn Điều 17?" | `GUIDES` | 3 |
| `comparison` | "Quy định năm 2020 vs 2024?" | `AMENDS` + temporal filter | 2 |
| `definition` | "Vốn điều lệ là gì?" | `DEFINES` | 1 |
| `multi_hop` | "Nghị định hướng dẫn điều này quy định gì?" | All relevant + follow references | 3 |

### Intent Classification (Cần Chốt)

| Phương Pháp | Mô Tả | Gợi Ý |
|---|---|---|
| Few-shot LLM | Dùng 5-10 ví dụ trong prompt | ✅ Bắt đầu với cách này |
| Fine-tuned PhoBERT | Train classifier trên ~200 câu | Nếu có thời gian, thêm experiment |
| Rule-based | Keyword matching | Baseline để compare |

### Câu Hỏi Mở Cho Nhóm
- [ ] Chọn phương pháp Intent Classification nào?
- [ ] Reranker: cross-encoder hay BM25 hybrid?
- [ ] Depth limit per intent có đúng không? (3 hop có quá nhiều không?)

---

## RC4 — Temporal Knowledge Graph

### Mô tả
Graph lưu thông tin thời gian trên **cả node lẫn edge**:

**Timestamps trên Node:**
```cypher
(:Article {
  id: "ldn_2020_art17",
  title: "Điều 17. Điều kiện thành lập",
  effective_from: "2021-01-01",
  effective_to: null,  // null = còn hiệu lực
  legal_status: "ACTIVE"
})
```

**Timestamps trên Edge (quan trọng hơn):**
```cypher
(:Article {id: "ldn_2025_art17"})-[:AMENDS {
  effective_from: "2021-01-01",
  effective_to: null,
  amendment_type: "partial"  // partial | full
}]->(:Article {id: "ldn_2020_art17"})
```

### Time Travel Query

```cypher
// Câu hỏi: "Quy định Điều 17 năm 2022"
MATCH (a:Article {id: "ldn_2020_art17"})
WHERE a.effective_from <= "2022-06-01"
  AND (a.effective_to IS NULL OR a.effective_to > "2022-06-01")

// Kiểm tra amendments tại thời điểm đó
OPTIONAL MATCH (b:Article)-[r:AMENDS]->(a)
WHERE r.effective_from <= "2022-06-01"
RETURN a, r, b
```

### Temporal Expression Extraction

```
User: "Quy định về vốn điều lệ năm 2022"
         ↓
LLM (structured output):
{
  "temporal_expression": "năm 2022",
  "resolved": {
    "from": "2022-01-01",
    "to": "2022-12-31",
    "granularity": "year"
  }
}
```

**Các loại temporal expression cần xử lý:**
- `"năm 2022"` → `[2022-01-01, 2022-12-31]`
- `"đầu năm 2022"` → `[2022-01-01, 2022-06-30]`
- `"hiện tại"`, `"hiện nay"` → `[today, null]`
- `"trước năm 2023"` → `[null, 2022-12-31]`
- `"sau khi Nghị định XX có hiệu lực"` → lookup effective date của NĐ XX

### Scope Notes
- Temporal expression extraction starts with rule-based parsing and LLM fallback for ambiguous cases.
- Node validity uses `legal_status` enums from `legal_ontology.md`.

---

## RC5 — Evaluation Framework 4 Tầng

### Mô tả
Đánh giá hệ thống ở 4 tầng tương ứng với 4 thành phần:

```
Level 1: Graph Construction Quality
Level 2: Retrieval Quality
Level 3: QA Quality
Level 4: Temporal & XAI Quality
```

### Level 1 — Graph Construction

| Metric | Công Thức | Công Cụ |
|---|---|---|
| Entity Precision | TP_entity / (TP+FP)_entity | So sánh với gold graph |
| Entity Recall | TP_entity / (TP+FN)_entity | So sánh với gold graph |
| Relation Precision | TP_rel / (TP+FP)_rel | So sánh với gold graph |
| Relation Recall | TP_rel / (TP+FN)_rel | So sánh với gold graph |

> Ground truth: Annotate thủ công 3-5 văn bản.

### Level 2 — Retrieval

| Metric | Mô Tả | Công Cụ |
|---|---|---|
| Context Precision | Chunks retrieved có relevant không? | RAGAS |
| Context Recall | Tất cả chunks cần thiết được retrieve không? | RAGAS |
| Hit Rate | Entry point có đúng article không? | Custom |

### Level 3 — QA

| Metric | Mô Tả | Công Cụ |
|---|---|---|
| Faithfulness | Câu trả lời có dựa trên context không? | RAGAS |
| Answer Relevance | Câu trả lời có đúng câu hỏi không? | RAGAS |
| Answer Correctness | Câu trả lời có đúng không? | Manual / LLM-as-judge |

### Level 4 — Temporal & XAI

| Metric | Mô Tả | Cách Đo |
|---|---|---|
| Temporal Accuracy | % câu hỏi temporal được trả lời đúng thời điểm | 50 test cases |
| Citation Completeness | Số điều luật được cite đầy đủ / Số cần cite | Manual review |
| Graph Path Correctness | Reasoning path có đúng với graph không? | Validate từng step |
| Reasoning Consistency | Path có nhất quán từ câu hỏi → đáp án không? | LLM-as-judge |

### Baseline So Sánh

| System | Mô Tả |
|---|---|
| **Main Baseline** | Naive RAG (vector search only) |
| **Optional Ablation** | Keyword Search / BM25 full-text only |
| **Proposed** | Temporal GraphRAG (hệ thống đề tài) |

### Ground Truth Dataset

| Phần | Số Lượng | Người Làm |
|---|---|---|
| Gold Graph annotation | 3-5 văn bản (~50 entities, ~30 relations) | Cả nhóm |
| General QA pairs | Current committed: 50; target full: 100 | Cả nhóm |
| Temporal QA pairs | Current committed: 25; target full: 50 | Cả nhóm |
| XAI evaluation | 20-30 câu + expected reasoning path | Cả nhóm |

### Câu Hỏi Mở Cho Nhóm
- [ ] Ai chịu trách nhiệm xây dựng ground truth dataset?
- [ ] Có mời legal expert review không?
- [ ] LLM-as-judge dùng model nào? (GPT-4o? Gemini?)

---

## Phụ lục: RC to Codebase Mapping

Để dễ dàng tra cứu và đối chiếu giữa bài viết luận văn và source code thực tế, các Research Contributions (RC) được map trực tiếp vào các thư mục trong repository như sau:

| Mã RC | Tên đóng góp | Thư mục Source Code Tương Ứng |
|---|---|---|
| **RC1** | Legal Ontology Design | `plans/legal_ontology.md` (Design doc là thành phẩm chính) |
| **RC2** | Graph Construction Pipeline | `src/pipeline/` (chứa crawler, parser, extraction, validator, neo4j_writer) |
| **RC3** | Intent-based Traversal GraphRAG | `src/retrieval/` (chứa classifier, graph_traversal, vector_search) |
| **RC4** | Temporal GraphRAG | `src/retrieval/` và `src/infrastructure/neo4j/` |
| **RC5** | Legal Evaluation Framework | `src/evaluation/` (chứa ground_truth builder, RAGAS integration, metrics) |

> **Lưu ý cho hội đồng**: Việc cấu trúc thư mục code map 1-1 với cấu trúc lý thuyết giúp việc đánh giá chéo (cross-evaluation) minh bạch và dễ dàng thẩm định.
