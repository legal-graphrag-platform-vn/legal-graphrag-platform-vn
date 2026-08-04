"""Tests for the conversation request contract and snapshot SSE (Plan 19 §4)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from api.models import (
    ChatCitationData,
    ChatClarificationData,
    ChatDoneData,
    ChatMetadataData,
    ConversationChatRequest,
)
from conversation.snapshot import (
    KIND_ANSWER,
    answer_snapshot,
    clarification_snapshot,
    error_snapshot,
    processing_snapshot,
    stream_from_snapshot,
)


def _metadata(**overrides) -> ChatMetadataData:
    base = dict(
        sources=[],
        intent="factual",
        strategy="factual_hybrid",
        retrieval_mode="graph",
        retrieval_contract_version="retrieval-runtime-v2",
        answer_contract_version="answer-generation-v1",
        cannot_answer=False,
    )
    base.update(overrides)
    return ChatMetadataData(**base)


# --------------------------------------------------------------------------- #
# Request contract                                                             #
# --------------------------------------------------------------------------- #


def test_conversation_request_requires_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationChatRequest(message="Điều 111")


def test_conversation_request_rejects_legacy_history() -> None:
    with pytest.raises(ValidationError):
        ConversationChatRequest(
            conversation_id=uuid.uuid4(),
            client_turn_id=uuid.uuid4(),
            message="Điều 111",
            history=[{"role": "user", "content": "x"}],
        )


def test_conversation_request_normalizes_message_and_ids() -> None:
    request = ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message="  Điều 111  ",
        document_ids=[" doc-1 "],
    )
    assert request.message == "Điều 111"
    assert request.document_ids == ["doc-1"]


def test_conversation_request_rejects_duplicate_document_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationChatRequest(
            conversation_id=uuid.uuid4(),
            client_turn_id=uuid.uuid4(),
            message="x",
            document_ids=["doc-1", "doc-1"],
        )


# --------------------------------------------------------------------------- #
# Snapshot reconstruction                                                      #
# --------------------------------------------------------------------------- #


def _answer_snapshot() -> dict:
    citation = ChatCitationData(
        unit_id="u1",
        citation_label="Điều 111",
        document_id="doc-1",
        article_id="art-1",
        clause_id=None,
        deep_link="/explorer?document=doc-1",
    )
    return answer_snapshot(
        kind=KIND_ANSWER,
        metadata=_metadata(),
        answer_text="Công ty cổ phần là doanh nghiệp có vốn điều lệ.",
        citations=[citation],
        done=ChatDoneData(status="completed", citation_count=1, confidence=0.9),
    )


def test_answer_snapshot_reconstructs_ordered_events() -> None:
    events = stream_from_snapshot(_answer_snapshot(), chunk_chars=10)
    kinds = [event.event for event in events]
    assert kinds[0] == "metadata"
    assert "token" in kinds
    assert kinds.count("citation") == 1
    assert kinds[-1] == "done"
    reconstructed = "".join(
        event.data["content"] for event in events if event.event == "token"
    )
    assert reconstructed == "Công ty cổ phần là doanh nghiệp có vốn điều lệ."


def test_replay_parity_is_byte_identical() -> None:
    snapshot = _answer_snapshot()
    first = stream_from_snapshot(snapshot, chunk_chars=8)
    second = stream_from_snapshot(snapshot, chunk_chars=8)
    assert [(e.event, e.data) for e in first] == [(e.event, e.data) for e in second]


def test_clarification_snapshot_streams_clarification_event() -> None:
    snapshot = clarification_snapshot(
        metadata=_metadata(
            needs_clarification=True,
            resolution_status="AMBIGUOUS",
            strategy="clarification",
        ),
        clarification=ChatClarificationData(
            mode="SELECT",
            question="Ý bạn là văn bản nào? 1. Luật A 2. Luật B",
            candidates=[
                {"candidate_id": "doc-1", "label": "Luật A"},
                {"candidate_id": "doc-2", "label": "Luật B"},
            ],
        ),
        done=ChatDoneData(status="needs_clarification"),
    )
    events = stream_from_snapshot(snapshot, chunk_chars=100)
    kinds = [event.event for event in events]
    assert "clarification" in kinds
    assert kinds[-1] == "done"
    clarification_event = next(e for e in events if e.event == "clarification")
    assert clarification_event.data["mode"] == "SELECT"
    assert len(clarification_event.data["candidates"]) == 2
    done_event = events[-1]
    assert done_event.data["status"] == "needs_clarification"


def test_error_snapshot_streams_error_then_done() -> None:
    events = stream_from_snapshot(
        error_snapshot(code="REWRITE_TIMEOUT", message="Quá thời gian."),
        chunk_chars=10,
    )
    assert [event.event for event in events] == ["error", "done"]
    assert events[0].data["code"] == "REWRITE_TIMEOUT"
    assert events[1].data["status"] == "error"


def test_processing_snapshot_streams_processing_done() -> None:
    events = stream_from_snapshot(
        processing_snapshot(retry_after_ms=1000), chunk_chars=10
    )
    assert [event.event for event in events] == ["done"]
    assert events[0].data["status"] == "processing"
    assert events[0].data["retry_after_ms"] == 1000


def test_unicode_is_preserved_in_tokens() -> None:
    snapshot = answer_snapshot(
        kind=KIND_ANSWER,
        metadata=_metadata(),
        answer_text="Điều 111 – cổ phần ưu đãi",
        citations=[],
        done=ChatDoneData(status="completed"),
    )
    events = stream_from_snapshot(snapshot, chunk_chars=3)
    joined = "".join(e.data["content"] for e in events if e.event == "token")
    assert joined == "Điều 111 – cổ phần ưu đãi"
