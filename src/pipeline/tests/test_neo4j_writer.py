from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.pipeline.persistence.neo4j_writer import GraphIngestionService, Neo4jWriter, WriteAttemptError, validate_graph_payload


def _valid_payload() -> dict:
    return {
        "nodes": [
            {
                "type": "Document",
                "id": "ldn_2020",
                "doc_type": "Law",
                "number": "59/2020/QH14",
                "normative": True,
                "legal_status": "ACTIVE",
                "effective_from": "2021-01-01",
                "issuer_name": "Quốc hội",
            },
            {
                "type": "Article",
                "id": "ldn_2020_art17",
                "number": "17",
                "content_raw": "Điều 17",
                "effective_from": "2021-01-01",
                "legal_status": "ACTIVE",
            },
        ],
        "relations": [
            {
                "head_id": "ldn_2020",
                "type": "CONTAINS",
                "tail_id": "ldn_2020_art17",
                "properties": {"relation_id": "rel_1"},
            }
        ],
    }


def test_pipeline_writer_rejects_raw_payload() -> None:
    writer = Neo4jWriter(session=Mock())

    with pytest.raises(WriteAttemptError):
        writer.write(_valid_payload())


def test_pipeline_ingestion_uses_root_validated_payload() -> None:
    session = Mock()
    service = GraphIngestionService(writer=Neo4jWriter(session=session))

    validated = service.ingest(_valid_payload())

    assert validated.__class__.__name__ == "ValidatedGraphPayload"
    assert validated.__class__.__module__ == "src.shared.ontology.validators"
    assert session.run.call_count == 3


def test_pipeline_writer_rejects_validated_relation_without_relation_id() -> None:
    payload = _valid_payload()
    payload["relations"][0]["properties"] = {}
    validated = validate_graph_payload(payload)

    with pytest.raises(WriteAttemptError, match="relation_id"):
        Neo4jWriter(session=Mock()).write(validated)
