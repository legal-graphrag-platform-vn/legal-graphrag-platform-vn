import pytest
from src.infrastructure.neo4j.writer import GraphIngestionService, Neo4jWriter, create_neo4j_session
from src.pipeline.reports.graph_quality import GraphQualityReporter
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id

@pytest.fixture(autouse=True)
def setup_test_nodes():
    session = create_neo4j_session()
    try:
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_qual_' DETACH DELETE n")
        yield
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_qual_' DETACH DELETE n")
    finally:
        session.close()

def test_online_graph_quality_report():
    session = create_neo4j_session()
    try:
        service = GraphIngestionService(writer=Neo4jWriter(session=session))

        relation_id = deterministic_relation_id("test_qual_doc", "CONTAINS", "test_qual_art1")
        payload = {
            "nodes": [
                {
                    "type": "Document",
                    "id": "test_qual_doc",
                    "doc_type": "Law",
                    "number": "99/2026/QH15",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2026-01-01",
                    "issuer_name": "National Assembly",
                },
                {
                    "type": "Article",
                    "id": "test_qual_art1",
                    "number": "1",
                    "content_raw": "Test Article Content",
                    "effective_from": "2026-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": "test_qual_doc",
                    "type": "CONTAINS",
                    "tail_id": "test_qual_art1",
                    "properties": {"relation_id": relation_id},
                }
            ],
        }

        # Ingest the test payload
        service.ingest(payload)

        # Generate report
        reporter = GraphQualityReporter(session=session)
        report = reporter.generate_for_document("test_qual_doc")

        # Verify report values
        assert report["document_count"] == 1
        assert report["article_count"] == 1
        assert report["clause_count"] == 0
        assert report["duplicate_node_id_count"] == 0
        assert report["duplicate_relation_identity_count"] == 0
        assert report["dangling_endpoint_count"] == 0
        assert report["ontology_violation_count"] == 0
        assert report["connected_component_count"] == 1

    finally:
        session.close()
