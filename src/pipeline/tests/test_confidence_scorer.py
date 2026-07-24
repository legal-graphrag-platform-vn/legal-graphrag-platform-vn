from src.pipeline.scoring.confidence_scorer import (
    WEIGHTS,
    score,
    score_entities_resolvable,
    score_evidence_presence,
)


def test_weights_sum_to_one() -> None:
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_evidence_exact_match() -> None:
    assert score_evidence_presence("Doanh nghiệp phải có vốn điều lệ.", "abc Doanh nghiệp phải có vốn điều lệ. xyz") == 1.0


def test_evidence_no_match() -> None:
    assert score_evidence_presence("câu không liên quan gì cả", "Điều 1. Phạm vi điều chỉnh.") == 0.0


def test_evidence_empty() -> None:
    assert score_evidence_presence("", "some text") == 0.0
    assert score_evidence_presence("text", "") == 0.0


def test_entities_resolvable_full() -> None:
    assert score_entities_resolvable(["a", "b"], {"a", "b", "c"}) == 1.0


def test_entities_resolvable_partial() -> None:
    assert score_entities_resolvable(["a", "x"], {"a", "b"}) == 0.5


def test_score_auto_accept_threshold() -> None:
    breakdown = score(
        schema_valid=True,
        ontology_valid=True,
        evidence="Doanh nghiệp phải có vốn điều lệ",
        article_text="...Doanh nghiệp phải có vốn điều lệ theo quy định...",
        head_id="doanh_nghiep",
        tail_id="von_dieu_le",
        known_entity_ids={"doanh_nghiep", "von_dieu_le"},
    )
    assert breakdown.total >= 0.7


def test_score_reject_when_schema_and_ontology_invalid() -> None:
    breakdown = score(
        schema_valid=False,
        ontology_valid=False,
        evidence="",
        article_text="",
        head_id="x",
        tail_id="y",
        known_entity_ids=set(),
    )
    assert breakdown.total < 0.3


def test_schema_score_calculation_with_deepdiff() -> None:
    from src.pipeline.validation.schema_validator import score_relation_schema

    # Perfect schema match
    perfect = {
        "head": "ldn_2020_art1",
        "relation": "REGULATES",
        "tail": "thanh_lap",
        "evidence": "Luật này quy định...",
        "confidence": 0.95,
    }
    assert score_relation_schema(perfect) == 1.0

    # Missing evidence field (minus 0.3)
    missing_evidence = {
        "head": "ldn_2020_art1",
        "relation": "REGULATES",
        "tail": "thanh_lap",
        "confidence": 0.95,
    }
    assert abs(score_relation_schema(missing_evidence) - 0.7) < 1e-9

    # Extra field (minus 0.05) and type change on confidence (minus 0.2)
    extra_and_type_change = {
        "head": "ldn_2020_art1",
        "relation": "REGULATES",
        "tail": "thanh_lap",
        "evidence": "evidence text",
        "confidence": "high",  # string instead of float -> type change
        "extra_field": "some data",  # extra field
    }
    # Expected penalty: type_change (0.2) + extra_key (0.05) = 0.25 -> Score: 0.75
    assert abs(score_relation_schema(extra_and_type_change) - 0.75) < 1e-9

    # Invalid relation literal (minus 0.2)
    invalid_relation = {
        "head": "ldn_2020_art1",
        "relation": "INVALID_RELATION",
        "tail": "thanh_lap",
        "evidence": "Luật này quy định...",
        "confidence": 0.95,
    }
    assert abs(score_relation_schema(invalid_relation) - 0.8) < 1e-9
