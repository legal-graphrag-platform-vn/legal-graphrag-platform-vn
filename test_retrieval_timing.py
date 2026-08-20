"""
Quick local retrieval timing test against production Neo4j.
Usage: uv run python test_retrieval_timing.py
"""
import os, time

# Point to production Neo4j
os.environ.setdefault("NEO4J_URI", "neo4j+s://graph-connection.lamdx4.duckdns.org:443")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "123456789")
os.environ.setdefault("EMBEDDING_PROVIDER", "flag_embedding")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-m3")
os.environ.setdefault("EMBEDDING_DIM", "1024")

from src.application.retrieval_factory import (
    RetrievalApplicationSettings,
    create_retrieval_runtime,
)
from src.retrieval.config import RetrievalConfig
from src.shared.retrieval_contract import RetrievalFilters

query = "Vốn điều lệ là gì?"

print("=" * 60)
print(f"Query: {query}")
print("=" * 60)

config = RetrievalConfig()
settings = RetrievalApplicationSettings()

with create_retrieval_runtime(config, settings) as runtime:
    # ---- 1. Time just the embedding ----
    print("\n[1] Warming up embedding model (first call loads weights)...")
    t0 = time.time()
    embedding = runtime._warmup_encoder.encode([query])
    t1 = time.time()
    print(f"    Embedding (first call): {t1 - t0:.2f}s  dim={len(embedding[0])}")

    print("\n[2] Timing embedding (second call, model already loaded)...")
    t0 = time.time()
    embedding = runtime._warmup_encoder.encode([query])
    t1 = time.time()
    print(f"    Embedding (warm call):  {t1 - t0:.2f}s")

    # ---- 2. Time vector search ----
    print("\n[3] Timing vector search in Neo4j (using warm embedding)...")
    from src.retrieval.retriever.vector import VECTOR_INDEXES
    from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    repo = Neo4jRetrieverRepo(driver)  # type: ignore

    t0 = time.time()
    rows = repo.vector_search(
        list(VECTOR_INDEXES),
        embedding[0],
        filters=RetrievalFilters(),
        k=5,
    )
    t1 = time.time()
    print(f"    Neo4j vector search:    {t1 - t0:.2f}s  rows={len(rows)}")
    for r in rows[:3]:
        print(f"      - {r.get('id')} (score={r.get('score', 0):.4f})")
    driver.close()

print("\n" + "=" * 60)
print("Summary: if embedding warm call is >5s, that's the bottleneck on CPU!")
print("=" * 60)
