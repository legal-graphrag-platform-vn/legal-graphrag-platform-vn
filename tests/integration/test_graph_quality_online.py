import pytest
from src.infrastructure.neo4j.writer import GraphIngestionService, Neo4jWriter, create_neo4j_session
from src.pipeline.reports.graph_quality import GraphQualityReporter
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id


pytestmark = pytest.mark.integration

def test_online_graph_quality_report(isolated_neo4j_prefix):
    doc_id = f"{isolated_neo4j_prefix}doc"
    article_id = f"{isolated_neo4j_prefix}art1"
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

        # Ingest the test payload
        service.ingest(payload)

        # Generate report
        reporter = GraphQualityReporter(session=session)
        report = reporter.generate_for_document(doc_id)

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
