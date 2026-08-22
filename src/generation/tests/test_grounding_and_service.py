from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.generation.config import GenerationConfig
from src.generation.context_projection import ContextProjector
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.errors import (
    AnswerProviderOutputError,
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
from src.retrieval.path_identity import build_topology_path_fingerprint
from src.retrieval.resolved_reference import (
    ReferenceSource,
    RelationGoal,
    ResolutionMethod,
    ResolvedReference,
)
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
        self.requests: list = []

    async def generate_structured(self, request):
        self.calls += 1
        self.requests.append(request)
        return self.candidate

    async def aclose(self) -> None:
        self.closed += 1


class SequencedProvider:
    """Returns a different candidate on each successive call, in order."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, candidates: list) -> None:
        self._candidates = list(candidates)
        self.calls = 0
        self.requests: list = []

    async def generate_structured(self, request):
        self.requests.append(request)
        candidate = self._candidates[min(self.calls, len(self._candidates) - 1)]
        self.calls += 1
        return candidate

    async def aclose(self) -> None:
        pass


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


def test_grounding_failure_self_repairs_on_second_attempt() -> None:
    """First candidate is ungrounded (bad citation); the model gets exactly one
    chance to resend a corrected candidate, and the repaired one is used."""

    async def scenario() -> None:
        provider = SequencedProvider(
            [answer_candidate(citation_id="doc_art999"), answer_candidate()]
        )
        context = retrieval_context()
        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        assert provider.calls == 2
        assert "BEGIN_REPAIR_FEEDBACK" in provider.requests[1].prompt
        assert response.cannot_answer is False
        assert response.citations[0].unit_id == "doc_art1"

    asyncio.run(scenario())


def test_grounding_failure_gives_up_after_one_repair_attempt() -> None:
    """Repair is bounded to a single extra LLM call — if the model still can't
    self-correct, the turn fails instead of retrying indefinitely."""

    async def scenario() -> None:
        provider = FakeProvider(answer_candidate(citation_id="doc_art999"))
        context = retrieval_context()
        with pytest.raises(CitationValidationError):
            await _generator(provider).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )
        assert provider.calls == 2

    asyncio.run(scenario())


class RepairFailsAtProviderLevel:
    """First call returns an ungrounded candidate (triggers repair); the repair
    call itself fails at the provider boundary, e.g. empty/malformed LLM output."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, first_candidate) -> None:
        self._first_candidate = first_candidate
        self.calls = 0

    async def generate_structured(self, request):
        self.calls += 1
        if self.calls == 1:
            return self._first_candidate
        raise AnswerProviderOutputError("Gemini returned an empty answer payload")

    async def aclose(self) -> None:
        pass


def test_grounding_repair_reason_is_recorded_in_metrics() -> None:
    """The first (rejected) candidate's grounding failure must be observable —
    it was previously swallowed silently before triggering repair."""

    async def scenario() -> None:
        provider = SequencedProvider(
            [answer_candidate(citation_id="doc_art999"), answer_candidate()]
        )
        context = retrieval_context()
        await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        diagnostics = context.metrics["generation_context"]
        assert diagnostics["grounding_repair_triggered"] is True
        assert "CitationValidationError" in diagnostics["grounding_repair_reason"]

    asyncio.run(scenario())


def test_repair_provider_failure_degrades_to_cannot_answer() -> None:
    """If the repair attempt itself fails at the provider boundary (empty or
    malformed LLM output), the turn must not be lost outright — degrade to
    cannot_answer instead of propagating the provider error and failing the
    whole conversation turn."""

    async def scenario() -> None:
        provider = RepairFailsAtProviderLevel(
            answer_candidate(citation_id="doc_art999")
        )
        context = retrieval_context()
        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        assert response.cannot_answer is True
        assert response.insufficiency_reason == "ANSWER_REPAIR_FAILED"
        diagnostics = context.metrics["generation_context"]
        assert diagnostics["grounding_repair_failed"] is True
        assert (
            "AnswerProviderOutputError"
            in diagnostics["grounding_repair_failure_reason"]
        )

    asyncio.run(scenario())


def test_fabricated_quote_is_hard_failure() -> None:
    """citation_id is valid and allowlisted, but quoted_text is not an actual
    excerpt of that evidence's content_raw — this must still be rejected,
    otherwise a model could cite a real unit while asserting fabricated text."""

    async def scenario() -> None:
        provider = FakeProvider(
            answer_candidate(quoted_text="Nội dung bịa đặt không có trong evidence")
        )
        context = retrieval_context()
        with pytest.raises(CitationValidationError, match="verbatim"):
            await _generator(provider).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )

    asyncio.run(scenario())


def test_verbatim_quote_is_surfaced_on_the_rendered_citation() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context()
        response = await _generator(provider).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )
        assert response.citations[0].quoted_text == (
            "Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp"
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


def test_relation_goal_answer_must_link_path_from_resolved_anchor() -> None:
    async def scenario() -> None:
        context = _relation_context()
        with pytest.raises(ReasoningPathValidationError, match="must link"):
            await _generator(FakeProvider(answer_candidate())).generate(
                AnswerGenerationRequest(query=context.query, retrieval_context=context)
            )

    asyncio.run(scenario())


def test_relation_goal_answer_exposes_verified_reasoning_path() -> None:
    async def scenario() -> None:
        context = _relation_context()
        path_id = build_topology_path_fingerprint(context.graph_paths[0])
        candidate = answer_candidate()
        statement = (
            candidate.direct_answer.paragraphs[0]
            .statements[0]
            .model_copy(update={"reasoning_path_ids": [path_id]})
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

        response = await _generator(FakeProvider(candidate)).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )

        assert [path.path_id for path in response.reasoning_paths] == [path_id]

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


def test_expired_document_anchor_supports_grounded_negative_validity() -> None:
    async def scenario() -> None:
        context = retrieval_context(intent=IntentType.VALIDITY, temporal=True)
        document = context.retrieved_units[0].model_copy(
            update={
                "id": "l_68_2014",
                "label": "Document",
                "content_raw": "Luật Doanh nghiệp số 68/2014/QH13",
                "document_id": "l_68_2014",
                "document_number": "68/2014/QH13",
                "document_title": "Luật Doanh nghiệp số 68/2014/QH13",
                "article_id": None,
                "article_number": None,
                "effective_from": date(2015, 7, 1),
                "effective_to": date(2021, 1, 1),
                "legal_status": "EXPIRED",
                "citation_label": "Văn bản, 68/2014/QH13",
                "deep_link": "/documents/l_68_2014/units/l_68_2014",
            }
        )
        context.retrieved_units = [document]
        context.evidence[0].unit_id = document.id
        context.resolved_references = (
            ResolvedReference(
                mention="Luật Doanh nghiệp năm 2014",
                node_id=document.id,
                node_type="Document",
                label="68/2014/QH13",
                document_id=document.document_id,
                resolution_method=ResolutionMethod.EXACT_STRUCTURAL_LOOKUP,
                source=ReferenceSource.CURRENT_MESSAGE,
            ),
        )
        candidate = answer_candidate(
            citation_id=document.id,
            quoted_text=document.content_raw,
        ).model_copy(
            update={
                "temporal_assertions": [
                    TemporalAssertion(
                        assertion_id="valid-at-query-date",
                        subject_unit_id=document.id,
                        query_date=date(2022, 7, 1),
                        asserted_valid=False,
                        scope="document",
                    )
                ]
            }
        )
        statement = (
            candidate.direct_answer.paragraphs[0]
            .statements[0]
            .model_copy(
                update={
                    "text": "Luật Doanh nghiệp năm 2014 không còn hiệu lực.",
                    "temporal_assertion_ids": ["valid-at-query-date"],
                }
            )
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

        response = await _generator(FakeProvider(candidate)).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )

        assert response.cannot_answer is False
        assert response.citations[0].unit_id == document.id
        assert "không có hiệu lực" in response.temporal_notes[0]

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


def _relation_context():
    context = retrieval_context(path_relations=["REFERS_TO"])
    anchor = context.graph_paths[0].nodes[0].node_id
    context.resolved_references = (
        ResolvedReference(
            mention="Điều 1 dẫn chiếu đến điều nào?",
            node_id=anchor,
            node_type="Article",
            label="Điều 1",
            document_id="doc",
            resolution_method=ResolutionMethod.EXACT_STRUCTURAL_LOOKUP,
            source=ReferenceSource.CURRENT_MESSAGE,
        ),
    )
    context.relation_goal = RelationGoal.REFERS_TO
    return context
