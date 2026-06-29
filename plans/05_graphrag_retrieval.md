# GraphRAG Retrieval — Chi Tiết Kỹ Thuật

> **Phiên bản**: 0.1  
> **Liên quan đến**: RC3 + RC4

---

## Tổng Quan Pipeline

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
│  ├── Vector Search      │  → Entry points (top-K articles)
│  └── Graph Expansion    │  → Traversal Policy
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Reranker              │
│  (BM25 hybrid /         │
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

```python
TRAVERSAL_POLICIES = {
    "factual": {
        "relations": ["REGULATES", "DEFINES", "REQUIRES", "REFERENCES"],
        "max_depth": 2,
        "follow_temporal": False
    },
    "validity": {
        "relations": ["AMENDED_BY", "REPLACED_BY", "REPEALED_BY"],
        "max_depth": 3,
        "follow_temporal": True,
        "priority": "latest"  # Ưu tiên node cuối cùng trong chain
    },
    "hierarchy": {
        "relations": ["IMPLEMENTED_BY", "GUIDED_BY", "CONTAINS"],
        "max_depth": 3,
        "direction": "both"   # Traverse cả 2 chiều
    },
    "comparison": {
        "relations": ["AMENDED_BY", "REPLACED_BY"],
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
MATCH path = (entry:Article {id: $entry_id})-[:REGULATES|DEFINES|REQUIRES|REFERENCES*1..2]->(related)
WHERE (
  related.effective_from <= $query_date
  AND (related.effective_to IS NULL OR related.effective_to > $query_date)
)
RETURN path, nodes(path) as nodes, relationships(path) as rels
ORDER BY length(path) ASC
LIMIT 20

// Template cho Temporal Time Travel (validity intent)
MATCH (start:Article {id: $entry_id})
OPTIONAL MATCH chain = (start)-[:AMENDED_BY|REPLACED_BY*1..5]->(latest)
WHERE ALL(r IN relationships(chain) WHERE
  r.effective_from <= $query_date
  AND (r.effective_to IS NULL OR r.effective_to > $query_date)
)
RETURN start, chain, latest
```

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
    id: str                    # e.g., "LDN2020_D46_K1"
    content: str               # Full text of clause
    source: str                # "Luật Doanh nghiệp 2020"
    article_number: int        # 46
    effective_from: date
    effective_to: date | None
    relevance_score: float

@dataclass
class GraphPath:
    nodes: list[str]           # ["LDN2020_D46", "LDN2020_D29"]
    relations: list[str]       # ["REFERENCES"]
    path_description: str      # Human-readable: "Điều 46 viện dẫn Điều 29"
    is_temporal_valid: bool
```

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
  "citations": ["LDN2020_D46_K1", "LDN2020_D29"],
  "reasoning_path": [
    {"from": "LDN2020_D46", "relation": "REFERENCES", "to": "LDN2020_D29",
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

## Open Questions — GraphRAG Specific

| # | Câu Hỏi | Priority |
|---|---|---|
| 1 | Depth limit 3 có đủ không, hay cần 4-5 cho multi-hop? | High |
| 2 | Khi graph paths rỗng (không tìm thấy), fallback như thế nào? | High |
| 3 | Reranker cuối cùng dùng gì: BM25 hybrid hay cross-encoder? | Medium |
| 4 | Có giới hạn số lượng context tokens không? (context window) | Medium |
| 5 | Khi có temporal conflict (2 versions cùng valid), xử lý thế nào? | High |
