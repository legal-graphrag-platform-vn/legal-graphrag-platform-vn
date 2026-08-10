"""PostgreSQL-backed integration tests for Plan 20 auth & history repository ops.

Marked ``conversation_db``; requires CONVERSATION_TEST_DATABASE_URL. Exercises
user/account creation, guest claiming, owner isolation and conversation CRUD
directly against ``SqlAlchemyConversationStore``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from auth.password import hash_password, verify_password
from persistence.domain import Owner
from persistence.enums import MessageKind, OwnerKind, ResolutionStatus, TurnStatus
from persistence.repository import SqlAlchemyConversationStore
from tests.conversation.conftest import prepared_conversation_store

pytestmark = pytest.mark.conversation_db


def _user_owner(user_id: uuid.UUID) -> Owner:
    return Owner(owner_kind=OwnerKind.USER, owner_principal_id=user_id)


def _anon_owner() -> Owner:
    return Owner(owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=uuid.uuid4())


async def _seed_conversation(
    store: SqlAlchemyConversationStore,
    owner: Owner,
    *,
    message: str = "Điều 3 Luật Đất đai quy định gì?",
) -> uuid.UUID:
    """Create a conversation with one completed answer turn, return its id."""
    conversation_id = uuid.uuid4()
    async with store.locked_turn(conversation_id=conversation_id, owner=owner) as turn:
        begun = await turn.begin_turn_and_load_context(
            client_turn_id=uuid.uuid4(), user_message=message
        )
        answer_text = "Trả lời: " + message
        await turn.persist_grounded_answer(
            turn_id=begun.turn_id,
            user_turn_no=begun.user_turn_no,
            status=TurnStatus.COMPLETED,
            kind=MessageKind.ANSWER,
            content=answer_text,
            standalone_query=message,
            resolution_status=ResolutionStatus.RESOLVED,
            resolution_reason_code=None,
            citations=(),
            focus_upserts=(),
            update_focus=False,
            response_snapshot={
                "kind": "answer",
                "metadata": None,
                "answer_text": answer_text,
                "answer": {"markdown": answer_text},
                "citations": [],
                "explanation": {"temporal_notes": [], "reasoning_paths": []},
                "done": {"status": "completed", "citation_count": 0},
            },
        )
    return conversation_id


def test_create_user_with_account_and_lookup(db_url: str) -> None:
    async def scenario() -> None:
        async with prepared_conversation_store(db_url) as store:
            user, account = await store.create_user_with_account(
                username="Alice",
                password_hash=hash_password("secret123"),
                full_name="Alice Nguyen",
            )
            # 1. Username is normalised to lower-case.
            assert account["username"] == "alice"

            # 2. Lookup by any case returns the account with its user_id.
            fetched = await store.get_account_by_username("ALICE")
            assert fetched is not None
            assert fetched["user_id"] == user["id"]
            assert verify_password("secret123", fetched["password_hash"])

            # 3. Profile lookup resolves the same user with its username.
            profile = await store.get_user_by_id(user["id"])
            assert profile is not None
            assert profile["full_name"] == "Alice Nguyen"
            assert profile["username"] == "alice"

            # 4. Unknown username returns None.
            assert await store.get_account_by_username("bob") is None

    asyncio.run(scenario())


def test_claim_guest_conversations_transfers_ownership(db_url: str) -> None:
    async def scenario() -> None:
        async with prepared_conversation_store(db_url) as store:
            user, _ = await store.create_user_with_account(
                username="carol", password_hash=hash_password("pw123456")
            )
            anon = _anon_owner()
            conv_a = await _seed_conversation(store, anon, message="Câu hỏi một")
            conv_b = await _seed_conversation(store, anon, message="Câu hỏi hai")

            # 1. Claim moves both anon conversations to the user.
            claimed = await store.claim_guest_conversations(
                anon_principal_id=anon.owner_principal_id, user_id=user["id"]
            )
            assert claimed == 2

            # 2. User now sees both; anon sees none.
            user_owner = _user_owner(user["id"])
            user_convs = await store.list_conversations(owner=user_owner)
            assert {c["id"] for c in user_convs} == {str(conv_a), str(conv_b)}
            assert await store.list_conversations(owner=anon) == []

    asyncio.run(scenario())


def test_owner_isolation_hides_other_owners_conversation(db_url: str) -> None:
    async def scenario() -> None:
        async with prepared_conversation_store(db_url) as store:
            owner_a = _user_owner(uuid.uuid4())
            owner_b = _user_owner(uuid.uuid4())
            conv = await _seed_conversation(store, owner_a)

            # 1. Owner B cannot read, rename or delete owner A's conversation.
            assert await store.get_conversation_detail(conv, owner_b) is None
            assert await store.patch_conversation_title(conv, owner_b, "Hack") is False
            assert await store.delete_conversation(conv, owner_b) is False
            assert await store.list_conversations(owner=owner_b) == []

            # 2. Owner A retains full access.
            detail = await store.get_conversation_detail(conv, owner_a)
            assert detail is not None
            assert len(detail["messages"]) == 2

    asyncio.run(scenario())


def test_conversation_crud_and_soft_delete(db_url: str) -> None:
    async def scenario() -> None:
        async with prepared_conversation_store(db_url) as store:
            owner = _user_owner(uuid.uuid4())
            conv = await _seed_conversation(store, owner)

            # 1. Rename succeeds and is reflected in detail.
            assert await store.patch_conversation_title(conv, owner, "  Tên mới  ")
            detail = await store.get_conversation_detail(conv, owner)
            assert detail is not None
            assert detail["title"] == "Tên mới"

            # 2. Soft delete hides it from list and detail.
            assert await store.delete_conversation(conv, owner) is True
            assert await store.list_conversations(owner=owner) == []
            assert await store.get_conversation_detail(conv, owner) is None

            # 3. Deleting again is a no-op miss (already hidden).
            assert await store.delete_conversation(conv, owner) is True

    asyncio.run(scenario())


def test_generate_conversation_title(db_url: str) -> None:
    async def scenario() -> None:
        async with prepared_conversation_store(db_url) as store:
            owner = _user_owner(uuid.uuid4())
            long_message = (
                "Cho tôi biết chi tiết về các quy định xử phạt vi phạm hành chính "
                "trong lĩnh vực giao thông đường bộ"
            )
            conv = await _seed_conversation(store, owner, message=long_message)

            # 1. Title is derived from the first user message and persisted.
            title = await store.generate_conversation_title(conv, owner)
            assert title is not None
            assert len(title) <= 51
            detail = await store.get_conversation_detail(conv, owner)
            assert detail is not None
            assert detail["title"] == title

            # 2. Wrong owner cannot generate a title.
            assert (
                await store.generate_conversation_title(conv, _user_owner(uuid.uuid4()))
                is None
            )

            # 3. Missing conversation returns None.
            assert await store.generate_conversation_title(uuid.uuid4(), owner) is None

    asyncio.run(scenario())
