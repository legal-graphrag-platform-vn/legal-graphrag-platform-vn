"""Integration tests for the conversation repository (Plan 19 §3-§4).

Marked ``conversation_db``; requires CONVERSATION_TEST_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from persistence.domain import (
    CitationSnapshot,
    ClarificationCandidate,
    Owner,
)
from persistence.enums import (
    ClarificationMode,
    MessageKind,
    OwnerKind,
    ResolutionStatus,
    TurnStatus,
)
from persistence.errors import (
    ConversationBusyError,
    ConversationNotFoundError,
    TurnSnapshotError,
)
from persistence.repository import (
    MAX_GROUNDED_FOCUSES,
    SqlAlchemyConversationStore,
    focus_upserts_from_citations,
)
from tests.conversation.conftest import prepared_conversation_store

pytestmark = pytest.mark.conversation_db


def _owner() -> Owner:
    return Owner(owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=uuid.uuid4())


def _citation(
    unit_id: str,
    *,
    ordinal: int = 1,
    label: str | None = None,
    document_id: str = "doc-1",
    article_id: str | None = "art-1",
    clause_id: str | None = None,
) -> CitationSnapshot:
    return CitationSnapshot(
        unit_id=unit_id,
        citation_ordinal=ordinal,
        citation_label=label or f"Điều {ordinal}",
        document_id=document_id,
        deep_link=f"/explorer?document={document_id}",
        article_id=article_id,
        clause_id=clause_id,
    )


async def _answer(
    store: SqlAlchemyConversationStore,
    conversation_id: uuid.UUID,
    owner: Owner,
    *,
    message: str,
    citations: tuple[CitationSnapshot, ...],
    update_focus: bool = True,
    status: TurnStatus = TurnStatus.COMPLETED,
    kind: MessageKind = MessageKind.ANSWER,
) -> None:
    async with store.locked_turn(conversation_id=conversation_id, owner=owner) as turn:
        begun = await turn.begin_turn_and_load_context(
            client_turn_id=uuid.uuid4(), user_message=message
        )
        await turn.persist_grounded_answer(
            turn_id=begun.turn_id,
            user_turn_no=begun.user_turn_no,
            status=status,
            kind=kind,
            content="Trả lời: " + message,
            standalone_query=message,
            resolution_status=ResolutionStatus.RESOLVED,
            resolution_reason_code=None,
            citations=citations,
            focus_upserts=focus_upserts_from_citations(citations),
            update_focus=update_focus,
            response_snapshot={"status": status.value, "message": message},
        )


# --------------------------------------------------------------------------- #
# Turn allocation and idempotency                                              #
# --------------------------------------------------------------------------- #


def test_begin_turn_creates_conversation_and_allocates_first_turn(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    client_turn_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=client_turn_id, user_message="Điều 111 nói gì?"
                )
            assert begun.user_turn_no == 1
            assert begun.user_message_ordinal == 1
            assert begun.context.recent_messages == ()
            assert begun.context.grounded_focuses == ()
            assert begun.context.pending_clarification is None

            record = await store.find_turn_by_client_id(
                conversation_id=conversation_id,
                owner=owner,
                client_turn_id=client_turn_id,
            )
            assert record is not None
            assert record.status is TurnStatus.PROCESSING
            assert record.user_turn_no == 1

    asyncio.run(_run())


def test_second_turn_increments_user_turn_no(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> tuple[int, int]:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="câu 1",
                citations=(_citation("u1"),),
            )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="câu 2"
                )
                return begun.user_turn_no, len(begun.context.recent_messages)

    user_turn_no, recent_count = asyncio.run(_run())
    assert user_turn_no == 2
    # The completed turn contributed a user and an assistant message.
    assert recent_count == 2


def test_find_turn_returns_none_before_conversation_exists(db_url: str) -> None:
    owner = _owner()

    async def _run() -> object:
        async with prepared_conversation_store(db_url) as store:
            return await store.find_turn_by_client_id(
                conversation_id=uuid.uuid4(),
                owner=owner,
                client_turn_id=uuid.uuid4(),
            )

    assert asyncio.run(_run()) is None


# --------------------------------------------------------------------------- #
# Owner scoping                                                                 #
# --------------------------------------------------------------------------- #


def test_cross_owner_access_is_reported_as_not_found(db_url: str) -> None:
    owner = _owner()
    intruder = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="câu 1",
                citations=(_citation("u1"),),
            )
            with pytest.raises(ConversationNotFoundError):
                await store.find_turn_by_client_id(
                    conversation_id=conversation_id,
                    owner=intruder,
                    client_turn_id=uuid.uuid4(),
                )

    asyncio.run(_run())


def test_begin_turn_rejects_foreign_owner(db_url: str) -> None:
    owner = _owner()
    intruder = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="câu 1",
                citations=(_citation("u1"),),
            )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=intruder
            ) as turn:
                with pytest.raises(ConversationNotFoundError):
                    await turn.begin_turn_and_load_context(
                        client_turn_id=uuid.uuid4(), user_message="xin chào"
                    )

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Grounded answer, focus policy                                                 #
# --------------------------------------------------------------------------- #


def test_completed_answer_upserts_focus_visible_next_turn(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> tuple[str, ...]:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="Điều 111",
                citations=(_citation("u1", label="Điều 111"),),
            )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="khoản đó?"
                )
                return tuple(focus.node_id for focus in begun.context.grounded_focuses)

    node_ids = asyncio.run(_run())
    assert node_ids == ("art-1",)


def test_cannot_answer_does_not_update_focus(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> int:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="câu hỏi mơ hồ",
                citations=(_citation("u1"),),
                update_focus=False,
                status=TurnStatus.CANNOT_ANSWER,
                kind=MessageKind.CANNOT_ANSWER,
            )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="tiếp"
                )
                return len(begun.context.grounded_focuses)

    assert asyncio.run(_run()) == 0


def test_focus_expires_after_ttl(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> int:
        async with prepared_conversation_store(db_url) as store:
            # Turn 1 grounds a focus.
            await _answer(
                store,
                conversation_id,
                owner,
                message="Điều 111",
                citations=(_citation("u1"),),
            )
            # Advance far enough that the focus is older than the TTL window.
            for index in range(6):
                await _answer(
                    store,
                    conversation_id,
                    owner,
                    message=f"nối tiếp {index}",
                    citations=(),
                    update_focus=False,
                )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="cuối"
                )
                return len(begun.context.grounded_focuses)

    assert asyncio.run(_run()) == 0


def test_focus_set_is_capped_at_five(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    citations = tuple(
        _citation(f"u{i}", ordinal=i, article_id=f"art-{i}") for i in range(1, 8)
    )

    async def _run() -> int:
        async with prepared_conversation_store(db_url) as store:
            await _answer(
                store,
                conversation_id,
                owner,
                message="nhiều điều",
                citations=citations,
            )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="tiếp"
                )
                return len(begun.context.grounded_focuses)

    assert asyncio.run(_run()) == MAX_GROUNDED_FOCUSES


# --------------------------------------------------------------------------- #
# Clarification and pending                                                     #
# --------------------------------------------------------------------------- #


def test_clarification_persists_pending_without_focus(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    candidates = (
        ClarificationCandidate(candidate_id="doc-1", label="Luật A"),
        ClarificationCandidate(candidate_id="doc-2", label="Luật B"),
    )

    async def _run() -> tuple:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="văn bản nào?"
                )
                await turn.persist_clarification(
                    turn_id=begun.turn_id,
                    mode=ClarificationMode.SELECT,
                    question="Bạn muốn hỏi văn bản nào?",
                    candidates=candidates,
                    resolution_status=ResolutionStatus.AMBIGUOUS,
                    resolution_reason_code="MULTIPLE_MATCHES",
                    response_snapshot={"status": "needs_clarification"},
                )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="1"
                )
                pending = begun.context.pending_clarification
                return (
                    pending.mode if pending else None,
                    tuple(c.candidate_id for c in pending.candidates)
                    if pending
                    else (),
                    len(begun.context.grounded_focuses),
                )

    mode, candidate_ids, focus_count = asyncio.run(_run())
    assert mode is ClarificationMode.SELECT
    assert candidate_ids == ("doc-1", "doc-2")
    assert focus_count == 0


def test_clear_pending_removes_clarification(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> object:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="văn bản nào?"
                )
                await turn.persist_clarification(
                    turn_id=begun.turn_id,
                    mode=ClarificationMode.SELECT,
                    question="Chọn?",
                    candidates=(
                        ClarificationCandidate(candidate_id="doc-1", label="Luật A"),
                    ),
                    resolution_status=ResolutionStatus.AMBIGUOUS,
                    resolution_reason_code=None,
                    response_snapshot={"status": "needs_clarification"},
                )
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                await turn.clear_pending()
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=uuid.uuid4(), user_message="hủy"
                )
                return begun.context.pending_clarification

    assert asyncio.run(_run()) is None


# --------------------------------------------------------------------------- #
# Failure and replay                                                            #
# --------------------------------------------------------------------------- #


def test_mark_turn_failed_records_error_and_snapshot(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    client_turn_id = uuid.uuid4()

    async def _run() -> tuple:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=client_turn_id, user_message="câu hỏi"
                )
                await turn.mark_turn_failed(
                    turn_id=begun.turn_id,
                    error_code="REWRITE_FAILED",
                    response_snapshot={"status": "error", "code": "REWRITE_FAILED"},
                )
            record = await store.find_turn_by_client_id(
                conversation_id=conversation_id,
                owner=owner,
                client_turn_id=client_turn_id,
            )
            return record.status, record.error_code

    status, error_code = asyncio.run(_run())
    assert status is TurnStatus.FAILED
    assert error_code == "REWRITE_FAILED"


def test_replay_turn_returns_snapshot(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    client_turn_id = uuid.uuid4()

    async def _run() -> dict:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                begun = await turn.begin_turn_and_load_context(
                    client_turn_id=client_turn_id, user_message="Điều 111"
                )
                await turn.persist_grounded_answer(
                    turn_id=begun.turn_id,
                    user_turn_no=begun.user_turn_no,
                    status=TurnStatus.COMPLETED,
                    kind=MessageKind.ANSWER,
                    content="Trả lời",
                    standalone_query="Điều 111",
                    resolution_status=ResolutionStatus.RESOLVED,
                    resolution_reason_code=None,
                    citations=(_citation("u1"),),
                    focus_upserts=focus_upserts_from_citations((_citation("u1"),)),
                    update_focus=True,
                    response_snapshot={"status": "completed", "answer": "Trả lời"},
                )
            return await store.replay_turn(
                conversation_id=conversation_id,
                owner=owner,
                client_turn_id=client_turn_id,
            )

    snapshot = asyncio.run(_run())
    assert snapshot == {"status": "completed", "answer": "Trả lời"}


def test_replay_turn_without_snapshot_raises(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()
    client_turn_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_conversation_store(db_url) as store:
            async with store.locked_turn(
                conversation_id=conversation_id, owner=owner
            ) as turn:
                await turn.begin_turn_and_load_context(
                    client_turn_id=client_turn_id, user_message="câu hỏi"
                )
            with pytest.raises(TurnSnapshotError):
                await store.replay_turn(
                    conversation_id=conversation_id,
                    owner=owner,
                    client_turn_id=client_turn_id,
                )

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Advisory locking                                                             #
# --------------------------------------------------------------------------- #


def test_same_conversation_second_lock_times_out(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_conversation_store(
            db_url, lock_timeout_seconds=0.2, lock_poll_interval_seconds=0.02
        ) as store:
            async with store.locked_turn(conversation_id=conversation_id, owner=owner):
                with pytest.raises(ConversationBusyError):
                    async with store.locked_turn(
                        conversation_id=conversation_id, owner=owner
                    ):
                        pass

    asyncio.run(_run())


def test_different_conversations_lock_concurrently(db_url: str) -> None:
    owner = _owner()
    first = uuid.uuid4()
    second = uuid.uuid4()

    async def _run() -> bool:
        async with prepared_conversation_store(
            db_url, lock_timeout_seconds=0.2
        ) as store:
            async with store.locked_turn(conversation_id=first, owner=owner):
                async with store.locked_turn(conversation_id=second, owner=owner):
                    return True
        return False

    assert asyncio.run(_run()) is True


def test_lock_is_released_after_turn(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> bool:
        async with prepared_conversation_store(
            db_url, lock_timeout_seconds=0.2
        ) as store:
            async with store.locked_turn(conversation_id=conversation_id, owner=owner):
                pass
            # Re-acquiring the same conversation must now succeed.
            async with store.locked_turn(conversation_id=conversation_id, owner=owner):
                return True
        return False

    assert asyncio.run(_run()) is True
