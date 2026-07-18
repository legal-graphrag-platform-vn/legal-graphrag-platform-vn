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

### Intent Router

The current runtime uses a deterministic six-intent router with stable decision
reason codes. It does not call an LLM. A learned classifier remains a future
ablation/fine-tune candidate after a reviewed intent dataset exists.

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

Router output includes `intent`, `decision_reason_code`, `decision_reason`,
`force_intent_used`, `temporal_source`, selected channels, and required
capability. `force_intent` overrides classification only; it never bypasses
request, temporal, filter, or capability validation.

### Temporal Extractor

The primary and current implementation is a deterministic date/expression
parser with an injected `Clock`. Explicit temporal wording that cannot be
resolved raises `TemporalRoutingError`; the runtime does not silently downgrade
the request or invoke an untracked model fallback.

Temporal precedence is:

```text
explicit request query_date
> parsed date expression in query
> injected current date only for explicit current-validity wording
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
        "relations": [
            "ISSUED_BY", "CONTAINS", "GUIDES", "REFERS_TO",
            "AMENDS", "REPEALS", "REPLACES", "DEFINES",
            "REGULATES", "REQUIRES"
        ],
        "max_depth": 3,
        "direction": "both"
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
class RetrievalContext:
    contract_version: Literal["retrieval-runtime-v2"]
    query: str
    intent: IntentType
    strategy: RetrievalStrategyType
    temporal: TemporalQuery
    filters_applied: RetrievalFilters
    retrieved_units: list[RetrievedUnit]
    graph_paths: list[GraphPath]
    evidence: list[EvidenceItem]
    reasoning_requirement: GraphReasoningRequirement | None
    executed_channels: list[RetrievalChannel]
    retrieval_mode: str
    metrics: dict[str, Any]

class GraphNodeRef:
    node_id: str
    labels: tuple[str, ...]
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None
    citable_unit_id: str | None

class GraphEdge:
    relation_id: str
    relation_type: str
    source_id: str             # canonical Neo4j direction
    target_id: str
    effective_from: date | None
    effective_to: date | None

class GraphPath:
    nodes: tuple[GraphNodeRef, ...]  # traversal order
    edges: tuple[GraphEdge, ...]     # canonical relationship direction
    path_description: str
```

Only node-and-relationship temporal-valid paths enter `RetrievalContext`.
Incoming traversal never reverses canonical edge direction. Multi-hop answer
generation remains fail-closed until retrieval supplies a trusted explicit graph
requirement and every citable intermediate legal unit is present. Comparison
requires a shared non-null `version_family_id` or a verified
`AMENDS`/`REPLACES` path.

Citation labels are generated from returned Document/Article/Clause metadata.
Deep links use canonical graph IDs, never filesystem `raw_doc_code` values.
When graph expansion reaches a `Point`, the path keeps the Point endpoint for
explanation while retrieval context is lifted to its parent `Clause`; Point
nodes are not added to the vector index.

---

## 4. Answer Generation Boundary

Answer generation is governed by Plans 11 and 13. It consumes only a validated
and projected `RetrievalContext`, emits structured claims with citation IDs, and
must pass grounding validation before any response is returned or streamed.
The provider cannot cite omitted evidence or invent graph paths. Multi-hop
generation fails closed unless context carries a trusted explicit
`GraphReasoningRequirement`.

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
