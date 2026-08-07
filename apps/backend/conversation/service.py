"""Grounded conversation orchestration service (Plan 19 §4).

Flow: authenticate + idempotency pre-check -> advisory lock -> begin turn and
load context -> deterministic resolution -> (clarification | standalone/resolved
-> rewrite -> retrieval once -> generation once -> grounding) -> persist ->
release lock -> buffered SSE from the persisted snapshot.
"""

from __future__ import annotations

from typing import AsyncIterator

from api.error_handlers import stream_error_contract
from api.models import (
    ChatCitationData,
    ChatClarificationCandidateData,
    ChatClarificationData,
    ChatDoneData,
    ChatMetadataData,
    ChatStreamEvent,
    ConversationChatRequest,
)
from conversation.snapshot import (
    KIND_ANSWER,
    KIND_CANNOT_ANSWER,
    KIND_SMALL_TALK,
    answer_snapshot,
    clarification_snapshot,
    error_snapshot,
    processing_snapshot,
    stream_from_snapshot,
)
from persistence.domain import (
    BegunTurn,
    CitationSnapshot,
    Owner,
)
from persistence.enums import (
    ClarificationMode,
    MessageKind,
    ResolutionStatus,
    TurnStatus,
)
from persistence.errors import ConversationStoreError
from persistence.repository import (
    LockedTurn,
    SqlAlchemyConversationStore,
    focus_upserts_from_citations,
)
from query_processing.fanout import build_subquery_requests, merge_contexts
from resolution.models import (
    REASON_NO_REFERENCE_REQUIRED,
    REASON_USER_CANCELLED,
    CancelResolution,
    ClarifyResolution,
    ResolvedResolution,
    StandaloneResolution,
)
from resolution.resolver import ReferenceResolver
from resolution.rewriter import RewriteError, StructuredRewriter
from services.conversation import greeting_response
from services.interfaces import (
    AnswerGeneratorPort,
    QueryProcessorPort,
    RetrievalApplicationPort,
)
from services.retrieval_mapping import to_retrieval_response
from src.generation.errors import AnswerGenerationError
from src.generation.models import (
    ANSWER_CONTRACT_VERSION,
    AnswerGenerationRequest,
)
from src.retrieval.errors import QueryProcessingError, RetrievalError
from src.shared.llm_errors import TextGenerationError
from src.shared.retrieval_contract import (
    RETRIEVAL_CONTRACT_VERSION,
    ProcessingStatus,
    RetrievalFilters,
    RetrievalRequest,
)

PROCESSING_RETRY_AFTER_MS = 1000
FILTER_CONFLICT_CODE = "CONVERSATION_FILTER_CONFLICT"
QUERY_PROCESSING_FAILED_CODE = "QUERY_PROCESSING_FAILED"
REASON_QUERY_PROCESSOR_CLARIFICATION = "QUERY_PROCESSOR_CLARIFICATION"
_QUERY_PROCESSING_FAILED_MESSAGE = "Không thể xử lý câu hỏi. Vui lòng thử lại."
_QUERY_PROCESSOR_FALLBACK_QUESTION = "Bạn có thể nói rõ hơn câu hỏi không?"

_REPLAYABLE_STATUSES = frozenset(
    {
        TurnStatus.COMPLETED,
        TurnStatus.CANNOT_ANSWER,
        TurnStatus.NEEDS_CLARIFICATION,
        TurnStatus.FAILED,
    }
)


class ConversationFilterConflictError(Exception):
    error_code = FILTER_CONFLICT_CODE


class ConversationChatService:
    def __init__(
        self,
        *,
        store: SqlAlchemyConversationStore,
        resolver: ReferenceResolver,
        rewriter: StructuredRewriter,
        retrieval: RetrievalApplicationPort,
        generator: AnswerGeneratorPort,
        stream_chunk_chars: int,
        query_processor: QueryProcessorPort | None = None,
    ) -> None:
        if stream_chunk_chars < 1:
            raise ValueError("stream_chunk_chars must be positive")
        self._store = store
        self._resolver = resolver
        self._rewriter = rewriter
        self._retrieval = retrieval
        self._generator = generator
        self._chunk_chars = stream_chunk_chars
        self._query_processor = query_processor

    async def stream_chat(
        self, request: ConversationChatRequest, owner: Owner
    ) -> AsyncIterator[ChatStreamEvent]:
        snapshot = await self._resolve_snapshot(request, owner)
        for event in stream_from_snapshot(snapshot, chunk_chars=self._chunk_chars):
            yield event

    async def _resolve_snapshot(
        self, request: ConversationChatRequest, owner: Owner
    ) -> dict:
        existing = await self._store.find_turn_by_client_id(
            conversation_id=request.conversation_id,
            owner=owner,
            client_turn_id=request.client_turn_id,
        )
        if existing is not None:
            return self._replay_snapshot(existing)

        async with self._store.locked_turn(
            conversation_id=request.conversation_id, owner=owner
        ) as turn:
            re_checked = await turn.find_turn_by_client_id(request.client_turn_id)
            if re_checked is not None:
                return self._replay_snapshot(re_checked)
            begun = await turn.begin_turn_and_load_context(
                client_turn_id=request.client_turn_id,
                user_message=request.message,
            )
            return await self._process_turn(turn, begun, request)

    def _replay_snapshot(self, record) -> dict:
        if record.status is TurnStatus.PROCESSING:
            return processing_snapshot(retry_after_ms=PROCESSING_RETRY_AFTER_MS)
        if record.status in _REPLAYABLE_STATUSES and record.response_snapshot:
            return record.response_snapshot
        # A terminal turn without a snapshot is a persistence invariant breach.
        raise ConversationStoreError("Turn is missing a replayable snapshot")

    async def _process_turn(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        request: ConversationChatRequest,
    ) -> dict:
        if self._query_processor is not None:
            return await self._process_turn_with_query_processor(turn, begun, request)

        outcome = await self._resolver.resolve(
            message=request.message, context=begun.context
        )

        if isinstance(outcome, CancelResolution):
            return await self._persist_cancel(turn, begun)
        if isinstance(outcome, ClarifyResolution):
            return await self._persist_clarification(turn, begun, outcome)

        if isinstance(outcome, StandaloneResolution):
            greeting = greeting_response(request.message)
            if greeting is not None:
                return await self._persist_small_talk(turn, begun, greeting)

        return await self._persist_answer(turn, begun, request, outcome)

    async def _process_turn_with_query_processor(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        request: ConversationChatRequest,
    ) -> dict:
        # Greetings short-circuit before spending an LLM call.
        greeting = greeting_response(request.message)
        if greeting is not None:
            return await self._persist_small_talk(turn, begun, greeting)

        history = _history_for_processor(begun)
        try:
            result = await self._query_processor.process(request.message, history)
        except (QueryProcessingError, TextGenerationError):
            return await self._persist_failure(
                turn,
                begun,
                QUERY_PROCESSING_FAILED_CODE,
                _QUERY_PROCESSING_FAILED_MESSAGE,
            )

        if result.status is ProcessingStatus.NEEDS_CLARIFICATION:
            clarify = ClarifyResolution(
                mode=ClarificationMode.RESTATE,
                resolution_status=ResolutionStatus.UNRESOLVED,
                reason_code=REASON_QUERY_PROCESSOR_CLARIFICATION,
                question=result.clarification_question
                or _QUERY_PROCESSOR_FALLBACK_QUESTION,
                candidates=(),
            )
            return await self._persist_clarification(turn, begun, clarify)

        # Ready: fan out the subqueries, merge contexts, and answer once.
        return await self._answer_from_query_processing(turn, begun, request, result)

    # -- clarification / cancel / small talk -------------------------------- #

    async def _persist_clarification(
        self, turn: LockedTurn, begun: BegunTurn, outcome: ClarifyResolution
    ) -> dict:
        metadata = _clarification_metadata(outcome.resolution_status.value)
        clarification = ChatClarificationData(
            mode=outcome.mode.value,
            question=outcome.question,
            candidates=[
                ChatClarificationCandidateData(
                    candidate_id=candidate.candidate_id, label=candidate.label
                )
                for candidate in outcome.candidates
            ],
        )
        done = ChatDoneData(status="needs_clarification", citation_count=0)
        snapshot = clarification_snapshot(
            metadata=metadata, clarification=clarification, done=done
        )
        await turn.persist_clarification(
            turn_id=begun.turn_id,
            mode=outcome.mode,
            question=outcome.question,
            candidates=outcome.candidates,
            resolution_status=outcome.resolution_status,
            resolution_reason_code=outcome.reason_code,
            response_snapshot=snapshot,
        )
        return snapshot

    async def _persist_cancel(self, turn: LockedTurn, begun: BegunTurn) -> dict:
        text = "Đã hủy yêu cầu làm rõ. Bạn có thể đặt câu hỏi mới."
        return await self._persist_direct(
            turn,
            begun,
            text=text,
            resolution_status=ResolutionStatus.UNRESOLVED,
            reason_code=REASON_USER_CANCELLED,
        )

    async def _persist_small_talk(
        self, turn: LockedTurn, begun: BegunTurn, text: str
    ) -> dict:
        return await self._persist_direct(
            turn,
            begun,
            text=text,
            resolution_status=ResolutionStatus.UNRESOLVED,
            reason_code=REASON_NO_REFERENCE_REQUIRED,
        )

    async def _persist_direct(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        *,
        text: str,
        resolution_status: ResolutionStatus,
        reason_code: str,
    ) -> dict:
        metadata = _small_talk_metadata()
        done = ChatDoneData(status="completed", citation_count=0, confidence=1.0)
        snapshot = answer_snapshot(
            kind=KIND_SMALL_TALK,
            metadata=metadata,
            answer_text=text,
            citations=[],
            done=done,
        )
        await turn.persist_grounded_answer(
            turn_id=begun.turn_id,
            user_turn_no=begun.user_turn_no,
            status=TurnStatus.COMPLETED,
            kind=MessageKind.SMALL_TALK,
            content=text,
            standalone_query="",
            resolution_status=resolution_status,
            resolution_reason_code=reason_code,
            citations=(),
            focus_upserts=(),
            update_focus=False,
            response_snapshot=snapshot,
        )
        return snapshot

    # -- grounded answer ---------------------------------------------------- #

    async def _persist_answer(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        request: ConversationChatRequest,
        outcome: StandaloneResolution | ResolvedResolution,
    ) -> dict:
        recent = tuple(msg.content for msg in begun.context.recent_messages)
        try:
            standalone_query = await self._rewriter.rewrite(
                message=request.message,
                recent_messages=recent,
                resolution=outcome,
            )
            document_ids = self._effective_document_ids(request, outcome)
        except RewriteError as exc:
            return await self._persist_failure(turn, begun, exc.error_code, str(exc))
        except ConversationFilterConflictError as exc:
            return await self._persist_failure(
                turn, begun, exc.error_code, "Bộ lọc tài liệu mâu thuẫn với tham chiếu."
            )

        try:
            retrieval_context = await self._retrieval.retrieve_context(
                RetrievalRequest(
                    query=standalone_query,
                    filters=RetrievalFilters(
                        document_ids=document_ids,
                        query_date=request.query_date,
                    ),
                    force_intent=request.force_intent,
                    enable_reranker=request.enable_reranker,
                )
            )
            answer = await self._generator.generate(
                AnswerGenerationRequest(
                    query=standalone_query,
                    retrieval_context=retrieval_context,
                    conversation_history=(),
                )
            )
        except (RetrievalError, AnswerGenerationError) as exc:
            code, message = stream_error_contract(exc)
            return await self._persist_failure(turn, begun, code, message)

        return await self._finish_answer(
            turn,
            begun,
            outcome,
            standalone_query=standalone_query,
            retrieval_context=retrieval_context,
            answer=answer,
        )

    async def _answer_from_query_processing(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        request: ConversationChatRequest,
        result,
    ) -> dict:
        # Fan out each subquery with its own temporal-safe intent, merge the
        # per-subquery contexts, then generate a single grounded answer.
        standalone_query = result.standalone_query
        subquery_requests = build_subquery_requests(
            result,
            document_ids=list(request.document_ids),
            query_date=request.query_date,
            enable_reranker=request.enable_reranker,
        )
        try:
            contexts = [
                await self._retrieval.retrieve_context(subquery_request)
                for subquery_request in subquery_requests
            ]
            merged_context = merge_contexts(contexts, query=standalone_query)
            answer = await self._generator.generate(
                AnswerGenerationRequest(
                    query=standalone_query,
                    retrieval_context=merged_context,
                    conversation_history=(),
                )
            )
        except (RetrievalError, AnswerGenerationError) as exc:
            code, message = stream_error_contract(exc)
            return await self._persist_failure(turn, begun, code, message)

        return await self._finish_answer(
            turn,
            begun,
            StandaloneResolution(),
            standalone_query=standalone_query,
            retrieval_context=merged_context,
            answer=answer,
        )

    async def _finish_answer(
        self,
        turn: LockedTurn,
        begun: BegunTurn,
        outcome: StandaloneResolution | ResolvedResolution,
        *,
        standalone_query: str,
        retrieval_context,
        answer,
    ) -> dict:
        retrieval = to_retrieval_response(retrieval_context)
        units_by_id = {unit.id: unit for unit in retrieval.retrieved_units}
        cited_ids = {citation.unit_id for citation in answer.citations}
        cited_sources = [
            unit for unit in retrieval.retrieved_units if unit.id in cited_ids
        ]

        citation_data: list[ChatCitationData] = []
        citation_snapshots: list[CitationSnapshot] = []
        for ordinal, citation in enumerate(answer.citations, start=1):
            citation_data.append(
                ChatCitationData(
                    unit_id=citation.unit_id,
                    citation_label=citation.citation_label,
                    document_id=citation.document_id,
                    article_id=citation.article_id,
                    clause_id=citation.clause_id,
                    deep_link=citation.deep_link,
                )
            )
            citation_snapshots.append(
                _citation_snapshot(citation, ordinal, units_by_id.get(citation.unit_id))
            )

        cannot_answer = answer.cannot_answer
        status = TurnStatus.CANNOT_ANSWER if cannot_answer else TurnStatus.COMPLETED
        kind = MessageKind.CANNOT_ANSWER if cannot_answer else MessageKind.ANSWER
        resolution_status, reason_code = _answer_resolution(outcome)
        metadata = ChatMetadataData(
            sources=cited_sources,
            intent=answer.intent,
            strategy=answer.strategy,
            retrieval_mode=retrieval_context.retrieval_mode,
            retrieval_contract_version=answer.retrieval_contract_version,
            answer_contract_version=answer.contract_version,
            cannot_answer=cannot_answer,
            resolution_status=resolution_status.value,
        )
        done = ChatDoneData(
            status="cannot_answer" if cannot_answer else "completed",
            citation_count=len(citation_data),
            confidence=answer.confidence,
            provider=answer.provider,
            model=answer.model,
        )
        snapshot = answer_snapshot(
            kind=KIND_CANNOT_ANSWER if cannot_answer else KIND_ANSWER,
            metadata=metadata,
            answer_text=answer.answer_text,
            citations=citation_data,
            done=done,
        )
        await turn.persist_grounded_answer(
            turn_id=begun.turn_id,
            user_turn_no=begun.user_turn_no,
            status=status,
            kind=kind,
            content=answer.answer_text,
            standalone_query=standalone_query,
            resolution_status=resolution_status,
            resolution_reason_code=reason_code,
            citations=tuple(citation_snapshots),
            focus_upserts=focus_upserts_from_citations(citation_snapshots),
            update_focus=not cannot_answer,
            response_snapshot=snapshot,
        )
        return snapshot

    async def _persist_failure(
        self, turn: LockedTurn, begun: BegunTurn, code: str, message: str
    ) -> dict:
        snapshot = error_snapshot(code=code, message=message)
        await turn.mark_turn_failed(
            turn_id=begun.turn_id,
            error_code=code,
            response_snapshot=snapshot,
        )
        return snapshot

    def _effective_document_ids(
        self,
        request: ConversationChatRequest,
        outcome: StandaloneResolution | ResolvedResolution,
    ) -> list[str]:
        # Standalone keeps the explicit request filters (Plan 19 §4 step 6).
        if isinstance(outcome, StandaloneResolution):
            return list(request.document_ids)
        resolved_document = outcome.candidate.document_id
        if not request.document_ids:
            return [resolved_document]
        if resolved_document in request.document_ids:
            return [resolved_document]
        raise ConversationFilterConflictError(
            "Requested document filter excludes the resolved reference"
        )


def _history_for_processor(begun: BegunTurn) -> tuple[dict[str, str], ...]:
    """Serialize recent transcript messages into role/content pairs."""
    return tuple(
        {"role": msg.role.value, "content": msg.content}
        for msg in begun.context.recent_messages
    )


def _citation_snapshot(citation, ordinal: int, unit) -> CitationSnapshot:
    metadata = {}
    if unit is not None:
        metadata = {
            "document_number": unit.document_number,
            "article_number": unit.article_number,
            "clause_number": unit.clause_number,
        }
    return CitationSnapshot(
        unit_id=citation.unit_id,
        citation_ordinal=ordinal,
        citation_label=citation.citation_label,
        document_id=citation.document_id,
        deep_link=citation.deep_link,
        article_id=citation.article_id,
        clause_id=citation.clause_id,
        metadata=metadata,
    )


def _answer_resolution(
    outcome: StandaloneResolution | ResolvedResolution,
) -> tuple[ResolutionStatus, str | None]:
    if isinstance(outcome, ResolvedResolution):
        return ResolutionStatus.RESOLVED, None
    return ResolutionStatus.UNRESOLVED, REASON_NO_REFERENCE_REQUIRED


def _clarification_metadata(resolution_status: str) -> ChatMetadataData:
    return ChatMetadataData(
        sources=[],
        intent="clarification",
        strategy="clarification",
        retrieval_mode="not_applicable",
        retrieval_contract_version=RETRIEVAL_CONTRACT_VERSION,
        answer_contract_version=ANSWER_CONTRACT_VERSION,
        cannot_answer=False,
        needs_clarification=True,
        resolution_status=resolution_status,
    )


def _small_talk_metadata() -> ChatMetadataData:
    return ChatMetadataData(
        sources=[],
        intent="small_talk",
        strategy="direct_response",
        retrieval_mode="not_applicable",
        retrieval_contract_version=RETRIEVAL_CONTRACT_VERSION,
        answer_contract_version=ANSWER_CONTRACT_VERSION,
        cannot_answer=False,
    )
