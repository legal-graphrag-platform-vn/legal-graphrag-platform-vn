from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.infrastructure.neo4j.hierarchy_reconciler import (
    HierarchyReconciliationError,
    SectionHierarchyReconciler,
)
from src.infrastructure.neo4j.writer import validate_graph_payload
from src.shared.ontology.payload_consistency_validator import deterministic_relation_id


def _validated_section_payload():
    relations = [
        ("doc", "Document", "doc_ch3", "Chapter"),
        ("doc_ch3", "Chapter", "doc_ch3_sec1", "Section"),
        ("doc_ch3_sec1", "Section", "doc_art46", "Article"),
    ]
    return validate_graph_payload(
        {
            "nodes": [
                {
                    "type": "Document",
                    "id": "doc",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2021-01-01",
                    "issuer_name": "Quốc hội",
                },
                {
                    "type": "Chapter",
                    "id": "doc_ch3",
                    "number": "III",
                    "title": "Công ty",
                },
                {
                    "type": "Section",
                    "id": "doc_ch3_sec1",
                    "number": "1",
                    "title": "Công ty trách nhiệm hữu hạn",
                },
                {
                    "type": "Article",
                    "id": "doc_art46",
                    "number": "46",
                    "title": "Công ty",
                    "content_raw": "Nội dung",
                    "effective_from": "2021-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": head,
                    "head_type": head_type,
                    "type": "CONTAINS",
                    "tail_id": tail,
                    "tail_type": tail_type,
                    "properties": {
                        "relation_id": deterministic_relation_id(head, "CONTAINS", tail)
                    },
                }
                for head, head_type, tail, tail_type in relations
            ],
        }
    )


def test_reconciler_deletes_only_exact_legacy_edge_after_chain_verification() -> None:
    session = Mock()
    session.run.return_value = [
        {"all_chains_exist": True, "deleted_legacy_edge_count": 1}
    ]

    report = SectionHierarchyReconciler(session).reconcile(_validated_section_payload())

    assert report.mapping_count == 1
    assert report.deleted_legacy_edge_count == 1
    call = session.run.call_args
    assert "all(item IN chain_checks WHERE item)" in call.args[0]
    assert call.kwargs["mappings"] == [
        {
            "chapter_id": "doc_ch3",
            "section_id": "doc_ch3_sec1",
            "article_id": "doc_art46",
        }
    ]


def test_reconciler_preserves_legacy_edges_when_new_chain_is_missing() -> None:
    session = Mock()
    session.run.return_value = [
        {"all_chains_exist": False, "deleted_legacy_edge_count": 0}
    ]

    with pytest.raises(
        HierarchyReconciliationError, match="legacy edges were preserved"
    ):
        SectionHierarchyReconciler(session).reconcile(_validated_section_payload())


def test_reconciler_rerun_is_idempotent() -> None:
    session = Mock()
    session.run.side_effect = [
        [{"all_chains_exist": True, "deleted_legacy_edge_count": 1}],
        [{"all_chains_exist": True, "deleted_legacy_edge_count": 0}],
    ]
    reconciler = SectionHierarchyReconciler(session)
    payload = _validated_section_payload()

    first = reconciler.reconcile(payload)
    second = reconciler.reconcile(payload)

    assert first.deleted_legacy_edge_count == 1
    assert second.deleted_legacy_edge_count == 0
