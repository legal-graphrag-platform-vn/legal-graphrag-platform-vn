from src.scoring.confidence_scorer import (
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
