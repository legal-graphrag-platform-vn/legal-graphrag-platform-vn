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
from src.generation.models import (
    AnswerBlock,
    AnswerParagraph,
    AnswerResponse,
    GroundedStatement,
)
from src.shared.retrieval_contract import (
    PlanType,
    ProcessingStatus,
    QueryProcessingResult,
    SubqueryDTO,
    SubqueryIntent,
)
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
        self.last_query: str | None = None

    async def retrieve_context(self, request):
        self.calls += 1
        self.last_query = request.query
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
            direct_answer=AnswerBlock(
                paragraphs=[
                    AnswerParagraph(
                        statements=[
                            GroundedStatement(
                                statement_id="statement-1",
                                text="Câu trả lời đã kiểm chứng.",
                                citation_ids=[unit.id],
                            )
                        ]
                    )
                ]
            ),
            sections=(),
            caveats=(),
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


def _service(
    store, retrieval, generator, query_processor=None
) -> ConversationChatService:
    return ConversationChatService(
        store=store,
        resolver=FakeResolver(),
        rewriter=StructuredRewriter(llm=None),
        retrieval=retrieval,
        generator=generator,
        stream_chunk_chars=20,
        query_processor=query_processor,
    )


class FakeQueryProcessor:
    def __init__(self, result: QueryProcessingResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def process(self, current_query, conversation_history=()):
        self.calls.append(current_query)
        return self._result


def _ready_result(standalone: str) -> QueryProcessingResult:
    return QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query=standalone,
        plan_type=PlanType.SINGLE,
        subqueries=[
            SubqueryDTO(
                id="q1",
                query=standalone,
                intent=SubqueryIntent.DEFINITION,
                depends_on=[],
            )
        ],
        clarification_question=None,
    )


def _ready_multi_result(standalone: str) -> QueryProcessingResult:
    return QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query=standalone,
        plan_type=PlanType.PARALLEL,
        subqueries=[
            SubqueryDTO(
                id="q1",
                query="Công ty cổ phần là gì?",
                intent=SubqueryIntent.DEFINITION,
                depends_on=[],
            ),
            SubqueryDTO(
                id="q2",
                query="Công ty TNHH là gì?",
                intent=SubqueryIntent.DEFINITION,
                depends_on=[],
            ),
        ],
        clarification_question=None,
    )


def _clarification_result(question: str) -> QueryProcessingResult:
    return QueryProcessingResult(
        status=ProcessingStatus.NEEDS_CLARIFICATION,
        standalone_query=None,
        plan_type=None,
        subqueries=[],
        clarification_question=question,
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


def test_query_processor_ready_uses_standalone_query(db_url: str) -> None:
    owner = _owner()
    standalone = "Công ty cổ phần là gì theo Luật Doanh nghiệp 2020?"
    processor = FakeQueryProcessor(_ready_result(standalone))
    request = ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message="cái đó là gì",
    )

    async def _run() -> tuple[int, str]:
        async with prepared_conversation_store(db_url) as store:
            retrieval = CountingRetrieval()
            generator = CountingGenerator()
            service = _service(store, retrieval, generator, query_processor=processor)
            await _collect(service, request, owner)
            return generator.calls, retrieval.last_query

    generate_calls, retrieved_query = asyncio.run(_run())
    assert generate_calls == 1
    assert retrieved_query == standalone
    assert processor.calls == ["cái đó là gì"]


def test_query_processor_fans_out_subqueries(db_url: str) -> None:
    owner = _owner()
    processor = FakeQueryProcessor(_ready_multi_result("so sánh cổ phần và TNHH"))
    request = ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message="so sánh hai loại đó",
    )

    async def _run() -> tuple[int, int]:
        async with prepared_conversation_store(db_url) as store:
            retrieval = CountingRetrieval()
            generator = CountingGenerator()
            service = _service(store, retrieval, generator, query_processor=processor)
            await _collect(service, request, owner)
            return retrieval.calls, generator.calls

    retrieval_calls, generate_calls = asyncio.run(_run())
    assert retrieval_calls == 2  # one retrieval per subquery
    assert generate_calls == 1  # a single merged generation


def test_query_processor_needs_clarification_skips_retrieval(db_url: str) -> None:
    owner = _owner()
    processor = FakeQueryProcessor(
        _clarification_result("Bạn hỏi về loại hình doanh nghiệp nào?")
    )
    request = ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message="so sánh hai loại đó",
    )

    async def _run() -> tuple[int, int, list[str]]:
        async with prepared_conversation_store(db_url) as store:
            retrieval = CountingRetrieval()
            generator = CountingGenerator()
            service = _service(store, retrieval, generator, query_processor=processor)
            events = await _collect(service, request, owner)
            return retrieval.calls, generator.calls, [e.event for e in events]

    retrieval_calls, generate_calls, event_names = asyncio.run(_run())
    assert retrieval_calls == 0
    assert generate_calls == 0
    assert any("clarification" in name for name in event_names)
