from __future__ import annotations

import asyncio

from api.models import ChatRequest
from services.graphrag_answer_service import GraphRAGAnswerService
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from tests.factories import retrieval_context


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve_context(self, request):
        self.calls += 1
        context = retrieval_context()
        context.query = request.query
        return context


class FakeGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.validated = False

    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        self.calls += 1
        self.validated = True
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


def test_answer_retrieves_and_generates_exactly_once() -> None:
    async def scenario() -> None:
        retrieval = FakeRetrieval()
        generator = FakeGenerator()
        service = GraphRAGAnswerService(
            retrieval=retrieval,
            generator=generator,
            stream_chunk_chars=10,
        )
        result = await service.answer(ChatRequest(message="Câu hỏi độc lập"))
        assert result.answer.answer_text == "Câu trả lời đã kiểm chứng."
        assert retrieval.calls == 1
        assert generator.calls == 1

    asyncio.run(scenario())


def test_sse_emits_no_token_before_generation_validation() -> None:
    async def scenario() -> None:
        retrieval = FakeRetrieval()
        generator = FakeGenerator()
        service = GraphRAGAnswerService(
            retrieval=retrieval,
            generator=generator,
            stream_chunk_chars=10,
        )
        events = [
            event
            async for event in service.stream_chat(
                ChatRequest(message="Câu hỏi độc lập")
            )
        ]
        assert generator.validated is True
        assert events[0].event == "metadata"
        assert len(events[0].data["sources"]) == 1
        assert [event.event for event in events].count("citation") == 1
        assert events[-1].event == "done"
        assert all(event.event != "token" for event in events[:1])
        assert (
            "".join(event.data["content"] for event in events if event.event == "token")
            == "Câu trả lời đã kiểm chứng."
        )

    asyncio.run(scenario())
