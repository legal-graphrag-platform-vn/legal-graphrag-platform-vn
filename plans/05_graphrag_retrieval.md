# GraphRAG Retrieval — Chi Tiết Kỹ Thuật

> **Phiên bản**: 0.3
> **Liên quan đến**: RC3 + RC4
> **Depends on**: [legal_ontology.md v1.12.0](./legal_ontology.md)

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

### Query-specific planned retrieval — development-only

`QUERY_PLANNING_ENABLED=false` is the default. When disabled, the runtime still
runs generic retrieval but MULTI_HOP has no trusted `GraphReasoningRequirement`;
therefore it must not be described as supported planned multi-hop, and generation
must fail-closed. When enabled in development, only the `MULTI_HOP` intent calls
the planner; other intents keep their existing retrieval path and have
`planner_provider_calls=0`.

Application orchestration tách rõ async/sync boundary:

```text
bounded worker: runtime.prepare(request)
       -> event loop: await planner.plan(query)       # MULTI_HOP only
       -> bounded worker: runtime handle bind + runtime.execute(...)
       -> exact executor: static depth-2/depth-3 query, read-only
       -> generation gate: admit only SATISFIED fingerprinted path
```

The planner only produces an `UnlinkedSemanticPlan`; it does not produce node
IDs or Cypher. The runtime handle resolves anchor/target independently and does
not use path existence for ranking. If binding or exact execution fails, generic
evidence must not replace the trusted planned path and the answer provider call
count must be 0. Planner timeout/unavailable/invalid output is returned as a
typed backend error, not a silent fallback.

As of 2026-07-30, QG-1 still has `threshold_status=failed` on three reviewed
cases of `ldn_2020`; therefore this profile is development/evaluation only, not
default-on, and carries no corpus-level or generalization claim.

| Contract | Default | Range / semantics |
|---|---:|---|
| Plan depth | required | `2..3`, exact-linear only; no default |
| Exact path budget | 20 | `1..100`; exceeding the budget returns `PATH_BUDGET_EXCEEDED` |
| Endpoint RRF k | 60 | `>=1` |
| Anchor/target candidate k | 10 / 10 | `1..100` per role |
| Anchor/target minimum score | `0.063` / `0.063` | `(0,1]`, calibrated separately from retrieval ranking |
| Anchor/target minimum margin | `0.001` / `0.001` | `[0,1]`; a missing margin returns typed ambiguous |

Query planning requires both vector and full-text seed channels. Endpoint
thresholds are not currently environment overrides; they are pinned in
`EndpointLinkerConfig` and only change after independent calibration evidence.

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
    resolved_references: tuple[ResolvedReference, ...]
    relation_goal: RelationGoal | None

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

### Server-owned canonical anchors

Conversation retrieval has a separate internal execution context; it is not a
field of the public retrieval request:

```python
class RetrievalExecutionContext:
    resolved_references: tuple[ResolvedReference, ...]
    relation_goal: RelationGoal | None

    @property
    def anchor_node_ids(self) -> tuple[str, ...]:
        return stable_unique(ref.node_id for ref in self.resolved_references)
```

The runtime hydrates these canonical IDs under the active filters before seed
retrieval, then builds one graph entry set as `stable_unique(anchors + top seed
IDs)`. A canonical anchor is therefore not dependent on lexical/vector recall.
For an explicit relation lookup, source and target citable units on the matching
path are pinned into final evidence; a missing edge is not replaced with a
similar node.

Canonical identity hydration preserves explicit document/type scope but does not
apply `query_date` or `legal_statuses`: those filters determine the answer state,
not whether an expired or not-yet-effective subject exists. A resolved `Document`
may enter retrieval context only as canonical temporal evidence; it is never a
vector/full-text seed unit. For current-validity queries, a closed interval that
places every exact subject outside the query date proves only the negative result
and may bypass graph expansion. Open-ended/positive validity still requires the
normal corpus-completeness capability and is never inferred from `effective_to =
null` alone.

---

## 4. Answer Generation Boundary

Answer generation is governed by Plans 11 and 13. It consumes only a validated
and projected `RetrievalContext`, emits structured paragraphs containing
statement-level citation linkage, and must pass grounding validation before any
response is returned or streamed.
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
