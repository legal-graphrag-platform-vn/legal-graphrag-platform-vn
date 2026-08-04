"""Schema-level integrity checks for the conversation store (Plan 19 §3).

Marked ``conversation_db``; requires CONVERSATION_TEST_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from persistence.enums import (
    ClarificationMode,
    MessageKind,
    MessageRole,
    OwnerKind,
    TurnStatus,
)
from persistence.models import (
    Conversation,
    ConversationMessage,
    ConversationTurn,
    GroundedFocus,
    MessageCitation,
    PendingClarification,
)
from tests.conversation.conftest import (
    build_test_engine,
    prepared_store,
    reset_schema,
)

pytestmark = pytest.mark.conversation_db

BACKEND_DIR = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "conversations",
    "conversation_turns",
    "conversation_messages",
    "message_citations",
    "grounded_focuses",
    "pending_clarifications",
}


def _new_conversation() -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        owner_kind=OwnerKind.ANONYMOUS,
        owner_principal_id=uuid.uuid4(),
        next_user_turn_no=1,
    )


def _new_turn(
    conversation_id: uuid.UUID, *, user_turn_no: int, client_turn_id
) -> ConversationTurn:
    return ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        client_turn_id=client_turn_id,
        user_turn_no=user_turn_no,
        status=TurnStatus.PROCESSING,
    )


# --------------------------------------------------------------------------- #
# Migration                                                                    #
# --------------------------------------------------------------------------- #


def test_migration_creates_six_tables(db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)

    async def _reset() -> None:
        engine = build_test_engine(db_url)
        try:
            await reset_schema(engine)
        finally:
            await engine.dispose()

    async def _table_names() -> set[str]:
        engine = build_test_engine(db_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync: set(inspect(sync).get_table_names())
                )
        finally:
            await engine.dispose()

    asyncio.run(_reset())
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")

    tables = asyncio.run(_table_names())
    assert EXPECTED_TABLES.issubset(tables)
    assert "alembic_version" in tables


# --------------------------------------------------------------------------- #
# Uniqueness constraints                                                       #
# --------------------------------------------------------------------------- #


def test_duplicate_client_turn_id_is_rejected(db_url: str) -> None:
    conversation = _new_conversation()
    client_turn_id = uuid.uuid4()

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add(conversation)
                session.add(
                    _new_turn(
                        conversation.id, user_turn_no=1, client_turn_id=client_turn_id
                    )
                )
                await session.commit()
            async with sessionmaker() as session:
                session.add(
                    _new_turn(
                        conversation.id, user_turn_no=2, client_turn_id=client_turn_id
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()

    asyncio.run(_run())


def test_duplicate_user_turn_no_is_rejected(db_url: str) -> None:
    conversation = _new_conversation()

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add(conversation)
                session.add(
                    _new_turn(
                        conversation.id, user_turn_no=1, client_turn_id=uuid.uuid4()
                    )
                )
                await session.commit()
            async with sessionmaker() as session:
                session.add(
                    _new_turn(
                        conversation.id, user_turn_no=1, client_turn_id=uuid.uuid4()
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.commit()

    asyncio.run(_run())


def test_pending_clarification_unique_per_conversation(db_url: str) -> None:
    conversation = _new_conversation()
    turn = _new_turn(conversation.id, user_turn_no=1, client_turn_id=uuid.uuid4())

    def _pending() -> PendingClarification:
        return PendingClarification(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            source_turn_id=turn.id,
            mode=ClarificationMode.SELECT,
            question="Bạn muốn hỏi văn bản nào?",
            candidates=[{"id": "doc-1", "label": "Luật A"}],
        )

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add_all([conversation, turn])
                await session.flush()
                session.add(_pending())
                await session.commit()
            async with sessionmaker() as session:
                session.add(_pending())
                with pytest.raises(IntegrityError):
                    await session.commit()

    asyncio.run(_run())


def test_message_citation_unique_message_unit(db_url: str) -> None:
    conversation = _new_conversation()
    turn = _new_turn(conversation.id, user_turn_no=1, client_turn_id=uuid.uuid4())
    message = ConversationMessage(
        id=uuid.uuid4(),
        turn_id=turn.id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        kind=MessageKind.ANSWER,
        content="Trả lời",
        ordinal=2,
    )

    def _citation() -> MessageCitation:
        return MessageCitation(
            id=uuid.uuid4(),
            message_id=message.id,
            conversation_id=conversation.id,
            unit_id="unit-1",
            citation_ordinal=1,
            citation_label="Điều 1",
            document_id="doc-1",
            deep_link="/explorer?document=doc-1",
        )

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add_all([conversation, turn])
                await session.flush()
                session.add(message)
                await session.flush()
                session.add(_citation())
                await session.commit()
            async with sessionmaker() as session:
                session.add(_citation())
                with pytest.raises(IntegrityError):
                    await session.commit()

    asyncio.run(_run())


def test_grounded_focus_unique_conversation_node(db_url: str) -> None:
    conversation = _new_conversation()

    def _focus() -> GroundedFocus:
        return GroundedFocus(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            node_id="node-1",
            node_type="Article",
            canonical_label="Điều 1",
            document_id="doc-1",
            last_grounded_user_turn_no=1,
            citation_order=1,
        )

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add_all([conversation, _focus()])
                await session.commit()
            async with sessionmaker() as session:
                session.add(_focus())
                with pytest.raises(IntegrityError):
                    await session.commit()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Enum CHECK and JSONB                                                          #
# --------------------------------------------------------------------------- #


def test_invalid_turn_status_is_rejected_by_check(db_url: str) -> None:
    conversation = _new_conversation()

    async def _run() -> None:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add(conversation)
                await session.commit()
            async with sessionmaker() as session:
                with pytest.raises(DBAPIError):
                    await session.execute(
                        text(
                            "INSERT INTO conversation_turns "
                            "(id, conversation_id, client_turn_id, user_turn_no, status) "
                            "VALUES (:id, :cid, :ctid, 1, 'BOGUS')"
                        ),
                        {
                            "id": uuid.uuid4(),
                            "cid": conversation.id,
                            "ctid": uuid.uuid4(),
                        },
                    )
                    await session.commit()

    asyncio.run(_run())


def test_jsonb_snapshot_and_candidates_round_trip(db_url: str) -> None:
    conversation = _new_conversation()
    snapshot = {
        "status": "completed",
        "citations": [{"unit_id": "u1", "label": "Điều 1"}],
        "unicode": "Điều 111 – cổ phần",
    }
    turn = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        client_turn_id=uuid.uuid4(),
        user_turn_no=1,
        status=TurnStatus.COMPLETED,
        standalone_query="công ty cổ phần là gì",
        response_snapshot=snapshot,
    )
    candidates = [
        {"id": "doc-1", "label": "Luật A"},
        {"id": "doc-2", "label": "Luật B"},
    ]
    pending = PendingClarification(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        source_turn_id=turn.id,
        mode=ClarificationMode.SELECT,
        question="Chọn văn bản?",
        candidates=candidates,
    )

    async def _run() -> dict:
        async with prepared_store(db_url) as sessionmaker:
            async with sessionmaker() as session:
                session.add_all([conversation, turn])
                await session.flush()
                session.add(pending)
                await session.commit()
            async with sessionmaker() as session:
                stored_turn = await session.get(ConversationTurn, turn.id)
                stored_pending = await session.get(PendingClarification, pending.id)
                return {
                    "snapshot": stored_turn.response_snapshot,
                    "candidates": stored_pending.candidates,
                }

    result = asyncio.run(_run())
    assert result["snapshot"] == snapshot
    assert result["candidates"] == candidates
