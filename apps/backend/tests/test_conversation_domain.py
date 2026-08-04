"""Unit tests for conversation domain value objects (Plan 19 §4)."""

from __future__ import annotations

import uuid

import pytest

from persistence.domain import (
    MAX_CLARIFICATION_CANDIDATES,
    ClarificationCandidate,
    candidates_from_json,
    candidates_to_json,
    validate_candidates,
)
from persistence.errors import InvalidClarificationCandidatesError
from persistence.lock import conversation_lock_key


def _candidate(candidate_id: str, label: str = "Luật A") -> ClarificationCandidate:
    return ClarificationCandidate(candidate_id=candidate_id, label=label)


def test_candidate_round_trips_through_json() -> None:
    candidate = ClarificationCandidate(
        candidate_id="unit-1",
        label="Điều 1 Luật A",
        node_type="Article",
        document_id="doc-1",
        article_id="art-1",
        metadata={"note": "cổ phần"},
    )
    restored = ClarificationCandidate.from_json(candidate.to_json())
    assert restored == candidate


def test_optional_fields_are_omitted_when_absent() -> None:
    payload = _candidate("unit-1").to_json()
    assert payload == {"candidate_id": "unit-1", "label": "Luật A"}


def test_candidates_to_json_and_back_preserves_order() -> None:
    candidates = tuple(_candidate(f"unit-{index}") for index in range(3))
    restored = candidates_from_json(candidates_to_json(candidates))
    assert restored == candidates


def test_empty_candidates_are_rejected() -> None:
    with pytest.raises(InvalidClarificationCandidatesError):
        validate_candidates(())


def test_more_than_five_candidates_are_rejected() -> None:
    candidates = tuple(
        _candidate(f"unit-{index}") for index in range(MAX_CLARIFICATION_CANDIDATES + 1)
    )
    with pytest.raises(InvalidClarificationCandidatesError):
        validate_candidates(candidates)


def test_duplicate_candidate_ids_are_rejected() -> None:
    with pytest.raises(InvalidClarificationCandidatesError):
        validate_candidates((_candidate("dup"), _candidate("dup", label="Luật B")))


def test_from_json_rejects_blank_candidate_id() -> None:
    with pytest.raises(InvalidClarificationCandidatesError):
        ClarificationCandidate.from_json({"candidate_id": "  ", "label": "x"})


def test_candidates_from_json_rejects_non_array() -> None:
    with pytest.raises(InvalidClarificationCandidatesError):
        candidates_from_json({"candidate_id": "unit-1", "label": "x"})


def test_lock_key_is_deterministic_and_signed_64_bit() -> None:
    conversation_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    key = conversation_lock_key(conversation_id)
    assert key == conversation_lock_key(conversation_id)
    assert -(2**63) <= key < 2**63


def test_lock_key_differs_between_conversations() -> None:
    first = conversation_lock_key(uuid.uuid4())
    second = conversation_lock_key(uuid.uuid4())
    assert first != second
