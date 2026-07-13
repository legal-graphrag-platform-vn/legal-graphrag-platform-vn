# GraphRAG Retrieval — Chi Tiết Kỹ Thuật

> **Phiên bản**: 0.3
> **Liên quan đến**: RC3 + RC4
> **Depends on**: [legal_ontology.md v1.5.1](./legal_ontology.md)

---

## Tổng Quan Pipeline

> **Embedding contract (ADR-20)**: indexed document vectors and query vectors use
> `BAAI/bge-m3`, 1024 dimensions, and the same normalization policy. BKAI/768 is an
> explicit baseline requiring its own matching index/re-embedding run; vectors from
> different models or dimensions must never be mixed.

```
User Query (Vietnamese NL)
         │
         ▼
┌─────────────────────────┐
│   NLU Processing        │
│  ├── Intent Classifier  │
│  └── Temporal Extractor │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Hybrid Retriever      │
│  ├── Vector Search      │  → Article/Clause entry points
│  ├── Full-text Search   │  → Lexical Article/Clause entry points
│  ├── RRF Fusion         │  → Deterministic channel fusion
│  └── Graph Expansion    │  → Traversal Policy
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Reranker              │
│  (Phase 2.5 optional    │
│   cross-encoder)        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Context Builder       │
│  ├── Text chunks        │
│  └── Graph paths (XAI)  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   LLM Generation        │
│  → Answer               │
│  → Citations            │
│  → Reasoning Path       │
└─────────────────────────┘
```

---

## 1. NLU Processing

### Intent Classifier

> Model choice: Gemini 2.5 Flash few-shot is the primary implementation path. PhoBERT-base-v2, XLM-R, and BamiBERT are ablation/fine-tune candidates only after an intent-labeled dataset exists. See `10_tech_stack.md` → Model Candidate Matrix.

**6 Intent Classes:**

```python
INTENT_CLASSES = [
    "factual",     # Điều kiện, quy định là gì?
    "validity",    # Còn hiệu lực không?
    "hierarchy",   # Văn bản nào hướng dẫn?
    "comparison",  # Trước/sau/giữa các thời điểm
    "definition",  # Khái niệm X là gì?
    "multi_hop"    # Multi-step reasoning
]
```

**Few-shot Prompt:**

```
Phân loại intent của câu hỏi pháp lý sau:

Classes:
- factual: Hỏi về quy định, điều kiện cụ thể
- validity: Hỏi về tình trạng hiệu lực của văn bản/điều luật
- hierarchy: Hỏi về văn bản hướng dẫn/thực thi
- comparison: So sánh quy định giữa các thời điểm
- definition: Hỏi định nghĩa khái niệm pháp lý
- multi_hop: Câu hỏi cần nhiều bước suy luận

Ví dụ:
Q: "Điều kiện thành lập công ty TNHH là gì?" → factual
Q: "NĐ 78/2015 còn hiệu lực không?" → validity
Q: "Nghị định nào hướng dẫn Luật DN 2020?" → hierarchy
Q: "Quy định vốn điều lệ năm 2019 khác bây giờ như thế nào?" → comparison
Q: "Vốn điều lệ là gì?" → definition
Q: "Thủ tục mà nghị định hướng dẫn điều X quy định ra sao?" → multi_hop

Câu hỏi: "{query}"
Intent:
```

### Temporal Extractor

> Model choice: rule-based date parser is primary; Gemini 2.5 Flash structured output is fallback for ambiguous temporal wording. See `10_tech_stack.md` → Model Candidate Matrix.

```python
TEMPORAL_EXTRACTION_PROMPT = """
Trích xuất thông tin thời gian từ câu hỏi sau (nếu có):

Câu hỏi: "{query}"

Trả về JSON:
{{
  "has_temporal": boolean,
  "expression": string | null,   // "năm 2022", "trước 2020", "hiện tại"
  "resolved_from": "YYYY-MM-DD" | null,
  "resolved_to": "YYYY-MM-DD" | null,
  "granularity": "year" | "month" | "day" | "current" | null
}}

Ngày hiện tại: {today}
"""
```

---

## 2. Traversal Policy

Every retrieval channel accepts the same corpus-independent filters:
`document_ids`, `doc_types`, `legal_statuses`, and `query_date`. Runtime code
must not infer document membership from ID prefixes or contain a default
document ID.

```python
TRAVERSAL_POLICIES = {
    "factual": {
        "relations": ["REGULATES", "DEFINES", "REQUIRES", "REFERS_TO"],  # ADR-17: REFERENCES → REFERS_TO
        "max_depth": 2,
        "follow_temporal": False
    },
    "validity": {
        "relations": ["AMENDS", "REPLACES", "REPEALS"],  # ADR-17: active voice
        "max_depth": 3,
        "follow_temporal": True,
        "priority": "latest"  # Scope M3: giả định chain tuyến tính; DAG là future work
    },
    "hierarchy": {
        "relations": ["GUIDES", "CONTAINS"],  # ADR-17: IMPLEMENTED_BY+GUIDED_BY → GUIDES
        "max_depth": 3,
        "direction": "both"   # Traverse cả 2 chiều
    },
    "comparison": {
        "relations": ["AMENDS", "REPLACES"],  # ADR-17: active voice
        "max_depth": 5,
        "follow_temporal": True,
        "return_all_versions": True  # Trả về tất cả phiên bản
    },
    "definition": {
        "relations": ["DEFINES"],
        "max_depth": 1,
        "follow_temporal": False
    },
    "multi_hop": {
        "relations": ["ALL"],  # Tất cả relations
        "max_depth": 3,
        "follow_temporal": True
    }
}
```

### Cypher Query Template

```cypher
// Template cho Traversal Policy (factual intent)
MATCH path = (entry:Article {id: $entry_id})-[:REGULATES|DEFINES|REQUIRES|REFERS_TO*1..2]->(related)
WHERE (
  related.effective_from <= $query_date
  AND (related.effective_to IS NULL OR related.effective_to > $query_date)
)
RETURN path, nodes(path) as nodes, relationships(path) as rels
ORDER BY length(path) ASC
LIMIT 20

// Template cho Temporal Time Travel (validity intent)
MATCH (start:Article {id: $entry_id})
OPTIONAL MATCH chain = (newer)-[:AMENDS|REPEALS|REPLACES*1..5]->(start)
WHERE ALL(r IN relationships(chain) WHERE
  r.effective_from <= $query_date
  AND (r.effective_to IS NULL OR r.effective_to > $query_date)
)
RETURN start, chain, collect(newer) AS newer_versions
```

Temporal relation direction is active voice: newer legal units point to older affected legal units. To ask "what changed this old node?", traverse incoming `AMENDS|REPEALS|REPLACES`. To ask "what did this new node change?", traverse outgoing `AMENDS|REPEALS|REPLACES`.

---

## 3. Context Builder Output Format

```python
@dataclass
class RetrievalContext:
    # Text chunks
    chunks: list[TextChunk]
    
    # Graph paths (for XAI)
    graph_paths: list[GraphPath]
    
    # Metadata
    temporal_context: dict
    intent: str

@dataclass
class TextChunk:
    id: str                    # e.g., "ldn_2020_art46_cl1"
    content: str               # Full text of clause
    source: str                # "Luật Doanh nghiệp 2020"
    article_number: int        # 46
    effective_from: date
    effective_to: date | None
    relevance_score: float
    source_url: str | None       # optional when persisted by the corpus
    deep_link: str               # /documents/{document_id}/units/{unit_id}

@dataclass
class GraphPath:
    nodes: list[str]           # ["ldn_2020_art46", "ldn_2020_art29"]  # naming convention: legal_ontology.md §4
    relations: list[str]       # ["REFERS_TO"]  # ADR-17: REFERENCES → REFERS_TO
    path_description: str      # Human-readable: "Điều 46 viện dẫn Điều 29"
    is_temporal_valid: bool
```

Citation labels are generated from returned Document/Article/Clause metadata.
Deep links use canonical graph IDs, never filesystem `raw_doc_code` values.
When graph expansion reaches a `Point`, the path keeps the Point endpoint for
explanation while retrieval context is lifted to its parent `Clause`; Point
nodes are not added to the vector index.

---

## 4. Answer Generation Prompt

```python
SYSTEM_PROMPT = """
Bạn là chuyên gia tư vấn pháp luật doanh nghiệp Việt Nam.
Trả lời câu hỏi chỉ dựa trên các điều luật được cung cấp.
KHÔNG được suy đoán hoặc bổ sung thông tin ngoài context.

Nếu câu hỏi liên quan đến thời điểm cụ thể, chỉ sử dụng các điều luật 
có hiệu lực tại thời điểm đó.

Định dạng trả lời (JSON):
{
  "answer": "Câu trả lời đầy đủ...",
  "citations": ["ldn_2020_art46_cl1", "ldn_2020_art29"],  // naming: legal_ontology.md §4
  "reasoning_path": [
    {"from": "ldn_2020_art46", "relation": "REFERS_TO", "to": "ldn_2020_art29",  // ADR-17
     "explanation": "Điều 46 viện dẫn quy định vốn tại Điều 29"}
  ],
  "temporal_note": "Câu trả lời áp dụng cho giai đoạn 2021-2024",
  "confidence": 0.92,
  "cannot_answer": false
}
"""

USER_PROMPT = """
Câu hỏi: {query}
Thời điểm hỏi: {temporal_context}

Các điều luật liên quan:
{text_chunks}

Đường suy luận trong đồ thị tri thức:
{graph_paths}
"""
```

---

## 5. Evaluation — Level 2-3 (Retrieval + QA)

```python
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

# Chuẩn bị dataset
dataset = Dataset.from_dict({
    "question": questions,
    "answer": generated_answers,
    "contexts": retrieved_contexts,
    "ground_truth": gold_answers
})

# Chạy evaluation
result = evaluate(
    dataset=dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    llm=gemini_pro,
    embeddings=vietnamese_encoder
)
```

---

## Reranker Policy

Reranking is not part of M3. It is enabled only in Phase 2.5 after vector + graph + temporal retrieval has a measurable baseline.

Allowed candidates:
- Default candidate: `bge-reranker-v2-m3`
- Ablation candidate: `Qwen3-Reranker-0.6B`
- Secondary candidate: `gte-multilingual-reranker-base`
- Non-model keyword path: Neo4j fulltext / BM25 fusion

Do not use `ms-marco-MiniLM-L-6-v2` as the primary reranker for Vietnamese legal text.

---

## Open Questions — GraphRAG Specific

| # | Câu Hỏi | Priority |
|---|---|---|
| 1 | Depth limit 3 có đủ không, hay cần 4-5 cho multi-hop? | High |
| 2 | Khi graph paths rỗng (không tìm thấy), fallback như thế nào? | High |
| 3 | Reranker Phase 2.5 chọn `bge-reranker-v2-m3` hay ablation `Qwen3-Reranker-0.6B`? | Medium |
| 4 | Có giới hạn số lượng context tokens không? (context window) | Medium |
| 5 | Khi có temporal conflict (2 versions cùng valid), xử lý thế nào? | High |
