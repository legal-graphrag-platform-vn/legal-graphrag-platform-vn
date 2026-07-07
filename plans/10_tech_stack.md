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
| **Embedding** | `bkai-foundation-models/vietnamese-bi-encoder` | Tiếng Việt native | OpenAI text-embedding-3-small |
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

# Fallback: OpenAI (nếu Vietnamese model không đủ tốt)
# from openai import OpenAI
# client.embeddings.create(model="text-embedding-3-small", input=text)
```

---

### LlamaIndex + Neo4j Integration

```python
from llama_index.graph_stores.neo4j import Neo4jGraphStore
from llama_index.core import PropertyGraphIndex

graph_store = Neo4jGraphStore(
    username="neo4j",
    password="password",
    url="bolt://localhost:7687",
    database="neo4j"
)

# Custom: không dùng PropertyGraphIndex mặc định
# mà implement custom GraphRAG với Traversal Policy
```

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

# Required packages (không có qdrant-client — dùng Neo4j native vector)
pip install \
  llama-index \
  llama-index-graph-stores-neo4j \
  neo4j \
  sentence-transformers \
  pymupdf \
  fastapi \
  uvicorn \
  google-generativeai \
  ragas \
  pydantic

# Development
pip install pytest pytest-asyncio black ruff
```

---

## API Cost Estimate

| Model | Usage | Estimate/Month |
|---|---|---|
| Gemini 1.5 Flash | Extraction (20 docs, N=3) | ~$2-5 |
| Gemini 1.5 Flash | Query answering (dev/test) | ~$3-10 |
| Gemini 1.5 Pro | Evaluation (RAGAS judge) | ~$5-15 |
| **Tổng** | | **~$10-30/month** |

> **Lưu ý**: Nếu vượt budget, fallback sang Ollama + Llama3.1-8B chạy local.

---

## Local Fallback (Zero Cost)

```bash
# Cài Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b    # General extraction
ollama pull nomic-embed-text  # Embedding (nếu cần)
```

```python
# LlamaIndex với Ollama
from llama_index.llms.ollama import Ollama
llm = Ollama(model="llama3.1:8b", request_timeout=120.0)
```

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
