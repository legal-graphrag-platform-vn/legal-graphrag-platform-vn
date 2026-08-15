from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.infrastructure.neo4j.writer import (
    GraphIngestionService,
    ManagedNeo4jSession,
    Neo4jWriter,
    WriteAttemptError,
    validate_graph_payload,
)
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id


def _valid_payload() -> dict:
    return {
        "nodes": [
            {
                "type": "Document",
                "id": "ldn_2020",
                "doc_type": "Law",
                "number": "59/2020/QH14",
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
                "properties": {
                    "relation_id": deterministic_relation_id(
                        "ldn_2020", "CONTAINS", "ldn_2020_art17"
                    )
                },
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
    document_call = session.run.call_args_list[0]
    assert "date($n_effective_from)" in document_call.args[0]
    assert document_call.kwargs["n_effective_from"] == "2021-01-01"
    assert "effective_from" not in document_call.kwargs["properties"]


def test_pipeline_ingestion_writes_document_section_chain() -> None:
    payload = _valid_payload()
    payload["nodes"].insert(
        1,
        {
            "type": "Section",
            "id": "ldn_2020_sec1",
            "number": "1",
            "title": "Quy định chung",
        },
    )
    payload["relations"] = [
        {
            "head_id": head_id,
            "type": "CONTAINS",
            "tail_id": tail_id,
            "properties": {
                "relation_id": deterministic_relation_id(head_id, "CONTAINS", tail_id)
            },
        }
        for head_id, tail_id in (
            ("ldn_2020", "ldn_2020_sec1"),
            ("ldn_2020_sec1", "ldn_2020_art17"),
        )
    ]
    session = Mock()

    GraphIngestionService(writer=Neo4jWriter(session=session)).ingest(payload)

    relation_calls = session.run.call_args_list[-2:]
    assert [call.kwargs["head_id"] for call in relation_calls] == [
        "ldn_2020",
        "ldn_2020_sec1",
    ]
    assert all("MERGE (head)-[r:CONTAINS" in call.args[0] for call in relation_calls)


def test_pipeline_ingestion_reconciles_only_after_validated_write() -> None:
    session = Mock()
    reconciler = Mock()
    reconciler.reconcile.return_value = {"deleted_legacy_edge_count": 0}
    service = GraphIngestionService(
        writer=Neo4jWriter(session=session),
        hierarchy_reconciler=reconciler,
    )

    validated = service.ingest(_valid_payload())

    reconciler.reconcile.assert_called_once_with(validated)
    assert service.last_hierarchy_report == {"deleted_legacy_edge_count": 0}


def test_pipeline_writer_rejects_validated_relation_without_relation_id() -> None:
    payload = _valid_payload()
    payload["relations"][0]["properties"] = {}
    validated = validate_graph_payload(payload)

    with pytest.raises(WriteAttemptError, match="relation_id"):
        Neo4jWriter(session=Mock()).write(validated)


def test_writer_rejects_invalid_temporal_value_before_merge() -> None:
    payload = _valid_payload()
    payload["nodes"][0]["effective_from"] = "01/01/2021"

    with pytest.raises(WriteAttemptError, match="ISO YYYY-MM-DD"):
        GraphIngestionService(writer=Neo4jWriter(session=Mock())).ingest(payload)


def test_managed_session_closes_session_and_driver() -> None:
    driver = Mock()
    session = Mock()

    ManagedNeo4jSession(driver=driver, session=session).close()

    session.close.assert_called_once_with()
    driver.close.assert_called_once_with()
