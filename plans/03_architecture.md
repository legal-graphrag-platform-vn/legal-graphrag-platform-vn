# Kiến Trúc Hệ Thống — Legal GraphRAG

> **Phiên bản**: 0.1  
> **Trạng thái**: Draft — cần nhóm review

---

## Tổng Quan 3 Layer

```
┌──────────────────────────────────────────────────────────────┐
│                        DATA LAYER                            │
│                                                              │
│  [Crawler] Legal Document Scraper (PDF + Web Metadata)       │
│         ↓                                                    │
│  [Parser] Hierarchy Parser (PDF Text extraction)             │
│         ↓                                                    │
│  [LLM] Information Extraction                                │
│         ↓                                                    │
│  [Pipeline] Graph Construction + Embedding                   │
│         ↓                                                    │
│  ┌────────────────────────────────────────────┐              │
│  │   Neo4j 5.11+ Community                    │              │
│  │   ├── Knowledge Graph (nodes + edges)      │              │
│  │   └── Vector Index (Article/Clause embeddings) │          │
│  └────────────────────────────────────────────┘              │
│  [ADR-08] Unified storage: không có Vector Store riêng biệt  │
└──────────────────────────────────────────────────────────────┘
                            ↕ (read/write)
┌──────────────────────────────────────────────────────────────┐
│                      RETRIEVAL LAYER                         │
│                                                              │
│  User Query (Vietnamese NL)                                  │
│         ↓                                                    │
│  [NLU] Intent Classifier + Temporal Extractor               │
│         ↓                                                    │
│  [Search] Hybrid Retriever                                   │
│     ├── Vector Search → Entry points                         │
│     └── Graph Expansion → Traversal Policy                   │
│         ↓                                                    │
│  [Ranking] Reranker                                          │
│         ↓                                                    │
│  [Builder] Context Builder                                   │
│     ├── Text chunks (Article/Clause content)                 │
│     └── Graph paths (reasoning chain)                        │
└──────────────────────────────────────────────────────────────┘
                            ↕
┌──────────────────────────────────────────────────────────────┐
│                     GENERATION LAYER                         │
│                                                              │
│  [LLM] Answer Generation                                     │
│         ↓                                                    │
│  Structured Output:                                          │
│     ├── answer: string                                       │
│     ├── citations: [Article/Clause IDs]                      │
│     ├── reasoning_path: [graph edges traversed]              │
│     └── confidence: float                                    │
│         ↓                                                    │
│  [UI] Chat Interface + Graph Visualization                   │
└──────────────────────────────────────────────────────────────┘
```

---

## Chi Tiết Từng Component

### 1. Document Crawler & Ingestion (New)

**Input**: URLs từ trang VBPL chính phủ hoặc Thư viện pháp luật  
**Output**: File PDF + JSON Metadata (ngày ban hành, hiệu lực, tình trạng)

**Nhiệm vụ:**
- Tự động tải file PDF của văn bản.
- Cào Metadata "chuẩn xác 100%" từ web (để làm hard constraints thay vì bắt LLM đoán).
- Lưu trữ vào thư mục `data/raw/` cùng file `metadata.json`.

---

### 2. Hierarchy Parser

**Input**: PDF file + Metadata JSON  
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
- Dùng **PyMuPDF** để extract text + formatting (bold, font size)
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
- Primary: **Gemini 2.5 Flash** (cost-effective, supports Vietnamese) — REPORT.md B2
- SDK: `google-genai` (thay `google-generativeai` deprecated)
- Structured output: JSON mode / function calling


---

### 3. Graph Construction Pipeline

**Input**: LLM output JSON  
**Output**: Neo4j nodes + edges

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

```python
class Neo4jRetriever:
    """Unified retriever: vector + graph + temporal trong 1 Cypher query (ADR-08)."""

    def retrieve(self, query: str, temporal_context: dict):
        # 1. Embed query
        query_embedding = embed(query)

        # 2. Get intent
        intent = self.intent_classifier.classify(query)
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

[1] NLU Processing
    Intent: "factual" (điều kiện)
    Temporal: {year: 2022, from: "2022-01-01", to: "2022-12-31"}
    Entities: ["công ty TNHH", "vốn điều lệ"]

[2] Vector Search
    Query embedding → Top-5 articles:
    - LDN2020_D46 (Công ty TNHH 2 thành viên)
    - LDN2020_D74 (Công ty TNHH 1 thành viên)
    - LDN2020_D29 (Vốn điều lệ)
    ...

[3] Graph Expansion (intent=factual, relations=[REGULATES, DEFINES, REQUIRES])
    LDN2020_D46 → REFERENCES → LDN2020_D29
    LDN2020_D29 → DEFINES → Concept(VốnĐiềuLệ)
    ND01_2021_D5 → REGULATES → Entity(CôngTyTNHH)

[4] Temporal Filter
    Check effective dates at 2022:
    - LDN2020_D46: effective 2021-01-01, still valid 2022 ✓
    - NĐ 47/2021: effective 2021-09-15, still valid 2022 ✓

[5] Rerank + Context Build
    Relevant chunks + graph path

[6] LLM Generation
    Answer: "Theo Luật Doanh nghiệp 2020 (có hiệu lực từ 01/01/2021), 
    Điều 46 không quy định mức vốn điều lệ tối thiểu cho công ty TNHH..."
    
    Citations: [LDN2020_D46, LDN2020_D29]
    Path: LDN2020_D46 → DEFINES → Concept(VốnĐiềuLệ) → CONTAINS → LDN2020_D46_K1

[7] UI Display
    - Chat bubble với câu trả lời
    - Sidebar: Điều 46, Điều 29 (click để đọc full text)
    - Graph view: subgraph 3 nodes, 2 edges
```

---

## Câu Hỏi Mở — Cần Nhóm Thảo Luận

| # | Câu Hỏi | Impact |
|---|---|---|
| 1 | Graph Visualizer dùng D3.js hay Cytoscape.js? | Frontend complexity |
| 2 | Có cần API authentication không? | Security scope |
| 3 | Deployment: local only hay có cloud? | Infra scope |
| 4 | Two-pass extraction có quá chậm không? (2 API calls/chunk) | Pipeline performance |
| 5 | Reranker: cross-encoder hay BM25 hybrid? | RC3 quality |
