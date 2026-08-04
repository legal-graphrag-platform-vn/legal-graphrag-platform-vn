import pytest

from src.retrieval.planning.patterns import validate_directed_step


@pytest.mark.parametrize(
    ("current_label", "relation", "direction", "next_label"),
    [
        ("Clause", "REFERS_TO", "outgoing", "Article"),
        ("Clause", "CONTAINS", "incoming", "Article"),
        ("LegalConcept", "DEFINES", "incoming", "Article"),
        ("Document", "AMENDS", "outgoing", "Clause"),
    ],
)
def test_validate_directed_step_accepts_canonical_ontology_patterns(
    current_label: str,
    relation: str,
    direction: str,
    next_label: str,
) -> None:
    assert validate_directed_step(
        current_label=current_label,
        relation=relation,
        direction=direction,
        next_label=next_label,
    )


@pytest.mark.parametrize(
    ("current_label", "relation", "direction", "next_label", "message"),
    [
        ("Article", "REFERENCES", "outgoing", "Clause", "legacy relation alias"),
        ("Article", "HAS_EXCEPTION", "outgoing", "Exception", "Runtime-only"),
        ("Article", "CONTAINS", "incoming", "Clause", "does not allow"),
        ("Article", "REFERS_TO", "sideways", "Clause", "direction"),
        ("Article", "UNKNOWN", "outgoing", "Clause", "not query-plannable"),
    ],
)
def test_validate_directed_step_rejects_invalid_patterns(
    current_label: str,
    relation: str,
    direction: str,
    next_label: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_directed_step(
            current_label=current_label,
            relation=relation,
            direction=direction,
            next_label=next_label,
        )
