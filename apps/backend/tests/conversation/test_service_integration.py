"""Service + PostgreSQL store integration (Plan 19 §2, §4).

Marked ``conversation_db``; requires CONVERSATION_TEST_DATABASE_URL. Retrieval
and generation are faked; the store, lock, persistence and replay are real.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from api.models import ConversationChatRequest
from conversation.service import ConversationChatService
from persistence.domain import Owner
from persistence.enums import OwnerKind
from persistence.errors import ConversationNotFoundError
from resolution.models import StandaloneResolution
from resolution.rewriter import StructuredRewriter
from src.generation.models import AnswerResponse
from tests.conversation.conftest import prepared_conversation_store
from tests.factories import retrieval_context

pytestmark = pytest.mark.conversation_db


def _owner() -> Owner:
    return Owner(owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=uuid.uuid4())


class FakeResolver:
    async def resolve(self, *, message, context):
        return StandaloneResolution()


class CountingRetrieval:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve_context(self, request):
        self.calls += 1
        context = retrieval_context()
        context.query = request.query
        return context


class CountingGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request) -> AnswerResponse:
        self.calls += 1
        unit = request.retrieval_context.retrieved_units[0]
        return AnswerResponse(
            retrieval_contract_version=request.retrieval_context.contract_version,
            query=request.query,
            answer_text="Câu trả lời đã kiểm chứng.",
            claims=(),
            citations=(
                {
                    "unit_id": unit.id,
                    "citation_label": unit.citation_label,
                    "document_id": unit.document_id,
                    "article_id": unit.article_id,
                    "clause_id": unit.clause_id,
                    "deep_link": unit.deep_link,
                },
            ),
            reasoning_paths=(),
            temporal_notes=(),
            cannot_answer=False,
            insufficiency_reason=None,
            confidence=0.9,
            provider="fake",
            model="fake-model",
            intent=request.retrieval_context.intent.value,
            strategy=request.retrieval_context.strategy.value,
        )

    async def aclose(self) -> None:
        return None


def _service(store, retrieval, generator) -> ConversationChatService:
    return ConversationChatService(
        store=store,
        resolver=FakeResolver(),
        rewriter=StructuredRewriter(llm=None),
        retrieval=retrieval,
        generator=generator,
        stream_chunk_chars=20,
    )


async def _collect(service, request, owner):
    return [event async for event in service.stream_chat(request, owner)]


def test_same_client_turn_id_replays_without_second_generation(db_url: str) -> None:
    owner = _owner()
    request = ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message="công ty cổ phần là gì",
    )

    async def _run() -> tuple[int, bool]:
        async with prepared_conversation_store(db_url) as store:
            retrieval = CountingRetrieval()
            generator = CountingGenerator()
            service = _service(store, retrieval, generator)
            first = await _collect(service, request, owner)
            second = await _collect(service, request, owner)
            same = [(e.event, e.data) for e in first] == [
                (e.event, e.data) for e in second
            ]
            return generator.calls, same

    generate_calls, replay_identical = asyncio.run(_run())
    assert generate_calls == 1
    assert replay_identical is True


def test_cross_owner_conversation_is_not_found(db_url: str) -> None:
    conversation_id = uuid.uuid4()
    owner_a = _owner()
    owner_b = _owner()

    async def _run() -> None:
        async with prepared_conversation_store(db_url) as store:
            service = _service(store, CountingRetrieval(), CountingGenerator())
            await _collect(
                service,
                ConversationChatRequest(
                    conversation_id=conversation_id,
                    client_turn_id=uuid.uuid4(),
                    message="câu hỏi",
                ),
                owner_a,
            )
            with pytest.raises(ConversationNotFoundError):
                await _collect(
                    service,
                    ConversationChatRequest(
                        conversation_id=conversation_id,
                        client_turn_id=uuid.uuid4(),
                        message="câu hỏi khác",
                    ),
                    owner_b,
                )

    asyncio.run(_run())


def test_second_distinct_turn_persists_and_replays(db_url: str) -> None:
    owner = _owner()
    conversation_id = uuid.uuid4()

    async def _run() -> int:
        async with prepared_conversation_store(db_url) as store:
            retrieval = CountingRetrieval()
            generator = CountingGenerator()
            service = _service(store, retrieval, generator)
            await _collect(
                service,
                ConversationChatRequest(
                    conversation_id=conversation_id,
                    client_turn_id=uuid.uuid4(),
                    message="câu 1",
                ),
                owner,
            )
            await _collect(
                service,
                ConversationChatRequest(
                    conversation_id=conversation_id,
                    client_turn_id=uuid.uuid4(),
                    message="câu 2",
                ),
                owner,
            )
            return generator.calls

    assert asyncio.run(_run()) == 2
