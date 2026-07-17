from __future__ import annotations

import asyncio

import pytest

from src.generation.config import GenerationConfig
from src.generation.context_projection import ContextProjector
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.errors import EvidenceContractError
from src.generation.grounding import GroundingValidator
from src.generation.models import AnswerGenerationRequest
from src.generation.projected_validation import ProjectedContextValidator
from src.generation.service import AnswerGenerator
from src.generation.sufficiency import EvidenceSufficiencyPolicy
from src.generation.tests.factories import (
    answer_candidate,
    graph_path,
    retrieval_context,
    retrieved_unit,
)
from src.retrieval.models import EvidenceItem, GraphReasoningRequirement, IntentType


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, request):
        self.calls += 1
        return answer_candidate()

    async def aclose(self) -> None:
        return None


def test_evidence_validator_rejects_malformed_unit() -> None:
    context = retrieval_context()
    context.retrieved_units[0].deep_link = ""

    with pytest.raises(EvidenceContractError, match="deep link"):
        EvidenceValidator().validate(context)


def test_hierarchical_duplicate_is_omitted_without_losing_provenance() -> None:
    context = retrieval_context()
    duplicate_clause = retrieved_unit("doc_art1_cl1", label="Clause")
    duplicate_clause.content_raw = context.retrieved_units[0].content_raw
    context.retrieved_units.append(duplicate_clause)
    context.evidence.append(
        EvidenceItem(
            unit_id=duplicate_clause.id,
            evidence_type="vector",
            is_eligible=False,
        )
    )

    plan = _compact(context)

    assert [item.unit.id for item in plan.candidates] == ["doc_art1"]
    assert plan.omitted_evidence[0].unit_id == "doc_art1_cl1"
    assert plan.omitted_evidence[0].reason == "hierarchical_duplicate"
    assert plan.omitted_evidence[0].retained_unit_id == "doc_art1"


def test_optional_oversized_unit_is_skipped_and_later_unit_is_admitted() -> None:
    context = retrieval_context()
    context.retrieved_units[0].content_raw = "required " * 20
    oversized = retrieved_unit("doc_art2")
    oversized.content_raw = "oversized " * 500
    trailing = retrieved_unit("doc_art3")
    trailing.content_raw = "compact supporting evidence"
    context.retrieved_units.extend([oversized, trailing])
    context.evidence.extend(
        [
            EvidenceItem(
                unit_id=oversized.id,
                evidence_type="vector",
                is_eligible=False,
            ),
            EvidenceItem(
                unit_id=trailing.id,
                evidence_type="vector",
                is_eligible=False,
            ),
        ]
    )
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    projector = ContextProjector(GenerationConfig(context_max_chars=3000))
    plan = _compact(context)

    result = projector.project(request, plan)

    assert result.projected is not None
    assert result.projected.selected_unit_ids == ("doc_art1", "doc_art3")
    assert any(
        omitted.unit_id == "doc_art2" and omitted.reason == "context_budget_exceeded"
        for omitted in result.projected.omitted_evidence
    )


def test_multi_hop_bundle_is_admitted_atomically() -> None:
    context = retrieval_context(intent=IntentType.MULTI_HOP)
    second = retrieved_unit("doc_art2")
    second.content_raw = "Intermediate legal provision."
    third = retrieved_unit("doc_art3")
    third.content_raw = "Target legal provision."
    context.retrieved_units.extend([second, third])
    context.evidence.extend(
        [
            EvidenceItem(
                unit_id=second.id,
                evidence_type="graph",
                is_eligible=True,
            ),
            EvidenceItem(
                unit_id=third.id,
                evidence_type="graph",
                is_eligible=True,
            ),
        ]
    )
    context.graph_paths = [
        graph_path(
            ["doc_art1", "doc_art2", "doc_art3"],
            ["REFERS_TO", "REFERS_TO"],
        )
    ]
    context.reasoning_requirement = GraphReasoningRequirement(minimum_edges=2)
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    projector = ContextProjector(GenerationConfig())
    plan = _compact(context)

    result = projector.project(request, plan)

    assert result.projected is not None
    assert result.projected.selected_unit_ids == (
        "doc_art1",
        "doc_art2",
        "doc_art3",
    )
    assert len(result.projected.paths) == 1
    assert len(result.projected.admitted_bundle_ids) == 1


def test_registry_contains_only_projected_legal_evidence() -> None:
    context = retrieval_context()
    oversized = retrieved_unit("doc_art2")
    oversized.content_raw = "x" * 5000
    context.retrieved_units.append(oversized)
    context.evidence.append(
        EvidenceItem(
            unit_id=oversized.id,
            evidence_type="vector",
            is_eligible=False,
        )
    )
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    projector = ContextProjector(GenerationConfig(context_max_chars=2500))
    result = projector.project(request, _compact(context))
    assert result.projected is not None

    registry = projector.build_registry(result.projected)

    assert registry.allowed_citation_ids == ("doc_art1",)
    assert {entry.unit_id for entry in registry.entries} == {"doc_art1"}


def test_path_only_semantic_node_is_not_citation_eligible() -> None:
    context = retrieval_context(intent=IntentType.MULTI_HOP)
    target = retrieved_unit("doc_art2")
    target.content_raw = "Target legal provision."
    context.retrieved_units.append(target)
    context.evidence.append(
        EvidenceItem(
            unit_id=target.id,
            evidence_type="graph",
            is_eligible=True,
        )
    )
    context.graph_paths = [
        graph_path(
            ["doc_art1", "legal_concept_x", "doc_art2"],
            ["DEFINES", "REQUIRES"],
            semantic_node_ids={"legal_concept_x"},
        )
    ]
    context.reasoning_requirement = GraphReasoningRequirement(minimum_edges=2)
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    projector = ContextProjector(GenerationConfig())
    result = projector.project(request, _compact(context))
    assert result.projected is not None

    registry = projector.build_registry(result.projected)

    assert "legal_concept_x" in result.projected.paths[0].nodes
    assert "legal_concept_x" not in registry.allowed_citation_ids
    assert registry.allowed_citation_ids == ("doc_art1", "doc_art2")


def test_mandatory_bundle_budget_failure_does_not_call_provider() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context()
        context.retrieved_units[0].content_raw = "required " * 1000
        response = await _generator(
            provider,
            GenerationConfig(context_max_chars=2000),
        ).generate(
            AnswerGenerationRequest(query=context.query, retrieval_context=context)
        )

        assert response.cannot_answer is True
        assert response.insufficiency_reason == (
            "REQUIRED_EVIDENCE_EXCEEDS_CONTEXT_BUDGET"
        )
        assert provider.calls == 0

    asyncio.run(scenario())


def test_malformed_evidence_does_not_call_provider() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context()
        context.retrieved_units[0].citation_label = ""
        with pytest.raises(EvidenceContractError):
            await _generator(provider, GenerationConfig()).generate(
                AnswerGenerationRequest(
                    query=context.query,
                    retrieval_context=context,
                )
            )
        assert provider.calls == 0

    asyncio.run(scenario())


def _compact(context):
    validated = EvidenceValidator().validate(context)
    return EvidenceCompactor().compact(context, validated)


def _generator(provider: FakeProvider, config: GenerationConfig) -> AnswerGenerator:
    return AnswerGenerator(
        provider=provider,
        projector=ContextProjector(config),
        sufficiency=EvidenceSufficiencyPolicy(),
        evidence_validator=EvidenceValidator(),
        compactor=EvidenceCompactor(),
        projected_validator=ProjectedContextValidator(),
        grounding=GroundingValidator(),
    )
