from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from src.generation.config import GenerationConfig
from src.generation.context_projection import ContextProjector
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.errors import EvidenceContractError
from src.generation.grounding import GroundingValidator
from src.generation.models import (
    AnswerCompositionOperand,
    AnswerCompositionPlan,
    AnswerGenerationRequest,
)
from src.generation.projected_validation import ProjectedContextValidator
from src.generation.service import AnswerGenerator
from src.generation.sufficiency import EvidenceSufficiencyPolicy
from src.generation.tests.factories import (
    answer_candidate,
    bind_satisfied_path,
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


def _comparison_plan() -> AnswerCompositionPlan:
    return AnswerCompositionPlan(
        operands=(
            AnswerCompositionOperand(
                operand_id="ordinary",
                query="Quyền của cổ phần phổ thông?",
                evidence_unit_ids=("doc_art1",),
            ),
            AnswerCompositionOperand(
                operand_id="voting_preference",
                query="Quyền của cổ phần ưu đãi biểu quyết?",
                evidence_unit_ids=("doc_art2",),
            ),
        )
    )


def test_comparison_composition_requires_evidence_from_each_operand() -> None:
    context = retrieval_context()
    second = retrieved_unit("doc_art2")
    second.content_raw = "Cổ phần ưu đãi biểu quyết có nhiều hơn một phiếu biểu quyết."
    context.retrieved_units.append(second)
    context.evidence.append(
        EvidenceItem(unit_id=second.id, evidence_type="vector", is_eligible=True)
    )
    composition = _comparison_plan()
    validated = EvidenceValidator().validate(context)

    plan = EvidenceCompactor().compact(
        context,
        validated,
        composition_plan=composition,
    )

    assert len(plan.required_bundle_sets) == 1
    required = plan.required_bundle_sets[0]
    assert {bundle.operand_id for bundle in required} == {
        "ordinary",
        "voting_preference",
    }
    assert {bundle.unit_ids for bundle in required} == {
        ("doc_art1",),
        ("doc_art2",),
    }


def test_comparison_provenance_follows_deduplicated_evidence() -> None:
    context = retrieval_context()
    duplicate = retrieved_unit("doc_art2")
    context.retrieved_units.append(duplicate)
    context.evidence.append(
        EvidenceItem(unit_id=duplicate.id, evidence_type="vector", is_eligible=True)
    )
    composition = _comparison_plan()

    plan = EvidenceCompactor().compact(
        context,
        EvidenceValidator().validate(context),
        composition_plan=composition,
    )

    assert plan.composition_plan is not None
    assert [
        operand.evidence_unit_ids for operand in plan.composition_plan.operands
    ] == [
        ("doc_art1",),
        ("doc_art1",),
    ]
    assert {bundle.operand_id for bundle in plan.required_bundle_sets[0]} == {
        "ordinary",
        "voting_preference",
    }


def test_projected_comparison_prompt_preserves_operand_evidence_mapping() -> None:
    context = retrieval_context()
    second = retrieved_unit("doc_art2")
    second.content_raw = "Cổ phần ưu đãi biểu quyết có nhiều hơn một phiếu biểu quyết."
    context.retrieved_units.append(second)
    context.evidence.append(
        EvidenceItem(unit_id=second.id, evidence_type="vector", is_eligible=True)
    )
    composition = _comparison_plan()
    request = AnswerGenerationRequest(
        query=context.query,
        retrieval_context=context,
        composition_plan=composition,
    )
    projector = ContextProjector(GenerationConfig())
    validated = EvidenceValidator().validate(context)
    plan = EvidenceCompactor().compact(
        context,
        validated,
        composition_plan=composition,
    )

    result = projector.project(request, plan)

    assert result.projected is not None
    assert result.projected.selected_unit_ids[:2] == ("doc_art1", "doc_art2")
    projected_plan = result.projected.composition_plan
    assert projected_plan is not None
    assert projected_plan.operands == composition.operands
    assigned_ids = {
        unit_id
        for operand in projected_plan.operands
        for unit_id in operand.evidence_unit_ids
    }
    assert assigned_ids == set(result.projected.selected_unit_ids)
    provider_request = projector.provider_request(
        result.projected,
        projector.build_registry(result.projected),
    )
    assert '"composition_plan"' in provider_request.prompt
    assert '"operand_id":"ordinary"' in provider_request.prompt


def test_comparison_missing_one_operand_evidence_does_not_call_provider() -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        context = retrieval_context()
        composition = _comparison_plan()
        second = retrieved_unit("doc_art2")
        second.content_raw = (
            "Cổ phần ưu đãi biểu quyết có nhiều hơn một phiếu biểu quyết."
        )
        context.retrieved_units.append(second)
        request = AnswerGenerationRequest(
            query=context.query,
            retrieval_context=context,
            composition_plan=composition,
        )

        response = await _generator(provider, GenerationConfig()).generate(request)

        assert response.cannot_answer is True
        assert response.insufficiency_reason == "PROJECTED_EVIDENCE_INSUFFICIENT"
        assert provider.calls == 0

    asyncio.run(scenario())


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
    bind_satisfied_path(context)
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


def test_parallel_citations_share_one_topology_path_identity() -> None:
    context = retrieval_context(intent=IntentType.MULTI_HOP)
    second = retrieved_unit("doc_art2")
    third = retrieved_unit("doc_art3")
    context.retrieved_units.extend([second, third])
    context.evidence.extend(
        [
            EvidenceItem(unit_id=second.id, evidence_type="graph", is_eligible=True),
            EvidenceItem(unit_id=third.id, evidence_type="graph", is_eligible=True),
        ]
    )
    first_path = graph_path(
        ["doc_art1", "doc_art2", "doc_art3"],
        ["REFERS_TO", "REFERS_TO"],
    )
    parallel_path = first_path.model_copy(
        update={
            "edges": tuple(
                edge.model_copy(update={"relation_id": f"parallel-{index}"})
                for index, edge in enumerate(first_path.edges, start=1)
            )
        }
    )
    context.graph_paths = [first_path, parallel_path]

    validated = EvidenceValidator().validate(context)

    assert len(validated.paths) == 2
    assert validated.paths[0].path_id == validated.paths[1].path_id


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
    bind_satisfied_path(context)
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    projector = ContextProjector(GenerationConfig())
    result = projector.project(request, _compact(context))
    assert result.projected is not None

    registry = projector.build_registry(result.projected)

    assert "legal_concept_x" in result.projected.paths[0].nodes
    assert "legal_concept_x" not in registry.allowed_citation_ids
    assert registry.allowed_citation_ids == ("doc_art1", "doc_art2")


def test_multi_hop_compaction_keeps_only_satisfied_path() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    satisfied_path = context.graph_paths[0]
    shorter_path = graph_path(
        ["doc_art1", "doc_art3"],
        ["REQUIRES"],
    )
    context.graph_paths = [shorter_path, satisfied_path]

    plan = _compact(context)

    assert len(plan.paths) == 1
    assert plan.paths[0].path.nodes == satisfied_path.nodes
    assert plan.required_bundle_sets[0][0].unit_ids == (
        "doc_art1",
        "doc_art2",
        "doc_art3",
    )


def test_multi_hop_projection_excludes_evidence_outside_satisfied_path() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    unrelated = retrieved_unit("doc_art99")
    context.retrieved_units.append(unrelated)
    context.evidence.append(
        EvidenceItem(
            unit_id=unrelated.id,
            evidence_type="vector",
            is_eligible=True,
        )
    )
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)

    result = ContextProjector(GenerationConfig()).project(request, _compact(context))

    assert result.projected is not None
    assert result.projected.selected_unit_ids == (
        "doc_art1",
        "doc_art2",
        "doc_art3",
    )


def test_projected_validation_rejects_missing_citable_intermediate() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    plan = _compact(context)
    result = ContextProjector(GenerationConfig()).project(request, plan)
    assert result.projected is not None
    projected = result.projected
    incomplete = projected.model_copy(
        update={
            "evidence": tuple(
                item for item in projected.evidence if item.unit_id != "doc_art2"
            ),
            "selected_unit_ids": tuple(
                unit_id
                for unit_id in projected.selected_unit_ids
                if unit_id != "doc_art2"
            ),
        }
    )

    validation = ProjectedContextValidator().evaluate(incomplete, plan)

    assert validation.sufficient is False
    assert validation.reason_code == "PROJECTED_EVIDENCE_INSUFFICIENT"


def test_projected_validation_requires_satisfied_path_membership() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    request = AnswerGenerationRequest(query=context.query, retrieval_context=context)
    plan = _compact(context)
    result = ContextProjector(GenerationConfig()).project(request, plan)
    assert result.projected is not None
    corrupted_plan = replace(
        plan,
        authoritative_path_ids=("path_not_satisfied",),
    )

    validation = ProjectedContextValidator().evaluate(
        result.projected,
        corrupted_plan,
    )

    assert validation.sufficient is False
    assert validation.reason_code == "PROJECTED_EVIDENCE_INSUFFICIENT"


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
