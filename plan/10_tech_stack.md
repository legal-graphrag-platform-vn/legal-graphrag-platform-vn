# Tech Stack

> **Nguyên tắc lựa chọn**: Ưu tiên open-source, tiết kiệm cost, có tài liệu tốt cho tiếng Việt

---

## Core Stack

| Layer | Công Nghệ | Lý Do Chọn | Thay Thế |
|---|---|---|---|
| **Graph DB** | Neo4j Community | Cypher query mạnh, tài liệu nhiều, miễn phí | ArangoDB |
| **Vector Store** | Qdrant | Open-source, Docker-friendly, performance tốt | ChromaDB |
| **LLM (main)** | Gemini 1.5 Flash | Cost-effective, hỗ trợ Vietnamese tốt | GPT-4o-mini |
| **LLM (judge)** | Gemini 1.5 Pro | Evaluation quality cần model mạnh hơn | GPT-4o |
| **Embedding** | `bkai-foundation-models/vietnamese-bi-encoder` | Tiếng Việt native | OpenAI text-embedding-3-small |
| **PDF Parser** | PyMuPDF | Nhanh, access font/format info | pdfplumber |
| **Framework** | LlamaIndex | GraphRAG support tốt hơn LangChain | LangChain |
| **Backend** | FastAPI | Async, OpenAPI docs tự động | Flask |
| **Frontend** | React + Vite | Standard, tài liệu nhiều | Next.js |
| **Graph UI** | Cytoscape.js | Chuyên cho graph, dễ hơn D3.js | D3.js |
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

### Qdrant (Vector Store)

```yaml
qdrant:
  image: qdrant/qdrant:latest
  ports:
    - "6333:6333"
  volumes:
    - ./data/qdrant:/qdrant/storage
```

**Collection setup:**
```python
client.create_collection(
    collection_name="legal_chunks",
    vectors_config=VectorParams(
        size=768,  # vietnamese-bi-encoder dimension
        distance=Distance.COSINE
    )
)
```

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
│   ├── parser/           # PDF Hierarchy Parser
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

# Required packages
pip install \
  llama-index \
  llama-index-graph-stores-neo4j \
  neo4j \
  qdrant-client \
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
