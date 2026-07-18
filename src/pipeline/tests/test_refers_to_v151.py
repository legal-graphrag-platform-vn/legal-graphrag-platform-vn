from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from src.pipeline.pipeline.artifact_store import (
    ACTIVE_ARTIFACT_NAMES,
    create_staging_artifact_dir,
    publish_staged_artifacts,
)
from src.pipeline.pipeline.orchestrator import (
    _checkpoint_fingerprint,
    _result_from_checkpoint,
)
from src.pipeline.extraction.structural_context import ArticleExtractionContext
from src.shared.ontology.validators import validate_relation


COMPLETE_PROPERTIES = {
    "confidence": 0.8,
    "llm_model": "gemini:gemini-3.1-flash-lite",
    "created_at": "2026-07-12T02:00:00Z",
    "citation_text": "Theo Điều 17 Luật này",
    "citation_type": "DIRECT",
    "extraction_method": "LLM",
    "reference_bundle_id": "bundle-17",
    "reference_target_count": 1,
    "checkpoint_id": "checkpoint-17",
}


@pytest.mark.parametrize("missing", COMPLETE_PROPERTIES)
def test_refers_to_requires_every_v160_llm_property(missing: str) -> None:
    properties = dict(COMPLETE_PROPERTIES)
    properties.pop(missing)

    ok, error = validate_relation(
        "Article", "REFERS_TO", "Article", properties=properties
    )

    assert ok is False
    assert missing in (error or "")


def test_v151_refers_to_artifact_fails_v160_contract() -> None:
    ok, error = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties={"citation_text": "Điều 17", "citation_type": "DIRECT"},
    )

    assert ok is False
    assert "extraction_method" in (error or "")


def test_rule_refers_to_does_not_require_llm_provenance() -> None:
    ok, error = validate_relation(
        "Point",
        "REFERS_TO",
        "Point",
        properties={
            "citation_text": "các điểm a và b khoản này",
            "citation_type": "RANGE",
            "extraction_method": "RULE",
            "created_at": "2026-07-18T00:00:00Z",
            "reference_bundle_id": "bundle-ab",
            "reference_target_count": 2,
            "resolver_name": "vn-structural-reference-resolver",
            "resolver_version": "2.0.0",
            "source_unit_id": "ldn_2020_art1_cl1_pc",
            "source_char_start": 20,
            "source_char_end": 48,
        },
    )

    assert ok, error


def test_checkpoint_provenance_is_loaded_and_timestamp_normalized() -> None:
    result = _result_from_checkpoint(
        {
            "article_number": "17",
            "provider": "gemini",
            "configured_model": "gemini:latest",
            "resolved_model": "gemini-3.1-flash-lite",
            "completed_at": "2026-07-12T09:00:00+07:00",
            "relations": [],
        }
    )

    assert result.provider == "gemini"
    assert result.resolved_model == "gemini-3.1-flash-lite"
    assert result.completed_at == "2026-07-12T02:00:00Z"


def test_checkpoint_missing_completed_at_is_not_defaulted() -> None:
    with pytest.raises(ValueError, match="missing completed_at"):
        _result_from_checkpoint(
            {"article_number": "17", "provider": "gemini", "resolved_model": "model"}
        )


def test_checkpoint_fingerprint_uses_recorded_model_not_current_environment() -> None:
    context = ArticleExtractionContext(
        raw_doc_code="L59_2020",
        graph_id="ldn_2020",
        article_number="17",
        article_id="ldn_2020_art17",
        clause_ids={},
        point_ids={},
    )
    expected = _checkpoint_fingerprint(
        context,
        "Nội dung",
        provider="gemini",
        configured_model="gemini:old-alias",
    )

    with patch(
        "src.pipeline.pipeline.orchestrator._configured_llm_model",
        return_value="gemini:new-alias",
    ):
        actual = _checkpoint_fingerprint(
            context,
            "Nội dung",
            provider="gemini",
            configured_model="gemini:old-alias",
        )

    assert actual == expected


def test_artifact_set_is_not_published_until_complete(tmp_path) -> None:
    artifact_set_id, staging = create_staging_artifact_dir(tmp_path)
    (staging / "extract.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete"):
        publish_staged_artifacts(tmp_path, artifact_set_id, staging)

    assert not (tmp_path / "current_extraction").exists()


def test_complete_artifact_set_switches_active_pointer(tmp_path) -> None:
    artifact_set_id, staging = create_staging_artifact_dir(tmp_path)
    for name in ACTIVE_ARTIFACT_NAMES:
        content = "{}" if name.endswith(".json") else ""
        (staging / name).write_text(content, encoding="utf-8")

    published = publish_staged_artifacts(tmp_path, artifact_set_id, staging)

    assert (tmp_path / "current_extraction").resolve() == published.resolve()
    assert (
        json.loads((tmp_path / "entity_index.json").read_text(encoding="utf-8")) == {}
    )
