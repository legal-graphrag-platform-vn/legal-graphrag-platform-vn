# 5 Đóng Góp Nghiên Cứu (Research Contributions)

> **Trạng thái**: ~~v0.1~~ → **PARTIALLY SUPERSEDED**
> Mô tả RC1-RC5 (high-level) vẫn còn giá trị. Tuy nhiên các chi tiết kỹ thuật (node types, relation names, extraction strategy) đã lỗi thời.

> [!CAUTION]
> **Node types**, **relation names**, và **extraction schema** trong file này đã lỗi thời.
> Xem **[legal_ontology.md v1.1.0](./legal_ontology.md)** để biết schema chính xác.
>
> | Nội dung | Trạng thái |
> |---|---|
> | RC1-RC5 mô tả tổng quan | ✅ Vẫn đúng |
> | Node types (có `Definition`, `Procedure`) | ❌ Xem legal_ontology.md §2 |
> | Relation names (`AMENDED_BY`, `IMPLEMENTED_BY`, `GUIDED_BY`) | ❌ Xem ADR-17: `AMENDS`, `GUIDES` |
> | Extraction strategy (single-pass) | ❌ Xem ADR-03: two-pass |
> | Confidence scoring (N=3) | ❌ Xem ADR-06: rule-based |
> | RC5 baselines (BM25 + Vector) | ❌ Xem ADR-07: 1 baseline (Vector RAG) |

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
| `Concept` | Khái niệm pháp lý | Vốn điều lệ, Cổ đông sáng lập |
| `Entity` | Chủ thể pháp lý | Công ty TNHH, Doanh nghiệp tư nhân |
| `Definition` | Định nghĩa pháp lý | "Vốn điều lệ là..." |
| `Procedure` | Thủ tục hành chính | Thủ tục đăng ký doanh nghiệp |

### Relation Types (Draft — cần thảo luận)

| Relation | Ngữ Nghĩa | Head → Tail |
|---|---|---|
| `CONTAINS` | Cấu trúc phân cấp | Document → Article → Clause → Point |
| `AMENDED_BY` | Bị sửa đổi bởi | Article → Article |
| `REPLACED_BY` | Bị thay thế hoàn toàn | Document → Document |
| `IMPLEMENTED_BY` | Được hướng dẫn bởi NĐ | Document(Law) → Document(Decree) |
| `GUIDED_BY` | Được hướng dẫn bởi TT | Document(Decree) → Document(Circular) |
| `REFERENCES` | Viện dẫn | Article → Article |
| `DEFINES` | Định nghĩa khái niệm | Article → Concept |
| `REGULATES` | Điều chỉnh chủ thể | Article → Entity |
| `REQUIRES` | Yêu cầu điều kiện | Entity → Concept (điều kiện) |
| `REPEALED_BY` | Bị hủy bỏ | Document → Document |

### Constraints (Ontology Rules)

```python
# Chỉ Document có thể CONTAINS Article
CONTAINS: Document | Article | Clause → Article | Clause | Point

# AMENDED_BY chỉ giữa cùng loại
AMENDED_BY: Article → Article, Clause → Clause

# IMPLEMENTED_BY chỉ từ Law → Decree
IMPLEMENTED_BY: Document(type=Law) → Document(type=Decree)

# DEFINES chỉ từ Article/Clause → Concept
DEFINES: Article | Clause → Concept | Definition
```

### Câu Hỏi Mở Cho Nhóm
- [ ] Có cần node `Procedure` không? Hay để trong future work?
- [ ] `Definition` có phải node riêng hay là attribute của `Concept`?
- [ ] Xử lý Phụ lục (Annex) như thế nào?

---

## RC2 — Graph Construction Pipeline với LLM + Validation

### Mô tả
Pipeline tự động chuyển đổi văn bản PDF → Knowledge Graph:

```
PDF
 ↓
[1] Hierarchy Parser       — PyMuPDF + rule-based chunking
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

### Phương Pháp Confidence Scoring (Cần Chốt)

| Phương Pháp | Mô Tả | Pros | Cons |
|---|---|---|---|
| **Self-consistency (N=3)** | Chạy LLM 3 lần, đếm majority vote | Không cần thêm model | Tốn API cost x3 |
| **Log-probability** | Dùng token log-probs | Nhanh, 1 lần gọi | Không phải LLM nào cũng hỗ trợ |
| **Critic LLM** | LLM thứ 2 đánh giá output LLM 1 | Chất lượng cao | Chi phí cao nhất |

> **Đề xuất**: Self-consistency N=3 — cân bằng giữa chất lượng và chi phí.

### LLM Extraction Prompt (Draft)

```
Cho đoạn văn bản pháp luật sau:
[TEXT]

Hãy trích xuất:
1. Tất cả entities (Document, Article, Clause, Concept, Entity)
2. Tất cả relations giữa các entities

Trả về JSON theo schema:
{
  "entities": [{"id": str, "type": str, "label": str, "properties": {}}],
  "relations": [{"head": str, "relation": str, "tail": str, "confidence": float}]
}

Chỉ sử dụng các relation types: AMENDED_BY, REPLACED_BY, IMPLEMENTED_BY, 
GUIDED_BY, REFERENCES, DEFINES, REGULATES, REQUIRES, REPEALED_BY, CONTAINS
```

### Câu Hỏi Mở Cho Nhóm
- [ ] Chọn phương pháp Confidence Scoring nào?
- [ ] Threshold để đưa vào Human Review là bao nhiêu? (0.5? 0.7?)
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
| `validity` | "Điều 17 còn hiệu lực không?" | `AMENDED_BY`, `REPLACED_BY`, `REPEALED_BY` | 3 |
| `hierarchy` | "Văn bản nào hướng dẫn Điều 17?" | `IMPLEMENTED_BY`, `GUIDED_BY` | 3 |
| `comparison` | "Quy định năm 2020 vs 2024?" | `AMENDED_BY` + temporal filter | 2 |
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
  id: "LDN2020_D17",
  title: "Điều 17. Điều kiện thành lập",
  effective_from: "2021-01-01",
  effective_to: null,  // null = còn hiệu lực
  status: "active"     // active | amended | repealed
})
```

**Timestamps trên Edge (quan trọng hơn):**
```cypher
(:Article {id: "LDN2014_D17"})-[:AMENDED_BY {
  effective_from: "2021-01-01",
  effective_to: null,
  amendment_type: "partial"  // partial | full
}]->(:Article {id: "LDN2020_D17"})
```

### Time Travel Query

```cypher
// Câu hỏi: "Quy định Điều 17 năm 2022"
MATCH (a:Article {id: "LDN2020_D17"})
WHERE a.effective_from <= "2022-06-01"
  AND (a.effective_to IS NULL OR a.effective_to > "2022-06-01")

// Kiểm tra amendments tại thời điểm đó
OPTIONAL MATCH (a)-[r:AMENDED_BY]->(b:Article)
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

### Câu Hỏi Mở Cho Nhóm
- [ ] Cần xử lý những loại temporal expression nào?
- [ ] `status` trên node: enum `[active, amended, repealed, suspended]`?

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
| **Baseline 1** | Keyword Search (BM25) |
| **Baseline 2** | Naive RAG (vector search only) |
| **Proposed** | Temporal GraphRAG (hệ thống đề tài) |

### Ground Truth Dataset

| Phần | Số Lượng | Người Làm |
|---|---|---|
| Gold Graph annotation | 3-5 văn bản (~50 entities, ~30 relations) | Cả nhóm |
| General QA pairs | 100 câu hỏi + đáp án | Cả nhóm |
| Temporal QA pairs | 50 câu hỏi + đáp án + năm cụ thể | Cả nhóm |
| XAI evaluation | 20-30 câu + expected reasoning path | Cả nhóm |

### Câu Hỏi Mở Cho Nhóm
- [ ] Ai chịu trách nhiệm xây dựng ground truth dataset?
- [ ] Có mời legal expert review không?
- [ ] LLM-as-judge dùng model nào? (GPT-4o? Gemini?)
