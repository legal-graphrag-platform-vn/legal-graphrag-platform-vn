"""Unit tests for the conversation orchestration service (Plan 19 §4)."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from conversation.service import ConversationChatService
from persistence.domain import (
    BegunTurn,
    HistoryContext,
    Owner,
    TurnRecord,
)
from persistence.enums import (
    ClarificationMode,
    OwnerKind,
    ResolutionStatus,
    TurnStatus,
)
from resolution.models import (
    CancelResolution,
    ClarifyResolution,
    ExpectedUnitType,
    ResolvedCandidate,
    ResolvedResolution,
    StandaloneResolution,
)
from resolution.rewriter import RewriteTimeoutError, StructuredRewriter
from src.generation.models import (
    AnswerBlock,
    AnswerParagraph,
    AnswerResponse,
    GroundedStatement,
    StatementCitation,
)
from src.retrieval.errors import RetrievalDependencyError
from src.retrieval.resolved_reference import ResolutionMethod, ReferenceSource
from src.retrieval.resolved_reference import RelationGoal
from src.shared.retrieval_contract import (
    PlanType,
    ProcessingStatus,
    QueryProcessingResult,
    SubqueryDTO,
    SubqueryIntent,
)
from tests.factories import retrieval_context


def _owner() -> Owner:
    return Owner(owner_kind=OwnerKind.ANONYMOUS, owner_principal_id=uuid.uuid4())


def _request(message: str = "câu hỏi", document_ids=None):
    from api.models import ConversationChatRequest

    return ConversationChatRequest(
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        message=message,
        document_ids=document_ids or [],
    )


def _empty_context() -> HistoryContext:
    return HistoryContext(
        recent_messages=(), grounded_focuses=(), pending_clarification=None
    )


class FakeLockedTurn:
    def __init__(self, context: HistoryContext) -> None:
        self._context = context
        self.persisted_answer = None
        self.persisted_clarification = None
        self.failed = None
        self.rechecked: TurnRecord | None = None

    async def find_turn_by_client_id(self, client_turn_id):
        return self.rechecked

    async def begin_turn_and_load_context(self, *, client_turn_id, user_message):
        return BegunTurn(
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            user_turn_no=1,
            user_message_ordinal=1,
            context=self._context,
        )

    async def persist_grounded_answer(self, **kwargs):
        self.persisted_answer = kwargs

    async def persist_clarification(self, **kwargs):
        self.persisted_clarification = kwargs

    async def mark_turn_failed(self, **kwargs):
        self.failed = kwargs

    async def clear_pending(self):
        return None


class FakeStore:
    def __init__(
        self,
        *,
        context: HistoryContext | None = None,
        existing: TurnRecord | None = None,
        recheck: TurnRecord | None = None,
    ) -> None:
        self._context = context or _empty_context()
        self._existing = existing
        self.turn = FakeLockedTurn(self._context)
        self.turn.rechecked = recheck
        self.locked_entered = False

    async def find_turn_by_client_id(self, **kwargs):
        return self._existing

    @asynccontextmanager
    async def locked_turn(self, **kwargs):
        self.locked_entered = True
        yield self.turn


class FakeResolver:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = 0

    async def resolve(self, *, message, context):
        self.calls += 1
        return self.outcome


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls = 0
        self.last_query = None
        self.last_document_ids = None
        self.last_execution_context = None

    async def retrieve_context(self, request, *, execution_context=None):
        self.calls += 1
        self.last_query = request.query
        self.last_document_ids = list(request.filters.document_ids)
        self.last_execution_context = execution_context
        context = retrieval_context()
        context.query = request.query
        if execution_context is not None:
            context.resolved_references = execution_context.resolved_references
            context.relation_goal = execution_context.relation_goal
        return context


class FakeGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.last_query = None

    async def generate(self, request) -> AnswerResponse:
        self.calls += 1
        self.last_query = request.query
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
                                citations=[
                                    StatementCitation(
                                        citation_id=unit.id, quoted_text="đoạn trích"
                                    )
                                ],
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


class FailingRewriter:
    async def rewrite(self, *, message, recent_messages, resolution):
        raise RewriteTimeoutError("timeout")


def _service(
    store,
    resolver,
    *,
    rewriter=None,
    retrieval=None,
    generator=None,
    query_processor=None,
):
    return ConversationChatService(
        store=store,
        resolver=resolver,
        rewriter=rewriter or StructuredRewriter(llm=None),
        retrieval=retrieval or FakeRetrieval(),
        generator=generator or FakeGenerator(),
        stream_chunk_chars=20,
        query_processor=query_processor,
    )


def _run_events(service, request, owner):
    async def _collect():
        return [event async for event in service.stream_chat(request, owner)]

    return asyncio.run(_collect())


def _resolved_candidate(document_id="doc-1"):
    return ResolvedCandidate(
        node_id="art-111",
        node_type=ExpectedUnitType.ARTICLE,
        canonical_label="Điều 111 59/2020/QH14",
        document_id=document_id,
        document_number="59/2020/QH14",
        article_id="art-111",
        article_number="111",
    )


def _resolved(document_id="doc-1", *, anaphora=False) -> ResolvedResolution:
    return ResolvedResolution(
        candidate=_resolved_candidate(document_id),
        resolution_method=(
            ResolutionMethod.GROUNDED_HISTORY_FOCUS
            if anaphora
            else ResolutionMethod.EXACT_STRUCTURAL_LOOKUP
        ),
        source=(
            ReferenceSource.GROUNDED_HISTORY
            if anaphora
            else ReferenceSource.CURRENT_MESSAGE
        ),
    )


# --------------------------------------------------------------------------- #
# Standalone / grounded answer                                                 #
# --------------------------------------------------------------------------- #


def test_standalone_answer_retrieves_and_generates_once() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    generator = FakeGenerator()
    service = _service(
        store,
        FakeResolver(StandaloneResolution()),
        retrieval=retrieval,
        generator=generator,
    )
    events = _run_events(service, _request("công ty cổ phần là gì"), _owner())

    assert retrieval.calls == 1
    assert generator.calls == 1
    # Retrieval and generation use the same standalone query.
    assert retrieval.last_query == "công ty cổ phần là gì"
    assert generator.last_query == "công ty cổ phần là gì"
    kinds = [event.event for event in events]
    assert kinds[0] == "metadata"
    assert kinds[-1] == "done"
    assert "citation" in kinds
    assert store.turn.persisted_answer["update_focus"] is True


def test_query_processor_trace_preserves_subquery_ids_and_merge_counts() -> None:
    class FakeQueryProcessor:
        async def process(self, current_query, conversation_history=()):
            return QueryProcessingResult(
                status=ProcessingStatus.READY,
                standalone_query=current_query,
                plan_type=PlanType.PARALLEL,
                subqueries=[
                    SubqueryDTO(
                        id="definition",
                        query="Công ty cổ phần là gì?",
                        intent=SubqueryIntent.DEFINITION,
                    ),
                    SubqueryDTO(
                        id="requirements",
                        query="Điều kiện thành lập công ty cổ phần?",
                        intent=SubqueryIntent.FACTUAL,
                    ),
                ],
            )

    from observability import bind_trace, clear_trace, get_turn_trace

    store = FakeStore()
    service = _service(
        store,
        FakeResolver(StandaloneResolution()),
        query_processor=FakeQueryProcessor(),
    )
    bind_trace(turn_id=uuid.uuid4())
    try:
        _run_events(service, _request("công ty cổ phần"), _owner())
        trace = get_turn_trace()
    finally:
        clear_trace()

    subquery_events = [
        event for event in trace if event["stage"] == "retrieval.subquery"
    ]
    assert {event["subquery_id"] for event in subquery_events} == {
        "definition",
        "requirements",
    }
    merge = next(event for event in trace if event["stage"] == "retrieval.merge")
    assert merge["input_unit_count"] == 2
    assert merge["merged_unit_count"] == 1
    assert merge["deduplicated_unit_count"] == 1


def test_reference_resolver_clarification_precedes_query_processor() -> None:
    class UnexpectedQueryProcessor:
        calls = 0

        async def process(self, current_query, conversation_history=()):
            self.calls += 1
            raise AssertionError("query processor must not run before clarification")

    resolver = FakeResolver(
        ClarifyResolution(
            mode=ClarificationMode.SELECT,
            resolution_status=ResolutionStatus.AMBIGUOUS,
            reason_code="MULTIPLE_MATCHES",
            question="Ý bạn là văn bản nào?",
            candidates=(),
        )
    )
    processor = UnexpectedQueryProcessor()
    retrieval = FakeRetrieval()
    generator = FakeGenerator()
    store = FakeStore()
    service = _service(
        store,
        resolver,
        retrieval=retrieval,
        generator=generator,
        query_processor=processor,
    )

    events = _run_events(service, _request("điều đó quy định gì"), _owner())

    assert resolver.calls == 1
    assert processor.calls == 0
    assert retrieval.calls == 0
    assert generator.calls == 0
    assert events[-1].data["status"] == "needs_clarification"


def test_query_processor_receives_canonical_query_and_resolved_filter() -> None:
    class RecordingQueryProcessor:
        def __init__(self) -> None:
            self.calls = []

        async def process(self, current_query, conversation_history=()):
            self.calls.append((current_query, conversation_history))
            return QueryProcessingResult(
                status=ProcessingStatus.READY,
                standalone_query=current_query,
                plan_type=PlanType.SINGLE,
                subqueries=[
                    SubqueryDTO(
                        id="canonical",
                        query=current_query,
                        intent=SubqueryIntent.FACTUAL,
                    )
                ],
            )

    resolver = FakeResolver(_resolved("doc-1", anaphora=True))
    processor = RecordingQueryProcessor()
    retrieval = FakeRetrieval()
    store = FakeStore()
    service = _service(
        store,
        resolver,
        retrieval=retrieval,
        query_processor=processor,
    )

    _run_events(service, _request("điều đó quy định gì"), _owner())

    assert processor.calls == [("Điều 111 59/2020/QH14 quy định gì", ())]
    assert retrieval.last_query == "Điều 111 59/2020/QH14 quy định gì"
    assert retrieval.last_document_ids == ["doc-1"]
    assert retrieval.last_execution_context.anchor_node_ids == ("art-111",)
    reference = retrieval.last_execution_context.resolved_references[0]
    assert reference.resolution_method is ResolutionMethod.GROUNDED_HISTORY_FOCUS
    assert reference.source is ReferenceSource.GROUNDED_HISTORY
    assert store.turn.persisted_answer["resolution_status"] is ResolutionStatus.RESOLVED


def test_query_processor_cannot_drop_resolved_canonical_anchor() -> None:
    class AnchorDroppingQueryProcessor:
        async def process(self, current_query, conversation_history=()):
            return QueryProcessingResult(
                status=ProcessingStatus.READY,
                standalone_query="quy định gì",
                plan_type=PlanType.SINGLE,
                subqueries=[
                    SubqueryDTO(
                        id="lost-anchor",
                        query="quy định gì",
                        intent=SubqueryIntent.FACTUAL,
                    )
                ],
            )

    retrieval = FakeRetrieval()
    store = FakeStore()
    service = _service(
        store,
        FakeResolver(_resolved("doc-1", anaphora=True)),
        retrieval=retrieval,
        query_processor=AnchorDroppingQueryProcessor(),
    )

    events = _run_events(service, _request("điều đó quy định gì"), _owner())

    assert retrieval.calls == 0
    assert store.turn.failed["error_code"] == "QUERY_PROCESSING_FAILED"
    assert events[-1].data["status"] == "error"


def test_query_processor_cannot_replace_canonical_generation_query() -> None:
    class RephrasingQueryProcessor:
        async def process(self, current_query, conversation_history=()):
            return QueryProcessingResult(
                status=ProcessingStatus.READY,
                standalone_query="processor rephrase",
                plan_type=PlanType.SINGLE,
                subqueries=[
                    SubqueryDTO(
                        id="q1",
                        query="retrieval decomposition",
                        intent=SubqueryIntent.FACTUAL,
                    )
                ],
            )

    retrieval = FakeRetrieval()
    generator = FakeGenerator()
    store = FakeStore()
    service = _service(
        store,
        FakeResolver(StandaloneResolution()),
        retrieval=retrieval,
        generator=generator,
        query_processor=RephrasingQueryProcessor(),
    )

    _run_events(service, _request("canonical standalone query"), _owner())

    assert retrieval.last_query == "retrieval decomposition"
    assert generator.last_query == "canonical standalone query"
    assert store.turn.persisted_answer["standalone_query"] == (
        "canonical standalone query"
    )


def test_typed_relation_lookup_bypasses_query_decomposition_in_v1() -> None:
    class UnexpectedQueryProcessor:
        calls = 0

        async def process(self, current_query, conversation_history=()):
            self.calls += 1
            raise AssertionError("typed relation lookup must remain atomic")

    processor = UnexpectedQueryProcessor()
    retrieval = FakeRetrieval()
    store = FakeStore()
    service = _service(
        store,
        FakeResolver(_resolved("doc-1")),
        retrieval=retrieval,
        query_processor=processor,
    )

    _run_events(
        service,
        _request("Điều 111 59/2020/QH14 dẫn chiếu đến điều nào?"),
        _owner(),
    )

    assert processor.calls == 0
    assert retrieval.calls == 1
    assert retrieval.last_execution_context.relation_goal is RelationGoal.REFERS_TO
    assert retrieval.last_execution_context.anchor_node_ids == ("art-111",)
    metadata = store.turn.persisted_answer["response_snapshot"]["metadata"]
    assert metadata["relation_goal"] == "REFERS_TO"
    assert metadata["resolved_references"][0]["node_id"] == "art-111"


def test_resolved_reference_intersects_document_filter() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    resolver = FakeResolver(_resolved("doc-1"))
    service = _service(store, resolver, retrieval=retrieval)
    _run_events(
        service,
        _request("Điều 111 59/2020/QH14 quy định gì", document_ids=["doc-1"]),
        _owner(),
    )
    assert retrieval.last_document_ids == ["doc-1"]


def test_filter_conflict_requests_clarification_before_retrieval() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    resolver = FakeResolver(_resolved("doc-1"))
    service = _service(store, resolver, retrieval=retrieval)
    events = _run_events(
        service,
        _request("Điều 111 59/2020/QH14 quy định gì", document_ids=["doc-2"]),
        _owner(),
    )
    assert retrieval.calls == 0
    assert store.turn.failed is None
    assert store.turn.persisted_clarification["resolution_reason_code"] == (
        "REFERENCE_FILTER_CONFLICT"
    )
    assert events[-1].data["status"] == "needs_clarification"


def test_rewrite_failure_is_persisted_and_streamed() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    resolver = FakeResolver(_resolved(anaphora=True))
    service = _service(store, resolver, rewriter=FailingRewriter(), retrieval=retrieval)
    events = _run_events(service, _request("điều đó"), _owner())
    assert retrieval.calls == 0
    assert store.turn.failed["error_code"] == "REWRITE_TIMEOUT"
    assert events[0].event == "error"
    assert events[-1].data["status"] == "error"


def test_retrieval_error_is_persisted_as_failure() -> None:
    class BadRetrieval:
        calls = 0

        async def retrieve_context(self, request, *, execution_context=None):
            raise RetrievalDependencyError("down")

    store = FakeStore()
    service = _service(
        store, FakeResolver(StandaloneResolution()), retrieval=BadRetrieval()
    )
    events = _run_events(service, _request("câu hỏi"), _owner())
    assert store.turn.failed is not None
    assert events[0].event == "error"


# --------------------------------------------------------------------------- #
# Clarification / cancel / small talk                                          #
# --------------------------------------------------------------------------- #


def test_clarification_makes_no_downstream_calls() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    generator = FakeGenerator()
    resolver = FakeResolver(
        ClarifyResolution(
            mode=ClarificationMode.SELECT,
            resolution_status=ResolutionStatus.AMBIGUOUS,
            reason_code="MULTIPLE_MATCHES",
            question="Ý bạn là văn bản nào?",
            candidates=(),
        )
    )
    service = _service(store, resolver, retrieval=retrieval, generator=generator)
    events = _run_events(service, _request("Điều 5"), _owner())

    assert retrieval.calls == 0
    assert generator.calls == 0
    assert store.turn.persisted_clarification is not None
    kinds = [event.event for event in events]
    assert "clarification" in kinds
    assert events[-1].data["status"] == "needs_clarification"


def test_cancel_persists_small_talk_without_retrieval() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    resolver = FakeResolver(CancelResolution())
    service = _service(store, resolver, retrieval=retrieval)
    events = _run_events(service, _request("hủy"), _owner())
    assert retrieval.calls == 0
    assert store.turn.persisted_answer["update_focus"] is False
    assert events[-1].data["status"] == "completed"


def test_greeting_bypasses_retrieval() -> None:
    store = FakeStore()
    retrieval = FakeRetrieval()
    service = _service(store, FakeResolver(StandaloneResolution()), retrieval=retrieval)
    events = _run_events(service, _request("chào"), _owner())
    assert retrieval.calls == 0
    assert store.turn.persisted_answer["update_focus"] is False
    assert events[0].data["intent"] == "small_talk"


# --------------------------------------------------------------------------- #
# Idempotency                                                                  #
# --------------------------------------------------------------------------- #


def _terminal_record(status: TurnStatus, snapshot) -> TurnRecord:
    return TurnRecord(
        turn_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        client_turn_id=uuid.uuid4(),
        user_turn_no=1,
        status=status,
        resolution_status=None,
        resolution_reason_code=None,
        standalone_query=None,
        error_code=None,
        response_snapshot=snapshot,
        created_at=datetime.now(timezone.utc),
    )


def test_completed_turn_replays_without_locking() -> None:
    snapshot = {
        "kind": "answer",
        "metadata": None,
        "answer_text": "đã trả lời",
        "citations": [],
        "done": {"status": "completed", "citation_count": 0},
    }
    store = FakeStore(existing=_terminal_record(TurnStatus.COMPLETED, snapshot))
    service = _service(store, FakeResolver(StandaloneResolution()))
    events = _run_events(service, _request(), _owner())
    assert store.locked_entered is False
    assert events[-1].data["status"] == "completed"


def test_processing_turn_returns_processing_done() -> None:
    store = FakeStore(existing=_terminal_record(TurnStatus.PROCESSING, None))
    service = _service(store, FakeResolver(StandaloneResolution()))
    events = _run_events(service, _request(), _owner())
    assert events[-1].data["status"] == "processing"
    assert events[-1].data["retry_after_ms"] == 1000


def test_failed_turn_replays_error_snapshot() -> None:
    snapshot = {
        "kind": "error",
        "error": {"code": "REWRITE_TIMEOUT", "message": "Quá thời gian."},
        "done": {"status": "error", "citation_count": 0},
    }
    store = FakeStore(existing=_terminal_record(TurnStatus.FAILED, snapshot))
    service = _service(store, FakeResolver(StandaloneResolution()))
    events = _run_events(service, _request(), _owner())
    assert events[0].event == "error"
    assert events[0].data["code"] == "REWRITE_TIMEOUT"


def test_recheck_under_lock_replays_existing_turn() -> None:
    snapshot = {
        "kind": "answer",
        "answer_text": "đã trả lời",
        "citations": [],
        "done": {"status": "completed", "citation_count": 0},
    }
    store = FakeStore(recheck=_terminal_record(TurnStatus.COMPLETED, snapshot))
    retrieval = FakeRetrieval()
    service = _service(store, FakeResolver(StandaloneResolution()), retrieval=retrieval)
    events = _run_events(service, _request(), _owner())
    # The re-check short-circuits before any resolution/retrieval.
    assert retrieval.calls == 0
    assert events[-1].data["status"] == "completed"
