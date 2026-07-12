# Kiến Trúc Hệ Thống — Legal GraphRAG

> **Phiên bản**: 0.3
> **Trạng thái**: Draft — cần nhóm review
> **Depends on**: [legal_ontology.md v1.5.1](./legal_ontology.md)

> **This work adopts a layered architecture that separates stable legal knowledge from context-dependent legal reasoning. Stable legal knowledge (e.g., document hierarchy, legal concepts, temporal validity, and citation relationships) is represented explicitly in the Legal Knowledge Graph, whereas contextual legal reasoning (e.g., obligations, exceptions, conditions, and comparative interpretation) is performed by the LLM at runtime using retrieved evidence. This separation avoids ontology explosion while preserving explainability and maintainability.**

> **The primary objective of the Knowledge Graph is not to replace legal reasoning, but to provide trustworthy, structured, and temporally valid evidence for downstream reasoning.**

> **Research Scope.** This work focuses on constructing a trustworthy Legal Knowledge Graph and an evidence-grounded retrieval pipeline for Vietnamese enterprise law. The primary research contribution lies in knowledge representation and retrieval rather than developing new legal reasoning algorithms.

### 0. The Golden Thread (Research Narrative)

```text
                     USER QUERY
                          │
                          ▼
               Evidence Retrieval
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
  Vector Search                      Graph Traversal
        │                                   │
        └──────────────┬────────────────────┘
                       ▼
             Retrieved Legal Evidence
                       │
                Knowledge Boundary
                       │
                       ▼
         Runtime Legal Reasoning (LLM)
                       │
                       ▼
               Grounded Legal Answer
```

### Knowledge Classification

Bảng phân loại dưới đây là triết lý thiết kế cốt lõi của đồ án, định nghĩa rõ ràng ranh giới giữa những gì thuộc về Đồ thị (Graph) và những gì thuộc về Suy luận động (LLM):

| Component                  | Type       | Thuộc Graph | Thuộc LLM                   |
| -------------------------- | ---------- | ----------- | --------------------------- |
| Document hierarchy         | Structural | ✅           | ❌                           |
| Citation links             | Structural | ✅           | ❌                           |
| Cross-reference            | Structural | ✅           | ❌                           |
| Temporal validity          | Temporal   | ✅           | ❌                           |
| Amendment Relationship     | Temporal   | ✅           | ❌                           |
| Legal concepts             | Semantic   | ✅           | ❌                           |
| Obligations                | Contextual | ❌           | ✅ (from retrieved evidence) |
| Rights                     | Contextual | ❌           | ✅ (from retrieved evidence) |
| Exceptions                 | Contextual | ❌           | ✅ (context-dependent)       |
| Conditions                 | Contextual | ❌           | ✅ (context-dependent)       |
| Comparative interpretation | Contextual | ❌           | ✅                           |
| Final legal answer         | Contextual | ❌           | ✅                           |

> **The Knowledge Boundary is the central architectural decision of this work. Stable knowledge is persisted because it remains valid across queries, whereas contextual knowledge is reconstructed dynamically during inference.**

---

## Tổng Quan 3 Layer

Kiến trúc hệ thống được chia thành 3 tầng rõ rệt, kết nối với nhau thông qua cầu nối Retrieval:

```text
                 Legal Documents
                        │
                        ▼
┌───────────────────────────────────────────────┐
│       LAYER 1: LEGAL KNOWLEDGE GRAPH          │
│                                               │
│  ├── Structural Knowledge                     │
│  │      Document, Article, Clause             │
│  │      Citation, Hierarchy                   │
│  ├── Semantic Knowledge                       │
│  │      Legal Concepts, Legal Entities        │
│  │      Domain Relationships                  │
│  └── Temporal Dimension                       │
│         effective_from, effective_to          │
│         legal_status, amendment               │
└───────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│       LAYER 2: EVIDENCE RETRIEVAL             │
│                                               │
│  ├── Candidate Retrieval                      │
│  │      Vector, BM25                          │
│  ├── Evidence Expansion                       │
│  │      Graph Traversal                       │
│  ├── Evidence Filtering                       │
│  │      Temporal Filter                       │
│  ├── Evidence Ranking                         │
│  │      Reranker                              │
│  └── Evidence Packaging                       │
│         Context Builder                       │
│                                               │
│ ───────────────────────────────────────────── │
│             KNOWLEDGE BOUNDARY                │
│  (Transforms structured legal evidence        │
│   into reasoning context for the LLM)         │
│ ───────────────────────────────────────────── │
│                                               │
│  └── Retrieved Evidence                       │
└───────────────────────────────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│   LAYER 3: RUNTIME LEGAL REASONING (LLM)      │
│                                               │
│  ├── Evidence-grounded Legal Reasoning:       │
│  │   ├── Obligation Identification            │
│  │   ├── Right Identification                 │
│  │   ├── Condition Interpretation             │
│  │   ├── Exception Resolution                 │
│  │   ├── Cross-document Reasoning             │
│  │   └── Answer Synthesis                     │
└───────────────────────────────────────────────┘
                        │
                        ▼
                   Final Answer
```

---

## Chi Tiết Từng Component

### 1. Document Crawler & Ingestion (New)

**Input**: URLs từ trang VBPL chính phủ hoặc Thư viện pháp luật  
**Output**: `data/raw/<doc_id>/source.txt` + `data/raw/<doc_id>/metadata.json` (ngày ban hành, hiệu lực, tình trạng)

**Nhiệm vụ:**
- Tự động crawl raw text của văn bản từ web.
- Cào Metadata "chuẩn xác 100%" từ web (để làm hard constraints thay vì bắt LLM đoán).
- Lưu trữ raw text và metadata vào thư mục `data/raw/<doc_id>/`.

---

### 2. Hierarchy Parser

**Input**: raw text file + Metadata JSON
**Output**: Cấu trúc phân cấp dạng JSON + Metadata được đính kèm


```
Luật Doanh nghiệp 2020
  ├── Chương I — Quy định chung
  │   ├── Điều 1 — Phạm vi điều chỉnh
  │   │   └── [nội dung]
  │   ├── Điều 2 — Đối tượng áp dụng
  │   │   └── [nội dung]
  │   └── ...
  ├── Chương II — ...
  └── ...
```

**Approach:**
- Dùng raw text từ crawler để parse theo dòng và regex.
- Rule-based parsing dựa trên regex pattern của luật VN:
  - `"Điều \d+"` → Article boundary
  - `"\d+\."` → Clause boundary
  - `"[a-zđ]\)"` → Point boundary
- Handle edge cases: tables, footnotes, cross-references inline

---

### 2. LLM Information Extraction

**Input**: Chunk text (1 Article hoặc 1 Clause)  
**Output**: JSON với entities + relations

**Two-pass approach:**

```
Pass 1: Entity Extraction
    → Extract: Document refs, Concepts, Entities mentioned

Pass 2: Relation Extraction
    → Extract: Relations between identified entities
    → Classify relation type theo ontology
```

**Model selection:**
- Primary extraction model: **Gemini Flash Lite latest** (available structured output, low batch cost)
- SDK: `google-genai` (thay `google-generativeai` deprecated)
- Structured output: JSON mode / function calling


---

### 3. Graph Construction Pipeline

**Input**: LLM output JSON  
**Output**: Neo4j nodes + edges

```text
  LLM Output
      │
      ▼
Schema Validation (JSON Schema)
      │
      ▼
Ontology Validation (legal_ontology.md)
      │
      ▼
Consistency Validation (Existing Graph)
      │
      ▼
Confidence Scoring (Rule-based)
      │
      ▼
 Neo4j Writer
```

```python
# Validation flow
def process_extraction(llm_output):
    # Step 1: JSON Schema
    validated = json_schema_validator.validate(llm_output)
    
    # Step 2: Ontology Rules
    ontology_check = ontology_validator.check(validated)
    
    # Step 3: Consistency
    consistency_check = graph_consistency_checker.check(
        validated, existing_graph
    )
    
    # Step 4: Confidence (Rule-based, ADR-06)
    confidence = confidence_scorer.score(
        extraction=llm_output,
        validation_results={
            "schema_ok": bool(validated),
            "ontology_ok": bool(ontology_check)
        },
        graph_context={"existing_ids": graph_consistency_checker.get_ids()}
    )
    
    if confidence >= THRESHOLD_AUTO:
        neo4j_writer.write(validated)
    elif confidence >= THRESHOLD_REVIEW:
        human_review_queue.push(validated, confidence)
    else:
        rejection_log.log(validated, reason="low_confidence")
```

---

### 4. Hybrid Retriever

**Input**: User query + temporal context  
**Output**: Ranked list of context chunks + graph paths

**Embedding boundary (ADR-20)**: query and document embeddings must use the same
configured model, provider, dimension, and normalization policy. Current primary is
BGE-M3/1024; BKAI/768 is a separate baseline run, not a mixed fallback.

```text
Query
    │
    ▼
Candidate Retrieval
(Vector + BM25)
    │
    ▼
Graph Expansion
    │
    ▼
Temporal Filtering
    │
    ▼
Evidence Ranking
    │
    ▼
Context Builder
```

```python
class Neo4jRetriever:
    """Unified retriever: vector + graph + temporal trong 1 Cypher query (ADR-08)."""

    def retrieve(self, query: str, temporal_context: dict):
        # 1. Embed query
        query_embedding = embed(query)

        # 2. Intent-aware traversal policy (RC3)
        intent, intent_confidence = self.intent_classifier.classify(query)
        if intent_confidence < settings.intent_confidence_threshold:
            intent = "multi_hop"  # safe fallback: widest bounded traversal
        traversal_policy = TRAVERSAL_POLICIES[intent]

        # 3. Unified Cypher: vector search + temporal filter + graph expansion
        result = self.neo4j.run("""
            CALL db.index.vector.queryNodes('clause_embedding', 10, $embedding)
            YIELD node AS clause, score
            WHERE clause.effective_from <= date($query_date)
              AND (clause.effective_to IS NULL OR clause.effective_to > date($query_date))
            MATCH (clause)<-[:CONTAINS]-(article:Article)
            MATCH (article)<-[:CONTAINS]-(doc:Document)
            CALL apoc.path.expand(clause, $relations, null, 1, $max_depth)
            YIELD path
            RETURN clause, article, doc, path, score
            ORDER BY score DESC
        """, {
            "embedding": query_embedding,
            "query_date": temporal_context.get("date"),
            "relations": "|".join(traversal_policy.relations),
            "max_depth": traversal_policy.max_depth
        })

        return result
```

---

### 5. Context Builder

**Input**: Ranked context (chunks + graph paths)  
**Output**: Prompt context với reasoning chain

```python
class ContextBuilder:
    def build(self, ranked_context: list) -> dict:
        return {
            "text_chunks": [
                {
                    "id": chunk.id,
                    "content": chunk.content,
                    "source": chunk.source_document,
                    "article": chunk.article_number
                }
                for chunk in ranked_context
            ],
            "graph_paths": [
                {
                    "path": path.nodes,
                    "relations": path.edges,
                    "temporal_valid": path.is_valid_at(temporal_context)
                }
                for path in ranked_context.paths
            ]
        }
```

---

### 6. Answer Generation

**Input**: Query + Context (chunks + graph paths)  
**Output**: Structured answer

**System Prompt:**
```
Bạn là chuyên gia pháp luật doanh nghiệp Việt Nam.
Trả lời câu hỏi pháp lý DỰA TRÊN và CHỈ DỰA TRÊN các điều luật được cung cấp.

Định dạng câu trả lời:
1. Trả lời trực tiếp câu hỏi
2. Giải thích cơ sở pháp lý (điều nào, khoản nào, văn bản nào)
3. Nếu có thay đổi theo thời gian, nêu rõ

Luôn kết thúc bằng:
CITATIONS: [list of Article IDs used]
REASONING_PATH: [mô tả đường suy luận trong graph]
TEMPORAL_NOTE: [nếu câu trả lời phụ thuộc thời điểm]
```

---

### 7. Frontend Components

| Component | Mô Tả | Thư Viện |
|---|---|---|
| Chat Interface | Giao diện hỏi đáp | React |
| Citation Panel | Hiển thị điều luật được trích dẫn | React |
| Graph Visualizer | Hiển thị subgraph reasoning | D3.js / Cytoscape.js |
| Timeline Slider | Chọn thời điểm pháp luật | React |
| Reasoning Path | Hiển thị đường suy luận | React + D3.js |

---

## Data Flow — Ví Dụ End-to-End

```
User: "Điều kiện vốn để thành lập công ty TNHH theo quy định năm 2022?"

[Stage 1] Query Understanding (If enabled)
    (Optional) Intent: "factual" (điều kiện)
    Temporal: {year: 2022, from: "2022-01-01", to: "2022-12-31"}
    (Optional) Entities: ["công ty TNHH", "vốn điều lệ"]

[Stage 2] Evidence Retrieval
    Query embedding → Top-5 articles:
    - ldn_2020_art46 (Công ty TNHH 2 thành viên)
    - ldn_2020_art74 (Công ty TNHH 1 thành viên)
    - ldn_2020_art29 (Vốn điều lệ)
    ...

[Stage 3] Evidence Expansion (intent=factual, relations=[REGULATES, DEFINES, REQUIRES])
    ldn_2020_art46 → REFERS_TO → ldn_2020_art29
    ldn_2020_art29 → DEFINES → LegalConcept(VốnĐiềuLệ)
    nd_01_2021_art5 → REGULATES → LegalSubject(CôngTyTNHH)

[Stage 4] Evidence Validation (Temporal Filtering)
    Check effective dates at 2022:
    - ldn_2020_art46: effective 2021-01-01, still valid 2022 ✓
    - NĐ 47/2021: effective 2021-09-15, still valid 2022 ✓

[Stage 5] Reasoning (Rerank + Context Build)
    Relevant chunks + graph path passed to LLM

[Stage 6] Answer Generation
    Answer: "Theo Luật Doanh nghiệp 2020 (có hiệu lực từ 01/01/2021), 
    Điều 46 không quy định mức vốn điều lệ tối thiểu cho công ty TNHH..."
    
    Citations: [ldn_2020_art46, ldn_2020_art29]
    Path: ldn_2020_art46 → DEFINES → LegalConcept("Vốn điều lệ") → CONTAINS → ldn_2020_art46_cl1

[Stage 7] UI Display
    - Chat bubble với câu trả lời
    - Sidebar: Điều 46, Điều 29 (click để đọc full text)
    - Graph view: subgraph 3 nodes, 2 edges
```

```

---

## Evaluation Architecture

Hệ thống đánh giá được tách biệt hoàn toàn khỏi Application Layer (để đảm bảo tính khách quan và dễ dàng thay đổi metric).

```
[Test Dataset] (100 General QA + 50 Temporal QA)
      │
      ▼
[Evaluation Engine] (Ragas / TruLens)
      │
      ├── (Gửi Query) ──────────────► [GraphRAG Application]
      │                                       │
      ◄────── (Trả về Context + Answer) ──────┤
      │
      ▼
[Judge Model] (Configurable LLM-as-a-Judge)
      │ Evaluation Dimensions:
      ├── Retrieval Quality (Context Precision/Recall)
      ├── Reasoning Quality (Faithfulness, Hallucination check)
      └── End-to-end QA Quality (Answer Relevance/Correctness)
      │
      ▼
[Evaluation Report] (CSV / Dashboard)
```

---

## Future Architecture (Out of Scope)

Trong phạm vi đồ án, chúng ta sử dụng kiến trúc **Single-node Pipeline** để tối ưu hóa thời gian phát triển và tập trung vào giá trị nghiên cứu (Research). 

Tuy nhiên, nếu hệ thống được triển khai lên Production với quy mô hàng ngàn văn bản và hàng triệu truy vấn, kiến trúc tương lai (Future Work) sẽ được mở rộng như sau (hiện tại nằm ngoài scope):

### Future Research

```text
1. Bitemporal / Snapshot Versioning (FRBR-style)
(Tạo ra các version riêng biệt của văn bản cho mỗi lần sửa đổi thay vì dùng property trên 1 node)

2. Incremental Graph Update
(Cập nhật đồ thị thời gian thực khi có văn bản mới thay vì batch processing)

3. Legal Reasoning Agent & Multi-document Reasoning
(Phát triển LLM Agents có khả năng lập luận đa bước phức tạp qua nhiều luật khác nhau)

4. Legal Semantic Expansion
(Mở rộng hệ thống ontology: Obligation Graph, Deontic Logic, Norm Conflict Resolution)
```

### Engineering Extensions

```text
1. Distributed Caching Layer
[User] → [Redis Cache] → [GraphRAG Core]
(Cache các câu hỏi pháp lý phổ biến)

2. Distributed Pipeline
[Web Crawl / Raw Text] → [MinIO/S3] → [RabbitMQ/Kafka] → [Distributed Parsers] → [Neo4j Cluster]
(Scale hệ thống crawl và parse)
```

---

## Câu Hỏi Mở — Cần Nhóm Thảo Luận

| # | Câu Hỏi | Impact |
|---|---|---|
| 1 | Graph Visualizer dùng D3.js hay Cytoscape.js? | Frontend complexity |
| 2 | Có cần API authentication không? | Security scope |
| 3 | Deployment: local only hay có cloud? | Infra scope |
| 4 | Two-pass extraction có quá chậm không? (2 API calls/chunk) | Pipeline performance |
| 5 | Reranker Phase 2.5 dùng `bge-reranker-v2-m3` hay `Qwen3-Reranker-0.6B` ablation? | RC3 quality |
