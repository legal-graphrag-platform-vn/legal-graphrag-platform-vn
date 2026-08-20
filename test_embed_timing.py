"""
Time just the BGE-M3 embedding model locally.
Không cần Neo4j connection.
Usage: uv run python test_embed_timing.py
"""
import time
import os

os.environ.setdefault("EMBEDDING_PROVIDER", "flag_embedding")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-m3")
os.environ.setdefault("EMBEDDING_DIM", "1024")

from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator

query = "Vốn điều lệ là gì?"

print("=" * 60)
print("BGE-M3 Embedding Timing Test")
print("=" * 60)

gen = EmbeddingGenerator(
    model_name="BAAI/bge-m3",
    provider="flag_embedding",
    expected_dimension=1024,
)

# Cold call (model load + inference)
print(f"\n[1] Cold call (loads model into RAM)...")
t0 = time.time()
vec = gen.encode([query])
t1 = time.time()
print(f"    Time: {t1 - t0:.2f}s  |  dim={len(vec[0])}")

# Warm call (model already in RAM)
print(f"\n[2] Warm call (model already loaded)...")
t0 = time.time()
vec = gen.encode([query])
t1 = time.time()
print(f"    Time: {t1 - t0:.2f}s")

print(f"\n[3] 5 warm calls in a row...")1e
times = []
for i in range(5):
    t0 = time.time()
    gen.encode([query])
    times.append(time.time() - t0)
    print(f"    Call {i+1}: {times[-1]:.2f}s")

print(f"\n    Average warm call: {sum(times)/len(times):.2f}s")
print(f"    Min: {min(times):.2f}s  Max: {max(times):.2f}s")

print("\n" + "=" * 60)
warm_avg = sum(times)/len(times)
neo4j_time = 0.5  # from our earlier test
total = warm_avg + neo4j_time
print(f"Estimated total latency: {warm_avg:.1f}s (embed) + {neo4j_time}s (neo4j) = {total:.1f}s")
if total > 30:
    print("⚠️  EXCEEDS 30s timeout! Need to increase BACKEND_RETRIEVAL_TIMEOUT_SECONDS")
else:
    print("✅  Under 30s — should work OK!")
print("=" * 60)
