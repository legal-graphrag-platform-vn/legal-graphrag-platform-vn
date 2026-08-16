import json

import pytest

from src.pipeline.validation.extraction_readiness import (
    ExtractionReadinessError,
    validate_extraction_readiness,
)


def _write_artifacts(tmp_path, *, extracted=1, accepted=1, review=0, rejected=0):
    for name, count in (("extract", extracted), ("accepted", accepted), ("review", review), ("rejected", rejected)):
        (tmp_path / f"{name}.jsonl").write_text("".join(json.dumps({"decision": name}) + "\n" for _ in range(count)))
    (tmp_path / "entity_index.json").write_text("{}")


def test_extraction_readiness_rejects_empty_accepted_artifact(tmp_path) -> None:
    _write_artifacts(tmp_path, extracted=0, accepted=0)
    with pytest.raises(ExtractionReadinessError, match="Gate 2"):
        validate_extraction_readiness(tmp_path)


def test_extraction_readiness_requires_reconciled_decisions(tmp_path) -> None:
    _write_artifacts(tmp_path, extracted=2, accepted=1)
    with pytest.raises(ExtractionReadinessError, match="reconcile"):
        validate_extraction_readiness(tmp_path)


def test_extraction_readiness_rejects_empty_entity_index(tmp_path) -> None:
    _write_artifacts(tmp_path, extracted=1, accepted=1)
    with pytest.raises(ExtractionReadinessError, match="entity_index.json is empty"):
        validate_extraction_readiness(tmp_path)


def test_extraction_readiness_rejects_smoke_subset(tmp_path) -> None:
    (tmp_path / "extraction_run.json").write_text(
        json.dumps({"complete_document": False, "selected_articles": ["5"]}), encoding="utf-8"
    )
    with pytest.raises(ExtractionReadinessError, match="smoke subset"):
        validate_extraction_readiness(tmp_path)


def test_extraction_readiness_reports_blocked_run(tmp_path) -> None:
    (tmp_path / "extraction_blocked.json").write_text(json.dumps({"reason": "404 model unavailable"}))
    with pytest.raises(ExtractionReadinessError, match="404 model unavailable"):
        validate_extraction_readiness(tmp_path)


def test_structural_readiness_passes_with_valid_hierarchy(tmp_path) -> None:
    from src.pipeline.validation.extraction_readiness import validate_structural_readiness

    (tmp_path / "hierarchy.json").write_text(
        json.dumps({"document": {"id": "doc_1", "doc_type": "Law"}}), encoding="utf-8"
    )
    # Should pass without throwing and without needing Gate 2 artifacts
    validate_structural_readiness(tmp_path)


def test_structural_readiness_rejects_missing_hierarchy(tmp_path) -> None:
    from src.pipeline.validation.extraction_readiness import (
        StructuralReadinessError,
        validate_structural_readiness,
    )

    with pytest.raises(StructuralReadinessError, match="Missing hierarchy artifact"):
        validate_structural_readiness(tmp_path)


def test_structural_readiness_rejects_invalid_hierarchy(tmp_path) -> None:
    from src.pipeline.validation.extraction_readiness import (
        StructuralReadinessError,
        validate_structural_readiness,
    )

    (tmp_path / "hierarchy.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    with pytest.raises(StructuralReadinessError, match="missing valid document header"):
        validate_structural_readiness(tmp_path)

