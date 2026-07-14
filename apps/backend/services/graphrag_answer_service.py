"""Retrieve once, generate once, then stream only validated answer content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from api.models import (
    ChatCitationData,
    ChatDoneData,
    ChatMetadataData,
    ChatRequest,
    ChatStreamEvent,
    ChatTokenData,
)
from services.conversation import greeting_response
from services.interfaces import AnswerGeneratorPort, RetrievalApplicationPort
from services.retrieval_mapping import to_retrieval_response
from src.generation.models import (
    ANSWER_CONTRACT_VERSION,
    AnswerGenerationRequest,
    AnswerResponse,
    GenerationHistoryMessage,
)
from src.retrieval.models import RetrievalContext
from src.shared.retrieval_contract import (
    RETRIEVAL_CONTRACT_VERSION,
    RetrievalFilters,
    RetrievalRequest,
)


@dataclass(frozen=True)
class BackendAnswerResult:
    retrieval_context: RetrievalContext
    answer: AnswerResponse


class GraphRAGAnswerService:
    def __init__(
        self,
        *,
        retrieval: RetrievalApplicationPort,
        generator: AnswerGeneratorPort,
        stream_chunk_chars: int,
    ) -> None:
        if stream_chunk_chars < 1:
            raise ValueError("stream_chunk_chars must be positive")
        self._retrieval = retrieval
        self._generator = generator
        self._stream_chunk_chars = stream_chunk_chars

    async def answer(self, request: ChatRequest) -> BackendAnswerResult:
        retrieval_context = await self._retrieval.retrieve_context(
            RetrievalRequest(
                query=request.message,
                filters=RetrievalFilters(
                    document_ids=request.document_ids,
                    query_date=request.query_date,
                ),
                force_intent=request.force_intent,
                enable_reranker=request.enable_reranker,
            )
        )
        answer = await self._generator.generate(
            AnswerGenerationRequest(
                query=request.message,
                retrieval_context=retrieval_context,
                conversation_history=tuple(
                    GenerationHistoryMessage(role=item.role, content=item.content)
                    for item in request.history
                ),
            )
        )
        return BackendAnswerResult(
            retrieval_context=retrieval_context,
            answer=answer,
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[ChatStreamEvent]:
        direct_response = greeting_response(request.message)
        if direct_response is not None:
            async for event in self._stream_direct_response(direct_response):
                yield event
            return

        result = await self.answer(request)
        retrieval = to_retrieval_response(result.retrieval_context)
        answer = result.answer
        cited_ids = {citation.unit_id for citation in answer.citations}
        cited_sources = [
            unit for unit in retrieval.retrieved_units if unit.id in cited_ids
        ]
        yield ChatStreamEvent(
            event="metadata",
            data=ChatMetadataData(
                sources=cited_sources,
                intent=answer.intent,
                strategy=answer.strategy,
                retrieval_mode=result.retrieval_context.retrieval_mode,
                retrieval_contract_version=answer.retrieval_contract_version,
                answer_contract_version=answer.contract_version,
                cannot_answer=answer.cannot_answer,
            ).model_dump(mode="json"),
        )
        for chunk in _chunks(answer.answer_text, self._stream_chunk_chars):
            yield ChatStreamEvent(event="token", data={"content": chunk})
        for citation in answer.citations:
            yield ChatStreamEvent(
                event="citation",
                data=ChatCitationData(
                    unit_id=citation.unit_id,
                    citation_label=citation.citation_label,
                    document_id=citation.document_id,
                    article_id=citation.article_id,
                    clause_id=citation.clause_id,
                    deep_link=citation.deep_link,
                ).model_dump(mode="json"),
            )
        yield ChatStreamEvent(
            event="done",
            data=ChatDoneData(
                status="cannot_answer" if answer.cannot_answer else "completed",
                citation_count=len(answer.citations),
                confidence=answer.confidence,
                provider=answer.provider,
                model=answer.model,
            ).model_dump(mode="json"),
        )

    async def _stream_direct_response(
        self,
        response: str,
    ) -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(
            event="metadata",
            data=ChatMetadataData(
                sources=[],
                intent="small_talk",
                strategy="direct_response",
                retrieval_mode="not_applicable",
                retrieval_contract_version=RETRIEVAL_CONTRACT_VERSION,
                answer_contract_version=ANSWER_CONTRACT_VERSION,
                cannot_answer=False,
            ).model_dump(mode="json"),
        )
        for chunk in _chunks(response, self._stream_chunk_chars):
            yield ChatStreamEvent(
                event="token",
                data=ChatTokenData(content=chunk).model_dump(mode="json"),
            )
        yield ChatStreamEvent(
            event="done",
            data=ChatDoneData(
                status="completed",
                citation_count=0,
                confidence=1.0,
                provider=None,
                model=None,
            ).model_dump(mode="json"),
        )


def _chunks(value: str, chunk_size: int) -> list[str]:
    return [
        value[index : index + chunk_size] for index in range(0, len(value), chunk_size)
    ]
