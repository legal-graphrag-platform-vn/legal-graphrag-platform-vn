import pytest
from src.infrastructure.neo4j.writer import GraphIngestionService, Neo4jWriter, create_neo4j_session
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id

pytestmark = pytest.mark.integration

def test_idempotent_writes(isolated_neo4j_prefix):
    prefix = isolated_neo4j_prefix
    doc_id = f"{prefix}doc"
    article_id = f"{prefix}art1"
    session = create_neo4j_session()
    try:
        service = GraphIngestionService(writer=Neo4jWriter(session=session))

        relation_id = deterministic_relation_id(doc_id, "CONTAINS", article_id)
        payload = {
            "nodes": [
                {
                    "type": "Document",
                    "id": doc_id,
                    "doc_type": "Law",
                    "number": "99/2026/QH15",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2026-01-01",
                    "issuer_name": "National Assembly",
                },
                {
                    "type": "Article",
                    "id": article_id,
                    "number": "1",
                    "content_raw": "Test Article Content",
                    "effective_from": "2026-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": doc_id,
                    "type": "CONTAINS",
                    "tail_id": article_id,
                    "properties": {"relation_id": relation_id},
                }
            ],
        }

        # First Write
        service.ingest(payload)

        # Count nodes and relations
        result_nodes = list(session.run(
            "MATCH (n) WHERE n.id STARTS WITH $prefix RETURN count(n) as cnt", prefix=prefix
        ))
        result_rels = list(session.run(
            "MATCH (n)-[r]->() WHERE n.id STARTS WITH $prefix RETURN count(r) as cnt", prefix=prefix
        ))
        
        node_count_1 = result_nodes[0]["cnt"]
        rel_count_1 = result_rels[0]["cnt"]
        
        assert node_count_1 == 2
        assert rel_count_1 == 1

        # Second Write (duplicate)
        service.ingest(payload)

        # Count nodes and relations again
        result_nodes_2 = list(session.run(
            "MATCH (n) WHERE n.id STARTS WITH $prefix RETURN count(n) as cnt", prefix=prefix
        ))
        result_rels_2 = list(session.run(
            "MATCH (n)-[r]->() WHERE n.id STARTS WITH $prefix RETURN count(r) as cnt", prefix=prefix
        ))
        
        assert result_nodes_2[0]["cnt"] == node_count_1, "Node count changed (not idempotent)"
        assert result_rels_2[0]["cnt"] == rel_count_1, "Relationship count changed (not idempotent)"

    finally:
        session.close()
