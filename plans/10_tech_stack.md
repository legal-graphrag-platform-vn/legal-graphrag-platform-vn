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
| **LLM (main)** | Gemini **2.5** Flash | Cost-effective, hỗ trợ Vietnamese tốt | GPT-4o-mini |
| **LLM (judge)** | Gemini **2.5** Pro | Evaluation quality cần model mạnh hơn | GPT-4o |
| **LLM SDK** | `google-genai` | SDK mới (thay `google-generativeai` đã deprecated) | — |
| **Embedding** | `bkai-foundation-models/vietnamese-bi-encoder` | Tiếng Việt native, 768-dim khớp vector index | `BAAI/bge-m3` sau khi verify dimension |
| **Hierarchy Parser** | Raw text parser | Khớp với `source.txt` từ crawler; retry/fallback selector nếu crawl lỗi | — |
| **Framework** | **Custom Pipeline** (không dùng LlamaIndex) | LlamaIndex không có direct support cho cấu trúc hà văn bản pháp luật VN | LlamaIndex |
| **Backend** | FastAPI | Async, OpenAPI docs tự động | Flask |
| **Frontend** | TBD (React hoặc Gradio — chốt sau Q2a) | Phụ thuộc scope | Next.js |
| **Graph UI** | Cytoscape.js / pyvis | Chuyên cho graph | D3.js |
| **Evaluation** | RAGAS | Industry standard cho RAG evaluation | DeepEval |

---

## Chi Tiết Từng Component

### Neo4j

```yaml
# docker-compose.yml
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
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX article_embedding
FOR (a:Article) ON a.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
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
# Vietnamese-specific embedding
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "bkai-foundation-models/vietnamese-bi-encoder"
)

# Fallback: BAAI/bge-m3 chỉ dùng sau khi verify dimension và cập nhật vector index nếu cần.
```

---

## Model Candidate Matrix

This table is the canonical model-selection map for implementation and thesis defense. `Primary` means the default for the current research prototype. `Candidate / Fallback` means allowed alternatives for ablation, quota failure, local fallback, or future training. Before implementation, verify model availability, license, context length, output schema support, and embedding dimension.

| Component | Primary | Candidate / Fallback | Future fine-tune? | Why this fits |
|---|---|---|---|---|
| Information Extraction | Gemini 2.5 Flash structured output | Gemini 2.5 Pro for hard cases; GPT-4o-mini; Qwen3-8B local | Optional LoRA local LLM | Needs reliable JSON/Pydantic output, Vietnamese legal text handling, low cost for batch extraction |
| Answer Generation | Gemini 2.5 Flash | Gemini 2.5 Pro for hard cases; Qwen3-8B local | Not priority | Generation is grounded by retrieved graph evidence; fine-tuning is less important than citation discipline |
| Judge / Evaluation | Gemini 2.5 Pro | GPT-4o; Gemini Flash smoke test | No | Judge should be stronger and more stable than the default generation model |
| Embedding | `bkai-foundation-models/vietnamese-bi-encoder` | `Qwen3-Embedding-0.6B`; `BAAI/bge-m3` after dimension check | Yes, after query-positive pairs exist | Primary is Vietnamese-focused and 768-dim; alternatives are for retrieval ablation |
| Intent Classifier | Gemini 2.5 Flash few-shot | PhoBERT-base-v2; XLM-R; BamiBERT | Yes, PhoBERT fine-tune | Six-class intent task can start with few-shot LLM; fine-tune only after labeled query set exists |
| Temporal Extractor | Rule-based date regex/parser + Gemini 2.5 Flash fallback | Gemini 2.5 Pro for hard cases; BERT classifier | Not priority | Legal temporal expressions are often deterministic; LLM fallback handles ambiguous wording |
| Reranker | Not enabled in M3 | `bge-reranker-v2-m3`; `Qwen3-Reranker-0.6B`; `gte-multilingual-reranker-base` | Yes, after retrieval dataset exists | Reranker belongs to Phase 2.5 ablation, not Neo4j Writer M3 |
| BM25 / Full-text | Neo4j fulltext index | External BM25 only if Neo4j fulltext is insufficient | No | Not a neural model; used as keyword retrieval/fusion or optional ablation |

### Training Priority

1. **Extraction training**: optional local LoRA only after enough corrected extraction triples exist.
2. **Intent training**: PhoBERT/XLM-R fine-tune after a labeled intent dataset exists.
3. **Embedding/reranker training**: only after query-positive/negative retrieval pairs exist.
4. **Answer generation training**: not prioritized; improve prompts, retrieval, citation checks, and evidence verifier first.

---

### FastAPI Backend Structure

```
backend/
├── main.py
├── api/
│   ├── routes/
│   │   ├── query.py      # POST /query
│   │   ├── graph.py      # GET /graph/{node_id}
│   │   └── admin.py      # POST /ingest
│   └── models.py
├── core/
│   ├── parser/           # Raw text Hierarchy Parser
│   ├── extraction/       # LLM Extraction
│   ├── validation/       # Ontology + Schema Validator
│   ├── retrieval/        # Hybrid Retriever
│   │   ├── vector.py
│   │   ├── graph.py
│   │   └── traversal_policy.py
│   ├── generation/       # Answer Generator
│   └── evaluation/       # RAGAS integration
├── graph/
│   ├── neo4j_client.py
│   └── queries.py        # Cypher query templates
└── config.py
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
| Gemini 2.5 Flash | Extraction (20 docs, two-pass entity + relation extraction, rule-based confidence) | ~$1-3 |
| Gemini 2.5 Flash | Query answering (dev/test) | ~$3-10 |
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
