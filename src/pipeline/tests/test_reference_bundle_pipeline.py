import json

from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import StructuralReferenceResolver
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import DocumentInfo
from src.pipeline.pipeline.orchestrator import (
    _apply_atomic_bundle_decisions,
    _rule_reference_records,
    _update_reference_checkpoints,
)


def _fixture():
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
b) Nghĩa vụ b;
c) Theo các điểm a và b khoản này.
"""
    document = DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )
    parsed = parse_text(text, document)
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )
    return registry, references


def test_rule_bundle_records_share_atomic_target_count(tmp_path) -> None:
    registry, references = _fixture()
    checkpoints = _update_reference_checkpoints(
        tmp_path / "references.jsonl",
        references,
        selected_article_ids={"ldn_2020_art1"},
    )

    records = _rule_reference_records(references, checkpoints, registry)

    assert len(records) == 2
    properties = [record["relation"]["properties"] for record in records]
    assert {item["reference_bundle_id"] for item in properties} == {
        references[0].mention.reference_bundle_id
    }
    assert {item["reference_target_count"] for item in properties} == {2}
    assert all(item["extraction_method"] == "RULE" for item in properties)


def test_atomic_decision_rejects_every_edge_when_one_edge_fails() -> None:
    bundle = "bundle-ab"
    records = [
        {
            "decision": "accepted",
            "relation": {
                "properties": {
                    "extraction_method": "RULE",
                    "reference_bundle_id": bundle,
                }
            },
        },
        {
            "decision": "rejected",
            "relation": {
                "properties": {
                    "extraction_method": "RULE",
                    "reference_bundle_id": bundle,
                }
            },
        },
    ]

    decided = _apply_atomic_bundle_decisions(records)

    assert {record["decision"] for record in decided} == {"rejected"}
    assert all(
        record["review_reason"] == "atomic_reference_bundle_validation_failed"
        for record in decided
    )


def test_reference_checkpoint_reuses_created_at_for_unchanged_fingerprint(
    tmp_path,
) -> None:
    _, references = _fixture()
    path = tmp_path / "references.jsonl"
    first = _update_reference_checkpoints(
        path,
        references,
        selected_article_ids={"ldn_2020_art1"},
    )
    second = _update_reference_checkpoints(
        path,
        references,
        selected_article_ids={"ldn_2020_art1"},
    )

    bundle_id = references[0].mention.reference_bundle_id
    assert first[bundle_id]["created_at"] == second[bundle_id]["created_at"]
    assert (
        len([line for line in path.read_text(encoding="utf-8").splitlines() if line])
        == 1
    )
    assert (
        json.loads(path.read_text(encoding="utf-8"))["reference_bundle_id"] == bundle_id
    )
