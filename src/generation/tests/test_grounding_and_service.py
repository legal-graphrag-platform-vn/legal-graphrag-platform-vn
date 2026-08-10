from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.generation.config import GenerationConfig
from src.generation.context_projection import ContextProjector
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.errors import (
    CitationValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)
from src.generation.grounding import GroundingValidator
from src.generation.models import (
    AnswerGenerationRequest,
    TemporalAssertion,
)
from src.generation.service import AnswerGenerator
from src.generation.projected_validation import ProjectedContextValidator
from src.generation.sufficiency import EvidenceSufficiencyPolicy
from src.generation.tests.factories import answer_candidate, retrieval_context
from src.retrieval.models import IntentType
from src.retrieval.execution_contract import (
    PlanExecutionResult,
    PlanExecutionStatus,
    PlanReasonCode,
)


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, candidate=None) -> None:
        self.candidate = candidate or answer_candidate()
        self.calls = 0
        self.closed = 0

    async def generate_structured(self, request):
        self.calls += 1
        return self.candidate

    async def aclose(self) -> None:
        self.closed += 1


def test_insufficient_evidence_does_not_call_provider() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context(no_results=True)
        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        assert response.cannot_answer is True
        assert provider.calls == 0
        assert response.provider is None
        assert context.metrics["generation_context"] == {
            "sufficient": False,
            "sufficiency_reason_code": response.insufficiency_reason,
        }

    asyncio.run(scenario())


def test_failed_plan_does_not_call_answer_provider_and_metrics_are_separate() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context(intent=IntentType.MULTI_HOP)
        context.plan_execution = PlanExecutionResult(
            plan_fingerprint="plan-failed",
            satisfied_path_fingerprints=(),
            bound_anchor_id="doc_art1",
            bound_target_id="doc_art3",
            execution_status=PlanExecutionStatus.FAILED,
            reason_code=PlanReasonCode.NO_PATH,
        )

        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )

        assert response.cannot_answer is True
        assert response.insufficiency_reason == "NO_PATH"
        assert provider.calls == 0
        assert context.metrics["planner_provider_calls"] == 0
        assert context.metrics["answer_provider_calls_after_plan_failure"] == 0
        assert "planner_provider_calls" != ("answer_provider_calls_after_plan_failure")

    asyncio.run(scenario())


def test_supported_answer_uses_trusted_citation_metadata() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context()
        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        assert provider.calls == 1
        assert response.citations[0].unit_id == "doc_art1"
        assert response.citations[0].deep_link == "/documents/doc/units/doc_art1"
        assert response.answer_text == (
            "Tổ chức, cá nhân có quyền thành lập doanh nghiệp. [1]"
        )
        diagnostics = context.metrics["generation_context"]
        assert diagnostics["sufficient"] is True
        assert diagnostics["selected_unit_count"] == 1
        assert diagnostics["omitted_evidence_count"] == 0
        assert diagnostics["used_evidence_chars"] > 0

    asyncio.run(scenario())


def test_hallucinated_citation_is_hard_failure() -> None:
    async def scenario() -> None:
        provider = FakeProvider(answer_candidate(citation_id="doc_art999"))
        context = retrieval_context()
        with pytest.raises(CitationValidationError):
            await _generator(provider).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )

    asyncio.run(scenario())


def test_invented_reasoning_path_is_rejected() -> None:
    async def scenario() -> None:
        candidate = answer_candidate()
        statement = (
            candidate.direct_answer.paragraphs[0]
            .statements[0]
            .model_copy(update={"reasoning_path_ids": ["path_invented"]})
        )
        paragraph = candidate.direct_answer.paragraphs[0].model_copy(
            update={"statements": [statement]}
        )
        candidate = candidate.model_copy(
            update={
                "direct_answer": candidate.direct_answer.model_copy(
                    update={"paragraphs": [paragraph]}
                )
            }
        )
        context = retrieval_context(path_relations=["REFERS_TO"])
        with pytest.raises(ReasoningPathValidationError):
            await _generator(FakeProvider(candidate)).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )

    asyncio.run(scenario())


def test_temporal_assertion_must_match_retrieved_interval() -> None:
    async def scenario() -> None:
        candidate = answer_candidate().model_copy(
            update={
                "temporal_assertions": [
                    TemporalAssertion(
                        assertion_id="valid-at-query-date",
                        subject_unit_id="doc_art1",
                        query_date=date(2022, 7, 1),
                        asserted_valid=False,
                        scope="scoped_pilot",
                    )
                ]
            }
        )
        statement = (
            candidate.direct_answer.paragraphs[0]
            .statements[0]
            .model_copy(update={"temporal_assertion_ids": ["valid-at-query-date"]})
        )
        paragraph = candidate.direct_answer.paragraphs[0].model_copy(
            update={"statements": [statement]}
        )
        candidate = candidate.model_copy(
            update={
                "direct_answer": candidate.direct_answer.model_copy(
                    update={"paragraphs": [paragraph]}
                )
            }
        )
        context = retrieval_context(intent=IntentType.VALIDITY, temporal=True)
        with pytest.raises(TemporalAnswerValidationError):
            await _generator(FakeProvider(candidate)).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )

    asyncio.run(scenario())


def _generator(provider: FakeProvider) -> AnswerGenerator:
    config = GenerationConfig()
    return AnswerGenerator(
        provider=provider,
        projector=ContextProjector(config),
        sufficiency=EvidenceSufficiencyPolicy(),
        evidence_validator=EvidenceValidator(),
        compactor=EvidenceCompactor(),
        projected_validator=ProjectedContextValidator(),
        grounding=GroundingValidator(),
    )
