"""Bounded structured telemetry for retrieval and answer generation."""

from __future__ import annotations

import time
from typing import Any

from observability.trace import log_event, redact
from src.generation.errors import (
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)
from src.generation.models import (
    AnswerGenerationRequest,
    AnswerResponse,
    iter_candidate_statements,
)
from src.retrieval.models import RetrievalContext
from src.shared.retrieval_contract import RetrievalRequest

_TOP_UNIT_LIMIT = 5
_TOP_EVIDENCE_LIMIT = 10
_GROUNDING_ERRORS = (
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)


def log_retrieval_result(
    *,
    request: RetrievalRequest,
    context: RetrievalContext,
    subquery_id: str,
    latency_ms: int,
) -> None:
    """Emit queryable stage events from one completed retrieval context."""
    metrics = context.metrics
    common = {
        "subquery_id": subquery_id,
        "query": redact(request.query),
    }
    log_event(
        "retrieval.route",
        **common,
        requested_intent=(request.force_intent.value if request.force_intent else None),
        intent=context.intent.value,
        decision_reason_code=context.decision_reason_code.value,
        temporal_source=context.temporal_source.value,
        resolved_from=context.temporal.resolved_from,
        resolved_to=context.temporal.resolved_to,
        document_filter_count=len(context.filters_applied.document_ids),
        executed_channels=[channel.value for channel in context.executed_channels],
        capability_status=context.capability_status,
    )
    log_event(
        "retrieval.seed",
        **common,
        vector_hits=metrics.get("vector_hits", 0),
        fulltext_hits=metrics.get("fulltext_hits", 0),
        seed_fused_count=metrics.get("seed_fused_count", 0),
        latency_ms=metrics.get("seed_latency_ms"),
    )
    log_event(
        "retrieval.graph",
        **common,
        graph_units=metrics.get("graph_units_count", 0),
        graph_paths=metrics.get("graph_paths_count", len(context.graph_paths)),
        temporal_rejected_paths=metrics.get("graph_temporal_rejected_path_count", 0),
        malformed_paths=metrics.get("graph_malformed_path_count", 0),
        planned_execution_count=metrics.get("planned_execution_count", 0),
        planned_execution_reason_code=metrics.get("planned_execution_reason_code"),
        latency_ms=metrics.get("graph_latency_ms"),
        planned_latency_ms=metrics.get("planned_execution_latency_ms"),
    )
    log_event(
        "retrieval.ranking",
        **common,
        temporal_filtered_count=metrics.get("temporal_filtered_count", 0),
        reranker_applied=context.reranker_applied,
        reranker_latency_ms=metrics.get("reranker_latency_ms"),
        final_unit_count=len(context.retrieved_units),
    )
    log_event(
        "retrieval.subquery",
        context.capability_status,
        **common,
        latency_ms=latency_ms,
        runtime_latency_ms=metrics.get("total_pipeline_latency_ms"),
        unit_count=len(context.retrieved_units),
        evidence_count=len(context.evidence),
        graph_path_count=len(context.graph_paths),
        retrieval_mode=context.retrieval_mode,
        top_units=_top_units(context),
    )


def log_retrieval_failure(
    *,
    request: RetrievalRequest,
    subquery_id: str,
    latency_ms: int,
    error: Exception,
) -> None:
    """Emit a typed retrieval failure without provider/database error text."""
    log_event(
        "retrieval.subquery",
        "error",
        subquery_id=subquery_id,
        query=redact(request.query),
        requested_intent=(request.force_intent.value if request.force_intent else None),
        latency_ms=latency_ms,
        error_type=type(error).__name__,
        error_code=getattr(error, "error_code", None),
    )


class TracedAnswerGenerator:
    """Decorate the answer-generation boundary with safe diagnostic events."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        context = request.retrieval_context
        log_event(
            "generation.context",
            query=redact(request.query),
            intent=context.intent.value,
            retrieval_mode=context.retrieval_mode,
            unit_count=len(context.retrieved_units),
            evidence_count=len(context.evidence),
            eligible_evidence_count=sum(
                1 for item in context.evidence if item.is_eligible
            ),
            graph_path_count=len(context.graph_paths),
            evidence_unit_ids=[
                item.unit_id for item in context.evidence[:_TOP_EVIDENCE_LIMIT]
            ],
            evidence_ids_truncated=len(context.evidence) > _TOP_EVIDENCE_LIMIT,
        )
        started = time.perf_counter()
        try:
            response = await self._inner.generate(request)
        except Exception as error:
            _log_generation_projection(context)
            stage = (
                "generation.grounding"
                if isinstance(error, _GROUNDING_ERRORS)
                else "generation.call"
            )
            log_event(
                stage,
                "error",
                latency_ms=_elapsed_ms(started),
                error_type=type(error).__name__,
                error_code=getattr(error, "error_code", None),
            )
            raise

        latency_ms = _elapsed_ms(started)
        _log_generation_projection(context)
        log_event(
            "generation.call",
            "cannot_answer" if response.cannot_answer else "ok",
            latency_ms=latency_ms,
            provider=response.provider,
            model=response.model,
            statement_count=_response_statement_count(response),
            citation_count=len(response.citations),
            reasoning_path_count=len(response.reasoning_paths),
            confidence=response.confidence,
            cannot_answer=response.cannot_answer,
            insufficiency_reason=response.insufficiency_reason,
        )
        log_event(
            "generation.grounding",
            "cannot_answer" if response.cannot_answer else "ok",
            statement_count=_response_statement_count(response),
            citation_count=len(response.citations),
            reasoning_path_count=len(response.reasoning_paths),
            temporal_note_count=len(response.temporal_notes),
            insufficiency_reason=response.insufficiency_reason,
        )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class TracedAnswerProvider:
    """Decorate the structured answer-provider boundary with redacted LLM I/O."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def generate_structured(self, request):
        started = time.perf_counter()
        try:
            candidate = await self._inner.generate_structured(request)
        except Exception as error:
            log_event(
                "generation.llm",
                "error",
                latency_ms=_elapsed_ms(started),
                provider=self.provider_name,
                model=self.model_name,
                system_instruction=redact(request.system_instruction),
                prompt=redact(request.prompt),
                error_type=type(error).__name__,
                error_code=getattr(error, "error_code", None),
            )
            raise
        log_event(
            "generation.llm",
            "ok",
            latency_ms=_elapsed_ms(started),
            provider=self.provider_name,
            model=self.model_name,
            system_instruction=redact(request.system_instruction),
            prompt=redact(request.prompt),
            raw_output=redact(candidate.model_dump_json()),
            statement_count=len(tuple(iter_candidate_statements(candidate))),
            citation_reference_count=sum(
                len(statement.citation_ids)
                for statement in iter_candidate_statements(candidate)
            ),
            reasoning_path_count=len(
                {
                    path_id
                    for statement in iter_candidate_statements(candidate)
                    for path_id in statement.reasoning_path_ids
                }
            ),
            temporal_assertion_count=len(candidate.temporal_assertions),
            cannot_answer=candidate.cannot_answer,
            insufficiency_reason=candidate.insufficiency_reason,
        )
        return candidate

    async def aclose(self) -> None:
        await self._inner.aclose()


def _top_units(context: RetrievalContext) -> list[dict[str, Any]]:
    return [
        {
            "unit_id": unit.id,
            "final_score": unit.final_score,
            "sources": list(unit.retrieval_sources),
        }
        for unit in context.retrieved_units[:_TOP_UNIT_LIMIT]
    ]


def _log_generation_projection(context: RetrievalContext) -> None:
    diagnostics = context.metrics.get("generation_context")
    if isinstance(diagnostics, dict):
        log_event("generation.projection", **diagnostics)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _response_statement_count(response: AnswerResponse) -> int:
    count = 0
    if response.direct_answer is not None:
        count += sum(
            len(paragraph.statements) for paragraph in response.direct_answer.paragraphs
        )
    count += sum(
        len(paragraph.statements)
        for section in response.sections
        for paragraph in section.paragraphs
    )
    count += sum(len(paragraph.statements) for paragraph in response.caveats)
    return count
