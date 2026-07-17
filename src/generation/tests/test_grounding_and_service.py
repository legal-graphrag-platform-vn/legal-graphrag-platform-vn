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
        assert "Điều 1, Luật thử nghiệm" in response.answer_text

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
        candidate = answer_candidate().model_copy(
            update={"reasoning_path_ids": ["path_invented"]}
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
                        subject_unit_id="doc_art1",
                        query_date=date(2022, 7, 1),
                        asserted_valid=False,
                        scope="scoped_pilot",
                    )
                ]
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
