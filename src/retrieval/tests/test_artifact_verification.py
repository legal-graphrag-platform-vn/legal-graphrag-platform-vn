import json
from pathlib import Path

from src.retrieval.eval.artifact_verification import build_artifact_verification
from src.retrieval.eval.development import load_development_dataset


DATASET = Path("configs/evaluation/retrieval_pilot_l59_2020.json")
HIERARCHY = Path("data/processed/L59_2020/hierarchy.json")
ACCEPTED = Path("data/processed/L59_2020/accepted.jsonl")


def test_artifact_verification_resolves_gold_and_capabilities(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({"graph_projection_sha256": "graph"}), encoding="utf-8"
    )

    report = build_artifact_verification(
        dataset=load_development_dataset(DATASET),
        dataset_path=DATASET,
        hierarchy_path=HIERARCHY,
        accepted_path=ACCEPTED,
        graph_snapshot_path=snapshot,
        capabilities=_pilot_capabilities(),
        temporal_units=_pilot_temporal_units(),
        runtime_identity=_runtime_identity(),
        source_commit="abc",
        working_tree_state="dirty",
        verification_command_hash="command",
    )

    assert report["verification"] == {
        "graph_paths_pass": True,
        "hierarchy_relations_pass": True,
        "temporal_evidence_pass": True,
        "capabilities_pass": True,
        "status": "PASS",
    }
    assert report["technical_checks_status"] == "PASS"
    assert report["evidence_tier"] == "development"
    assert report["official_evidence_eligible"] is False
    assert len(report["accepted_refers_to_records"]) == 7
    relation_ids = [
        item["relation_id"] for item in report["accepted_refers_to_records"]
    ]
    assert all(len(relation_id) == 40 for relation_id in relation_ids)
    assert len(relation_ids) == len(set(relation_ids))
    assert all(
        item["relation_id_source"] == "derived_canonical_contract"
        for item in report["accepted_refers_to_records"]
    )
    assert any(
        item["expected"]["child_id"] == "ldn_2020_art17_cl2_pa" and item["matched"]
        for item in report["hierarchy_relation_checks"]
    )
    assert report["document_metadata"]["id"] == "ldn_2020"
    temporal_checks = {
        item["query_id"]: item for item in report["temporal_evidence_checks"]
    }
    validity_05 = temporal_checks["validity_05"]
    assert validity_05["field_presence"]["effective_to"] is False
    assert validity_05["normalization"]["missing_effective_to_means"] == ("open_ended")
    assert validity_05["subject_snapshot"]["legal_status"] == "ACTIVE"
    assert validity_05["predicate_evaluation"]["computed_valid"] is True
    assert validity_05["predicate_evaluation"]["matched"] is True
    checks = {item["capability"]: item for item in report["capability_checks"]}
    assert checks["guides_relations"]["actual_available"] is False
    assert checks["multiple_versions"]["actual_available"] is False


def test_artifact_verification_fails_capability_mismatch(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")
    capabilities = _pilot_capabilities()
    capabilities["guides_relations_available"] = True

    report = build_artifact_verification(
        dataset=load_development_dataset(DATASET),
        dataset_path=DATASET,
        hierarchy_path=HIERARCHY,
        accepted_path=ACCEPTED,
        graph_snapshot_path=snapshot,
        capabilities=capabilities,
        temporal_units=_pilot_temporal_units(),
        runtime_identity=_runtime_identity(),
        source_commit="abc",
        working_tree_state="dirty",
        verification_command_hash="command",
    )

    assert report["verification"]["capabilities_pass"] is False
    assert report["verification"]["status"] == "FAIL"


def test_clean_approved_artifact_is_official_candidate(tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")

    report = build_artifact_verification(
        dataset=load_development_dataset(DATASET),
        dataset_path=DATASET,
        hierarchy_path=HIERARCHY,
        accepted_path=ACCEPTED,
        graph_snapshot_path=snapshot,
        capabilities=_pilot_capabilities(),
        temporal_units=_pilot_temporal_units(),
        runtime_identity=_runtime_identity(),
        source_commit="abc",
        working_tree_state="clean",
        verification_command_hash="command",
    )

    assert report["evidence_tier"] == "official_candidate"
    assert report["official_evidence_eligible"] is True


def _pilot_capabilities() -> dict[str, object]:
    return {
        "vector_article_index_available": True,
        "vector_clause_index_available": True,
        "fulltext_index_available": True,
        "scoped_temporal_metadata_available": True,
        "corpus_complete_current_validity_available": False,
        "temporal_relations_available": False,
        "guides_relations_available": False,
        "structural_hierarchy_available": True,
        "multiple_versions_available": False,
        "definition_relations_available": True,
        "semantic_multi_hop_graph_available": True,
        "canonical_relation_types_available": {
            "CONTAINS",
            "DEFINES",
            "ISSUED_BY",
            "REFERS_TO",
            "REGULATES",
            "REQUIRES",
        },
    }


def _pilot_temporal_units() -> list[dict[str, object]]:
    return [
        {
            "id": "ldn_2020",
            "labels": ["Document"],
            "effective_from": "2021-01-01",
            "effective_to": None,
            "legal_status": "PARTIALLY_EFFECTIVE",
            "properties": {
                "effective_from": "2021-01-01",
                "legal_status": "PARTIALLY_EFFECTIVE",
            },
        },
        {
            "id": "ldn_2020_art30",
            "labels": ["Article"],
            "effective_from": "2021-01-01",
            "effective_to": None,
            "legal_status": "ACTIVE",
            "properties": {
                "effective_from": "2021-01-01",
                "legal_status": "ACTIVE",
            },
        },
    ]


def _runtime_identity() -> dict[str, object]:
    return {
        "database_name": "neo4j",
        "components": [
            {"name": "Neo4j Kernel", "versions": ["5.26.28"], "edition": "community"}
        ],
    }
