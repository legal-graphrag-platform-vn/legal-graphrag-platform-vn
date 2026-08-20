"""Time each stage of the retrieval pipeline against production Neo4j."""
import json
import time
import urllib.request

# Production Neo4j HTTP API
URL = "https://graph-ui.lamdx4.duckdns.org/db/neo4j/tx/commit"
AUTH = ("neo4j", "123456789")

# A proper 1024-dim vector (uniform, matches embedding dim)
EMBEDDING = [0.001] * 1024

def run_query(label, statement, params=None):
    body = json.dumps({
        "statements": [{
            "statement": statement,
            "parameters": params or {}
        }]
    }).encode()

    import base64
    token = base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()

    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        },
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    elapsed = time.time() - t0

    errors = data.get("errors", [])
    results = data.get("results", [{}])
    rows = results[0].get("data", []) if results else []

    if errors:
        print(f"[{label}] ERROR in {elapsed:.2f}s: {errors[0]['message'][:120]}")
    else:
        print(f"[{label}] OK in {elapsed:.2f}s — {len(rows)} rows returned")
    return elapsed


print("=" * 60)
print("Benchmarking production Neo4j vector search")
print("=" * 60)

# Test 1: Single index (clause_embedding)
run_query(
    "Single index (clause_embedding) k=20",
    "CALL db.index.vector.queryNodes('clause_embedding', 20, $e) YIELD node, score RETURN node.id AS id, score",
    {"e": EMBEDDING},
)

# Test 2: UNION ALL 3 indexes (new code)
run_query(
    "UNION ALL 3 indexes",
    """
    CALL {
        CALL db.index.vector.queryNodes('article_embedding', 20, $e) YIELD node, score RETURN node, score
        UNION ALL
        CALL db.index.vector.queryNodes('clause_embedding', 20, $e) YIELD node, score RETURN node, score
        UNION ALL
        CALL db.index.vector.queryNodes('appendix_embedding', 20, $e) YIELD node, score RETURN node, score
    }
    WITH node, score
    RETURN node.id AS id, score ORDER BY score DESC LIMIT 5
    """,
    {"e": EMBEDDING},
)

# Test 3: Full query with CONTAINS traversal (what the backend actually runs)
run_query(
    "Full query with CONTAINS traversal",
    """
    CALL {
        CALL db.index.vector.queryNodes('article_embedding', 20, $e) YIELD node, score RETURN node, score
        UNION ALL
        CALL db.index.vector.queryNodes('clause_embedding', 20, $e) YIELD node, score RETURN node, score
        UNION ALL
        CALL db.index.vector.queryNodes('appendix_embedding', 20, $e) YIELD node, score RETURN node, score
    }
    WITH node, score
    OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(node)
    MATCH (document:Document)-[:CONTAINS*1..4]->(node)
    WHERE ($document_ids = [] OR document.id IN $document_ids)
    RETURN node.id AS id, score ORDER BY score DESC LIMIT 5
    """,
    {"e": EMBEDDING, "document_ids": []},
)

print("=" * 60)
print("Done. If all 3 are fast (<5s), the bottleneck is in the EMBEDDING GENERATION step on server CPU.")
print("=" * 60)
