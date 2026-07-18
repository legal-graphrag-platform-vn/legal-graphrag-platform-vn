# Tech Stack

> **Nguyên tắc lựa chọn**: Ưu tiên open-source, tiết kiệm cost, có tài liệu tốt cho tiếng Việt

> [!WARNING]
> File này có một số mục đã được cập nhật. **LlamaIndex** không được dùng trong implementation hiện tại (không có import nào trong `src/`). Framework là custom pipeline.
> LLM SDK đã chuyển sang `google-genai` (SDK mới) thay vì `google-generativeai` (deprecated).

---

## Core Stack

| Layer | Công Nghệ | Lý Do Chọn | Thay Thế |
|---|---|---|---|
| **Graph DB + Vector** | Neo4j 5.11+ Community | Graph + Vector Index native, 1 query cho vector + graph + temporal | ArangoDB |
| **LLM (main)** | Configured Gemini provider; current answer default `gemini-3.1-flash-lite` | Structured output, Vietnamese support, configurable checkpoint | Local/provider alternatives require a separate adapter |
| **LLM (judge)** | Gemini **2.5** Pro | Evaluation quality cần model mạnh hơn | GPT-4o |
| **LLM SDK** | `google-genai` | SDK mới (thay `google-generativeai` đã deprecated) | — |
| **Embedding** | `BAAI/bge-m3` via `FlagEmbedding` | Smoke test tốt hơn BKAI trên query pháp luật doanh nghiệp; multilingual dense vector 1024-dim | BKAI Vietnamese bi-encoder 768-dim baseline |
| **Hierarchy Parser** | Raw text parser | Khớp với `source.txt` từ crawler; retry/fallback selector nếu crawl lỗi | — |
| **Framework** | **Custom Pipeline** (không dùng LlamaIndex) | LlamaIndex không có direct support cho cấu trúc hà văn bản pháp luật VN | LlamaIndex |
| **Backend** | FastAPI | Async, OpenAPI docs tự động | Flask |
| **Frontend** | Next.js 16 + React 19 | Pilot chat, citation, graph explorer, typed backend contracts | — |
| **Graph UI** | Cytoscape.js / pyvis | Chuyên cho graph | D3.js |
| **Evaluation** | RAGAS | Industry standard cho RAG evaluation | DeepEval |

---

## Chi Tiết Từng Component

### Neo4j

```yaml
# Generic development example. The guarded disposable M3 runtime uses
# infra/docker-compose.m3.yml with HTTP 7475 and Bolt 7688.
neo4j:
  image: neo4j:5.x-community
  ports:
    - "7474:7474"  # Browser UI
    - "7687:7687"  # Bolt protocol
  environment:
    NEO4J_AUTH: neo4j/password
    NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
  volumes:
    - ./data/neo4j:/data
```

**Plugins cần:**
- APOC (utility functions)
- Graph Data Science (optional: PageRank để rank nodes)

---

### Neo4j Vector Index (thay thế Qdrant)

> [!IMPORTANT]
> **ADR-08**: Dùng Neo4j native vector index (5.11+), không dùng Qdrant riêng biệt.
> Lý do: 1 Cypher query dù nhất thực hiện vector search + graph traversal + temporal filter.
> Với quy mô ~5000 clauses, unified storage là lựa chọn phù hợp hơn split architecture.

```cypher
-- Khởi tạo vector index khi init DB:
CREATE VECTOR INDEX clause_embedding
FOR (c:Clause) ON c.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX article_embedding
FOR (a:Article) ON a.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};
```

```python
# Unified query: vector + graph + temporal trong 1 Cypher
CYPHER = """
CALL db.index.vector.queryNodes('clause_embedding', 10, $embedding)
YIELD node AS clause, score
WHERE clause.effective_from <= date($query_date)
  AND (clause.effective_to IS NULL OR clause.effective_to > date($query_date))
MATCH (clause)<-[:CONTAINS]-(article:Article)
MATCH (article)<-[:CONTAINS]-(doc:Document)
RETURN clause, article, doc, score
ORDER BY score DESC
"""
```

**Scalability note** (cho báo cáo):
> Với quy mô lớn hơn, interface-based RetrieverInterface cho phép thay thế
> bằng Qdrant hoặc Milvus mà không ảnh hưởng các tầng còn lại.

---

### Embedding Model

```python
# Primary dense embedding contract (ADR-20)
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
EMBEDDING_DIM = 1024

# Explicit baseline only:
# bkai-foundation-models/vietnamese-bi-encoder via sentence-transformers
# EMBEDDING_DIM = 768
```

Configuration contract:

```text
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_PROVIDER=flag_embedding
EMBEDDING_DIM=1024
```

Model output, application config, and Neo4j vector index dimension must match.
Changing dimension requires an ADR, ontology version bump, vector-index recreation,
and re-embedding all Article/Clause nodes.

---

## Model Candidate Matrix

This table is the canonical model-selection map for implementation and thesis defense. `Primary` means the default for the current research prototype. `Candidate / Fallback` means allowed alternatives for ablation, quota failure, local fallback, or future training. Before implementation, verify model availability, license, context length, output schema support, and embedding dimension.

| Component | Primary | Candidate / Fallback | Future fine-tune? | Why this fits |
|---|---|---|---|---|
| Information Extraction | Gemini Flash Lite latest structured output | Gemini Pro for hard cases; GPT-4o-mini; Qwen3-8B local | Optional LoRA local LLM | Available structured output, Vietnamese legal text handling, and low batch cost |
| Answer Generation | Configured Gemini adapter; current default `gemini-3.1-flash-lite` | Stronger Gemini checkpoint or local model through a separate adapter | Not priority | Generation is grounded by retrieved graph evidence; fine-tuning is less important than citation discipline |
| Judge / Evaluation | Gemini 2.5 Pro | GPT-4o; Gemini Flash smoke test | No | Judge should be stronger and more stable than the default generation model |
| Embedding | `BAAI/bge-m3` via `FlagEmbedding`, 1024-dim | BKAI Vietnamese bi-encoder 768-dim baseline; `Qwen3-Embedding-0.6B` future candidate | Yes, after query-positive pairs exist | BGE-M3 won the project smoke test on Vietnamese enterprise-law queries; BKAI is retained for ablation |
| Intent Router | Deterministic six-intent rules + temporal parser | PhoBERT/XLM-R future classifier after labeled data exists | Yes, after reviewed intent labels exist | Current routing must be reproducible and must not require an LLM call |
| Temporal Extractor | Deterministic date/expression parser | Future reviewed parser/model for unresolved expressions | Not priority | Explicit temporal expressions fail closed when they cannot be resolved; runtime does not silently downgrade |
| Reranker | Optional `BAAI/bge-reranker-v2-m3` via `FlagReranker`, disabled by default | `Qwen3-Reranker-0.6B`; `gte-multilingual-reranker-base` | Yes, after retrieval dataset exists | Phase 2 adapter is implemented; M3 graph construction does not depend on it |
| BM25 / Full-text | Neo4j fulltext index | External BM25 only if Neo4j fulltext is insufficient | No | Not a neural model; used as keyword retrieval/fusion or optional ablation |

### Training Priority

1. **Extraction training**: optional local LoRA only after enough corrected extraction triples exist.
2. **Intent training**: PhoBERT/XLM-R fine-tune after a labeled intent dataset exists.
3. **Embedding/reranker training**: only after query-positive/negative retrieval pairs exist.
4. **Answer generation training**: not prioritized; improve prompts, retrieval, citation checks, and evidence verifier first.

---

### Current Application Structure

```
apps/
├── backend/              # FastAPI routes, DTO mapping, services, lifecycle
└── frontend/             # Next.js 16 / React 19 pilot UI

src/
├── application/          # retrieval/answer composition roots
├── retrieval/            # routing, channels, fusion, runtime, evaluation
├── generation/           # projection, sufficiency, prompting, grounding
├── infrastructure/       # Neo4j, embedding, reranker, Gemini adapters
├── pipeline/             # crawl, parse, extract, validate, write, reports
└── shared/               # ontology and public cross-layer contracts
```

---

### React Frontend Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ChatInterface/
│   │   ├── CitationPanel/
│   │   ├── GraphVisualizer/   # Cytoscape.js
│   │   ├── TemporalSlider/
│   │   └── ReasoningPath/
│   ├── pages/
│   │   ├── HomePage.tsx
│   │   └── ExplorerPage.tsx
│   ├── hooks/
│   │   └── useQuery.ts
│   └── api/
│       └── client.ts
└── package.json
```

---

## Environment Setup

```bash
# Python
python >= 3.11

# Required packages (không có qdrant-client hoặc llama-index — dùng Neo4j native vector + custom pipeline)
pip install \
  neo4j \
  torch \
  FlagEmbedding \
  sentence-transformers \
  fastapi \
  uvicorn \
  google-genai \
  ragas \
  pydantic

# Development
pip install pytest pytest-asyncio black ruff
```

---

## API Cost Estimate

| Model | Usage | Estimate/Month |
|---|---|---|
| Gemini Flash Lite latest | Extraction (20 docs, two-pass entity + relation extraction, rule-based confidence) | Recalculate from measured Milestone A usage |
| Configured Gemini answer model | Query answering (dev/test) | Recalculate from measured pilot usage |
| Gemini 2.5 Pro | Evaluation (RAGAS judge) | ~$5-15 |
| **Tổng** | | **~$10-30/month** |

> **Lưu ý**: Nếu vượt budget, fallback sang Ollama + Llama3.1-8B chạy local. Cost phụ thuộc số Article/Clause chunks và việc chạy extraction ở Article-level hay Clause-level.

---

## Local Fallback (Zero Cost)

```bash
# Cài Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b    # General extraction
ollama pull nomic-embed-text  # Embedding (nếu cần)
```

Local fallback must keep the same Pydantic output schema and ontology validation path as cloud providers.

---

## Literature References

| Paper | Link | Relevance |
|---|---|---|
| GraphRAG (Edge et al., 2024) | [arxiv.org/abs/2404.16130](https://arxiv.org/abs/2404.16130) | Core GraphRAG |
| From Local to Global (2024) | Microsoft Research | GraphRAG community detection |
| RAGAS (Hu et al., 2023) | [arxiv.org/abs/2309.15217](https://arxiv.org/abs/2309.15217) | Evaluation framework |
| TComplEx (Lacroix et al., 2020) | ICLR 2020 | Temporal KG |
| Pan et al. (2024) | Survey | LLMs + KGs |
| PhoBERT | VinAI Research | Vietnamese NLP |
