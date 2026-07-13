# Kế Hoạch Chi Tiết: Triển Khai Phase 2 (GraphRAG Retrieval)

Đây là bản thiết kế kỹ thuật (Technical Design) cho Phase 2, bám sát kiến trúc Clean Architecture, Import Rules (AGENTS.md) và Timeline dự án (tập trung 100% vào Retrieval & Ablation, không lấn sang Phase 3 Generation).

## 0. Preconditions (Điều kiện tiên quyết)
- **Milestone A status: NOT PASSED. Gate 7 and M3-B13 remain OPEN.**
- Retrieval development is explicitly allowed against the signed-off `L59_2020`
  pilot graph. This exception unblocks implementation and local evaluation only;
  it does not close Gate 7, complete Milestone A, or constitute Milestone B
  acceptance.
- The retrieval architecture must remain corpus-agnostic. `L59_2020` may appear in
  fixtures and development commands, but never in repository queries, traversal
  policies, filters, citation builders, or runtime defaults.
- Current blockers are maintained in `06_m3_blocker_register.md`.
- Deferred retrieval findings are maintained in
  `07_phase2_retrieval_prototype_review.md` and form the active pilot fix register.
- Neo4j graph có canonical IDs.
- Article/Clause embeddings đã được tạo và khớp dimension (1024).
- Vector indexes `article_embedding` và `clause_embedding` ở trạng thái ONLINE.
- Báo cáo Graph-quality không có lỗi ontology và không có duplicate relation identity.

### Development status contract

```text
Retrieval implementation: ACTIVE on the L59_2020 pilot
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
Milestone B acceptance: NOT STARTED
Phase 2 evaluation scope: pilot-only until the four-document corpus passes
```

---

## 1. Yêu cầu Kiến trúc & Phụ thuộc
Theo execution contract tại Plan 09:
- `src/retrieval/` chỉ được import `src/shared/` và retrieval-owned domain ports.
- `src/infrastructure/` implements ports bằng structural typing và không import retrieval runtime.
- `src/application/retrieval_factory.py` là composition root duy nhất được import cả retrieval và infrastructure.
- TUYỆT ĐỐI KHÔNG import từ `src/pipeline/`, `apps/` hay `prototypes/` trong retrieval.
- Provider cho Intent sẽ được thiết kế chuẩn Interface, không hardcode Gemini (ưu tiên default là DeepSeek).
- Reranker (`bge-reranker-v2-m3`) là dependency optional, test dùng fake implementation.

---

## 2. Thiết kế Module & Cấu trúc File

### 2.1. DTOs & Models (`src/retrieval/models.py`)
```python
from enum import Enum
from pydantic import BaseModel
from typing import Optional, List, Dict, Literal
from datetime import date

class IntentType(str, Enum):
    FACTUAL = "factual"
    VALIDITY = "validity"
    HIERARCHY = "hierarchy"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    MULTI_HOP = "multi_hop"

class TemporalQuery(BaseModel):
    has_temporal: bool
    expression: Optional[str] = None
    resolved_from: Optional[date] = None
    resolved_to: Optional[date] = None
    granularity: Optional[str] = None

class RetrievedUnit(BaseModel):
    id: str
    label: Literal["Article", "Clause", "Point"]
    content_raw: str
    title: Optional[str] = None
    document_id: str
    document_number: Optional[str] = None
    article_number: Optional[str] = None
    clause_number: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    graph_score: Optional[float] = None
    rerank_score: Optional[float] = None
    final_score: Optional[float] = None
    citation_label: str

class GraphPath(BaseModel):
    nodes: List[str]
    relations: List[str]
    path_description: str
    is_temporal_valid: bool

class EvidenceItem(BaseModel):
    unit_id: str
    evidence_type: Literal["vector", "bm25", "graph", "temporal", "rerank"]
    matched_text: Optional[str] = None
    score: Optional[float] = None
    source_path_id: Optional[str] = None
    is_sufficient: bool = False

class RetrievalContext(BaseModel):
    query: str
    intent: IntentType
    temporal: TemporalQuery
    retrieved_units: List[RetrievedUnit]
    graph_paths: List[GraphPath]
    evidence: List[EvidenceItem]
    metrics: Dict[str, int]
    retrieval_mode: Literal[
        "vector_only",
        "vector_graph",
        "hybrid",
        "fulltext_only",
        "no_results"
    ]
    confidence_penalty: bool = False
```

### 2.2. Core Retrieval Modules (`src/retrieval/`)
```text
src/retrieval/
├── models.py
├── nlu/
│   ├── classifier.py
│   └── prompts.py
├── query/
│   ├── query_analyzer.py (Rule-based fast path + LLM fallback)
│   └── temporal_parser.py
├── retriever/
│   ├── vector.py
│   ├── fulltext.py (FullTextRetriever thay vì BM25)
│   ├── graph.py
│   └── hybrid.py
├── fusion/
│   └── reciprocal_rank_fusion.py
├── reranking/
│   ├── base.py
│   └── bge_reranker.py
├── evidence/
│   └── verifier.py
├── context/
│   └── context_builder.py
└── eval/
    ├── benchmark.py
    └── metrics.py
```

### 2.3. Cập nhật Infrastructure (`src/infrastructure/`)
- Cấu trúc:
  ```text
  src/infrastructure/
  ├── embedding/
  │   ├── base.py
  │   └── bge_m3.py
  ├── llm/
  │   ├── base.py
  │   ├── deepseek.py
  │   └── gemini.py
  └── neo4j/
      └── retriever_repo.py
  ```
- **Neo4j Cypher (Vector Query - Article Example)**: Lấy đủ metadata phục vụ Citation.
  ```cypher
  CALL db.index.vector.queryNodes('article_embedding', $k, $query_embedding)
  YIELD node, score
  MATCH (d:Document)-[:CONTAINS*1..3]->(node)
  RETURN
    node.id AS id,
    'Article' AS label,
    node.content_raw AS content_raw,
    node.title AS title,
    node.number AS article_number,
    d.id AS document_id,
    d.number AS document_number,
    d.source_url AS source_url,
    node.effective_from AS effective_from,
    node.effective_to AS effective_to,
    score
  ```

All channels use one filter contract: `document_ids`, `doc_types`,
`legal_statuses`, and `query_date`. Repository queries resolve document
membership through `CONTAINS`; they never use document-specific ID prefixes.

### 2.4. Traversal Direction Rules (Chính sách Duyệt Đồ thị)
Dựa theo ontology (`newer legal unit -> older affected legal unit`):
- **definition**: `Article/Clause -> DEFINES -> LegalConcept`
- **obligation/procedure**: `Article/Clause -> REGULATES/REQUIRES semantic nodes` + parent/child `CONTAINS` context
- **validity/temporal**: Filter `effective_from/to`.
  - Muốn biết cũ bị sửa bởi ai: traverse incoming `AMENDS/REPEALS/REPLACES`.
  - Muốn biết mới sửa cái gì: traverse outgoing `AMENDS/REPEALS/REPLACES`.
- **citation/reference**: `REFERS_TO` between legal units/documents
- **hierarchy**: `Document -> Chapter -> Article -> Clause -> Point`

### 2.5. Environment Configs (Reranker)
```env
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_PROVIDER=flagembedding
RERANK_TOP_N=50
FINAL_TOP_K=10
INTENT_PROVIDER=deepseek
DEEPSEEK_INTENT_MODEL=deepseek-v4-flash
```

---

## 4. Test Plan

**Unit tests:**
- Intent schema validation.
- Temporal parser rule cases.
- Vector retriever maps Neo4j rows to `RetrievedUnit`.
- Fulltext retriever maps rows to `RetrievedUnit`.
- RRF combines vector + fulltext deterministically.
- Traversal policy selects allowed relation types by intent.
- Temporal filter chooses effective_from latest valid version.
- Evidence verifier flags missing evidence.
- Reranker can be replaced by fake implementation.

**Integration tests:**
- Query `article_embedding` and `clause_embedding`.
- Fulltext index returns `Article`/`Clause`.
- Graph expansion returns `CONTAINS`/`REFERS_TO`/`AMENDS` paths.
- Phase 2 benchmark produces Recall@5, MRR, nDCG.

Pilot benchmark results from `L59_2020` are development evidence only. Corpus
evaluation and Milestone B acceptance remain blocked by M3-B13.

---

## 5. Các bước thực thi (14-Step Execution Plan)
1. Move `EmbeddingGenerator` to `infrastructure/embedding`.
2. Add retrieval DTOs + `EvidenceItem` + `retrieval_mode` fields.
3. Add LLM provider interface + fake provider for tests.
4. Add rule-based first-pass QueryAnalyzer, then DeepSeek/Gemini fallback.
5. Add vector retriever for Article/Clause.
6. Add fulltext retriever.
7. Add traversal policy registry by intent (with direction rules).
8. Add temporal filter and conflict resolver.
9. Add RRF fusion.
10. Add fake reranker + BGE reranker implementation.
11. Add evidence verifier.
12. Add context builder.
13. Add benchmark runner and metrics.
14. Produce Milestone B ablation table.
