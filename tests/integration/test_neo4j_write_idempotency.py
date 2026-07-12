import pytest

pytestmark = pytest.mark.integration
from src.infrastructure.neo4j.writer import GraphIngestionService, Neo4jWriter, create_neo4j_session
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id

@pytest.fixture(autouse=True)
def cleanup_neo4j():
    session = create_neo4j_session()
    try:
        # Clean before test
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_idemp_' DETACH DELETE n")
        yield
        # Clean after test
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_idemp_' DETACH DELETE n")
    finally:
        session.close()

def test_idempotent_writes():
    session = create_neo4j_session()
    try:
        service = GraphIngestionService(writer=Neo4jWriter(session=session))

        relation_id = deterministic_relation_id("test_idemp_doc", "CONTAINS", "test_idemp_art1")
        payload = {
            "nodes": [
                {
                    "type": "Document",
                    "id": "test_idemp_doc",
                    "doc_type": "Law",
                    "number": "99/2026/QH15",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2026-01-01",
                    "issuer_name": "National Assembly",
                },
                {
                    "type": "Article",
                    "id": "test_idemp_art1",
                    "number": "1",
                    "content_raw": "Test Article Content",
                    "effective_from": "2026-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": "test_idemp_doc",
                    "type": "CONTAINS",
                    "tail_id": "test_idemp_art1",
                    "properties": {"relation_id": relation_id},
                }
            ],
        }

        # First Write
        service.ingest(payload)

        # Count nodes and relations
        result_nodes = list(session.run(
            "MATCH (n) WHERE n.id STARTS WITH 'test_idemp_' RETURN count(n) as cnt"
        ))
        result_rels = list(session.run(
            "MATCH (n)-[r]->() WHERE n.id STARTS WITH 'test_idemp_' RETURN count(r) as cnt"
        ))
        
        node_count_1 = result_nodes[0]["cnt"]
        rel_count_1 = result_rels[0]["cnt"]
        
        assert node_count_1 == 2
        assert rel_count_1 == 1

        # Second Write (duplicate)
        service.ingest(payload)

        # Count nodes and relations again
        result_nodes_2 = list(session.run(
            "MATCH (n) WHERE n.id STARTS WITH 'test_idemp_' RETURN count(n) as cnt"
        ))
        result_rels_2 = list(session.run(
            "MATCH (n)-[r]->() WHERE n.id STARTS WITH 'test_idemp_' RETURN count(r) as cnt"
        ))
        
        assert result_nodes_2[0]["cnt"] == node_count_1, "Node count changed (not idempotent)"
        assert result_rels_2[0]["cnt"] == rel_count_1, "Relationship count changed (not idempotent)"

    finally:
        session.close()
