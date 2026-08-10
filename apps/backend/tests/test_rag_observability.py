from __future__ import annotations

import asyncio
import uuid

import pytest

from observability import bind_trace, clear_trace, get_turn_trace
from observability.rag import (
    TracedAnswerGenerator,
    TracedAnswerProvider,
    log_retrieval_failure,
    log_retrieval_result,
)
from src.generation.errors import CitationValidationError
from src.generation.models import (
    AnswerBlock,
    AnswerGenerationRequest,
    AnswerParagraph,
    AnswerResponse,
    GroundedStatement,
    ProviderAnswerRequest,
)
from src.generation.tests.factories import answer_candidate
from src.shared.retrieval_contract import RetrievalRequest
from tests.factories import retrieval_context


def _events_by_stage() -> dict[str, dict]:
    return {event["stage"]: event for event in get_turn_trace()}


def test_retrieval_trace_exposes_pipeline_metrics_without_document_content() -> None:
    context = retrieval_context()
    context.metrics.update(
        {
            "vector_hits": 8,
            "fulltext_hits": 5,
            "seed_fused_count": 10,
            "graph_units_count": 4,
            "graph_paths_count": 2,
            "graph_temporal_rejected_path_count": 1,
            "graph_malformed_path_count": 0,
            "temporal_filtered_count": 3,
            "seed_latency_ms": 12,
            "graph_latency_ms": 8,
            "planned_execution_latency_ms": 0,
            "reranker_latency_ms": 2,
            "total_pipeline_latency_ms": 31,
        }
    )
    request = RetrievalRequest(query="quyền thành lập doanh nghiệp")
    bind_trace(turn_id=uuid.uuid4())
    try:
        log_retrieval_result(
            request=request,
            context=context,
            subquery_id="q1",
            latency_ms=35,
        )
        events = _events_by_stage()
    finally:
        clear_trace()

    assert set(events) == {
        "retrieval.route",
        "retrieval.seed",
        "retrieval.graph",
        "retrieval.ranking",
        "retrieval.subquery",
    }
    assert events["retrieval.seed"]["vector_hits"] == 8
    assert events["retrieval.graph"]["temporal_rejected_paths"] == 1
    assert events["retrieval.ranking"]["temporal_filtered_count"] == 3
    assert events["retrieval.subquery"]["subquery_id"] == "q1"
    assert events["retrieval.subquery"]["top_units"] == [
        {
            "unit_id": "doc_art1",
            "final_score": 0.7,
            "sources": ["vector", "fulltext"],
        }
    ]
    serialized = repr(events)
    assert "Quyền thành lập doanh nghiệp." not in serialized
    assert "embedding" not in serialized


def test_retrieval_failure_is_typed_and_does_not_leak_error_message() -> None:
    bind_trace(turn_id=uuid.uuid4())
    try:
        log_retrieval_failure(
            request=RetrievalRequest(query="bí mật người dùng"),
            subquery_id="q2",
            latency_ms=9,
            error=RuntimeError("password=do-not-log"),
        )
        event = get_turn_trace()[0]
    finally:
        clear_trace()

    assert event["stage"] == "retrieval.subquery"
    assert event["status"] == "error"
    assert event["error_type"] == "RuntimeError"
    assert "do-not-log" not in repr(event)


class _SuccessfulGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        request.retrieval_context.metrics["generation_context"] = {
            "sufficient": True,
            "selected_unit_count": 1,
            "omitted_evidence_count": 0,
            "omitted_reason_counts": {},
            "used_evidence_chars": 120,
            "evidence_budget_chars": 1000,
            "truncated": False,
        }
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


class _GroundingFailureGenerator:
    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        raise CitationValidationError("provider payload secret")

    async def aclose(self) -> None:
        return None


class _SuccessfulProvider:
    provider_name = "fake"
    model_name = "fake-model"

    async def generate_structured(self, request: ProviderAnswerRequest):
        return answer_candidate()

    async def aclose(self) -> None:
        return None


class _FailingProvider(_SuccessfulProvider):
    async def generate_structured(self, request: ProviderAnswerRequest):
        raise RuntimeError("api-key=do-not-log")


def test_answer_trace_emits_context_call_and_grounding_outcome() -> None:
    async def scenario() -> None:
        context = retrieval_context()
        generator = TracedAnswerGenerator(_SuccessfulGenerator())
        bind_trace(turn_id=uuid.uuid4())
        try:
            response = await generator.generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )
            events = _events_by_stage()
        finally:
            clear_trace()

        assert response.cannot_answer is False
        assert events["generation.context"]["evidence_count"] == 1
        assert events["generation.projection"]["selected_unit_count"] == 1
        assert events["generation.projection"]["used_evidence_chars"] == 120
        assert events["generation.call"]["provider"] == "fake"
        assert events["generation.call"]["citation_count"] == 1
        assert events["generation.grounding"]["status"] == "ok"

    asyncio.run(scenario())


def test_answer_trace_classifies_grounding_failure_without_leaking_message() -> None:
    async def scenario() -> None:
        context = retrieval_context()
        generator = TracedAnswerGenerator(_GroundingFailureGenerator())
        bind_trace(turn_id=uuid.uuid4())
        try:
            with pytest.raises(CitationValidationError):
                await generator.generate(
                    AnswerGenerationRequest(
                        query=context.query,
                        retrieval_context=context,
                    )
                )
            events = _events_by_stage()
        finally:
            clear_trace()

        assert events["generation.grounding"]["status"] == "error"
        assert events["generation.grounding"]["error_type"] == (
            "CitationValidationError"
        )
        assert "provider payload secret" not in repr(events)

    asyncio.run(scenario())


def test_answer_provider_trace_captures_redacted_prompt_and_candidate_shape() -> None:
    async def scenario() -> None:
        provider = TracedAnswerProvider(_SuccessfulProvider())
        bind_trace(turn_id=uuid.uuid4())
        try:
            await provider.generate_structured(
                ProviderAnswerRequest(
                    system_instruction="Chỉ dùng chứng cứ hợp lệ",
                    prompt="Evidence registry có dữ liệu người dùng",
                )
            )
            event = get_turn_trace()[0]
        finally:
            clear_trace()

        assert event["stage"] == "generation.llm"
        assert event["provider"] == "fake"
        assert event["model"] == "fake-model"
        assert event["prompt"]["chars"] > 0
        assert event["raw_output"]["chars"] > 0
        assert event["statement_count"] == 1
        assert event["citation_reference_count"] == 1

    asyncio.run(scenario())


def test_answer_provider_failure_does_not_log_exception_payload() -> None:
    async def scenario() -> None:
        provider = TracedAnswerProvider(_FailingProvider())
        bind_trace(turn_id=uuid.uuid4())
        try:
            with pytest.raises(RuntimeError):
                await provider.generate_structured(
                    ProviderAnswerRequest(
                        system_instruction="system",
                        prompt="prompt",
                    )
                )
            event = get_turn_trace()[0]
        finally:
            clear_trace()

        assert event["status"] == "error"
        assert event["error_type"] == "RuntimeError"
        assert "do-not-log" not in repr(event)

    asyncio.run(scenario())
