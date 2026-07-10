from __future__ import annotations

from unittest.mock import Mock

from src.reports.graph_quality import GraphQualityReporter, build_graph_quality_report
from src.validation.payload_consistency_validator import deterministic_relation_id


def test_graph_quality_report_counts_nodes_and_relations() -> None:
    payload = {
        "nodes": [
            {"type": "Document", "id": "ldn_2020"},
            {"type": "Article", "id": "ldn_2020_art17", "embedding": [0.1]},
            {"type": "Clause", "id": "ldn_2020_art17_cl1"},
            {"type": "LegalConcept", "id": "von_dieu_le"},
        ],
        "relations": [
            {
                "head_id": "ldn_2020",
                "type": "CONTAINS",
                "tail_id": "ldn_2020_art17",
                "properties": {"relation_id": deterministic_relation_id("ldn_2020", "CONTAINS", "ldn_2020_art17")},
            },
            {
                "head_id": "ldn_2020_art17",
                "type": "CONTAINS",
                "tail_id": "ldn_2020_art17_cl1",
                "properties": {
                    "relation_id": deterministic_relation_id("ldn_2020_art17", "CONTAINS", "ldn_2020_art17_cl1")
                },
            },
            {
                "head_id": "ldn_2020_art17",
                "type": "DEFINES",
                "tail_id": "von_dieu_le",
                "properties": {
                    "relation_id": deterministic_relation_id("ldn_2020_art17", "DEFINES", "von_dieu_le")
                },
            },
        ],
    }

    report = build_graph_quality_report(payload)

    assert report["document_count"] == 1
    assert report["article_count"] == 1
    assert report["clause_count"] == 1
    assert report["semantic_node_count"] == 1
    assert report["relation_count_by_type"]["CONTAINS"] == 2


def test_online_graph_quality_uses_neo4j_embedding_coverage() -> None:
    session = Mock()
    session.run.side_effect = [
        [
            {
                "node_ids": [
                    "ldn_2020",
                    "issuer_quoc_hoi",
                    "ldn_2020_art17",
                    "ldn_2020_art18",
                    "ldn_2020_art17_cl1",
                    "cong_ty",
                    "von_dieu_le",
                    "orphan_concept",
                ]
            }
        ],
        [
            {"labels": ["Document"], "count": 1},
            {"labels": ["Issuer"], "count": 1},
            {"labels": ["Article"], "count": 2},
            {"labels": ["Clause"], "count": 1},
            {"labels": ["LegalSubject"], "count": 1},
            {"labels": ["LegalConcept"], "count": 2},
        ],
        [{"total": 2, "embedded": 2}],
        [{"total": 1, "embedded": 0}],
        [{"count": 1}],
        [
            {
                "source": "ldn_2020",
                "source_labels": ["Document"],
                "source_doc_type": "Law",
                "relation_type": "CONTAINS",
                "properties": {"relation_id": "x"},
                "relation_id": "x",
                "target": "ldn_2020_art17",
                "target_labels": ["Article"],
                "target_doc_type": None,
            },
            {
                "source": "ldn_2020",
                "source_labels": ["Document"],
                "source_doc_type": "Law",
                "relation_type": "ISSUED_BY",
                "properties": {"relation_id": "issued"},
                "relation_id": "issued",
                "target": "issuer_quoc_hoi",
                "target_labels": ["Issuer"],
                "target_doc_type": None,
            },
            {
                "source": "ldn_2020_art17",
                "source_labels": ["Article"],
                "source_doc_type": None,
                "relation_type": "DEFINES",
                "properties": {},
                "relation_id": "defines",
                "target": "von_dieu_le",
                "target_labels": ["LegalConcept"],
                "target_doc_type": None,
            },
            {
                "source": "ldn_2020_art17",
                "source_labels": ["Article"],
                "source_doc_type": None,
                "relation_type": "REGULATES",
                "properties": {"confidence": 0.9, "llm_model": "test", "created_at": "2026-07-10T00:00:00Z"},
                "relation_id": "regulates",
                "target": "cong_ty",
                "target_labels": ["LegalSubject"],
                "target_doc_type": None,
            },
            {
                "source": "cong_ty",
                "source_labels": ["LegalSubject"],
                "source_doc_type": None,
                "relation_type": "REQUIRES",
                "properties": {"confidence": 0.9, "llm_model": "test", "created_at": "2026-07-10T00:00:00Z"},
                "relation_id": "requires",
                "target": "von_dieu_le",
                "target_labels": ["LegalConcept"],
                "target_doc_type": None,
            },
            {
                "source": "ldn_2020",
                "source_labels": ["Document"],
                "source_doc_type": "Law",
                "relation_type": "CONTAINS",
                "properties": {"relation_id": "x"},
                "relation_id": "x",
                "target": "ldn_2020_art18",
                "target_labels": ["Article"],
                "target_doc_type": None,
            },
        ],
    ]

    report = GraphQualityReporter(session=session).generate_for_document("ldn_2020")

    assert report["source"] == "neo4j"
    assert report["document_count"] == 1
    assert report["issuer_count"] == 1
    assert report["article_count"] == 2
    assert report["clause_count"] == 1
    assert report["legal_concept_count"] == 2
    assert report["legal_subject_count"] == 1
    assert report["semantic_node_count"] == 3
    assert report["embedding_coverage"]["Article"] == 1.0
    assert report["embedding_coverage"]["Clause"] == 0.0
    assert report["relation_count_by_type"]["DEFINES"] == 1
    assert report["relation_count_by_type"]["REQUIRES"] == 1
    assert report["duplicate_node_id_count"] == 1
    assert report["duplicate_relation_identity_count"] == 1
    assert report["orphan_node_count"] == 2
    assert report["connected_component_count"] == 3
    assert report["ontology_violation_count"] == 1
    assert report["ontology_violation_rate"] == 1 / 6
