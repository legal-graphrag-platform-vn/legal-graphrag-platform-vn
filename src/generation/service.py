"""One canonical answer generation path."""

from __future__ import annotations

from collections import Counter

from src.generation.context_projection import ContextProjector
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.grounding import GroundingValidator
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from src.generation.ports import AnswerProviderPort
from src.generation.projected_validation import ProjectedContextValidator
from src.generation.sufficiency import EvidenceSufficiencyPolicy


class AnswerGenerator:
    def __init__(
        self,
        *,
        provider: AnswerProviderPort,
        projector: ContextProjector,
        sufficiency: EvidenceSufficiencyPolicy,
        evidence_validator: EvidenceValidator,
        compactor: EvidenceCompactor,
        projected_validator: ProjectedContextValidator,
        grounding: GroundingValidator,
    ) -> None:
        self._provider = provider
        self._projector = projector
        self._sufficiency = sufficiency
        self._evidence_validator = evidence_validator
        self._compactor = compactor
        self._projected_validator = projected_validator
        self._grounding = grounding

    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        request.retrieval_context.metrics.setdefault("planner_provider_calls", 0)
        request.retrieval_context.metrics.setdefault(
            "answer_provider_calls_after_plan_failure", 0
        )
        result = self._sufficiency.evaluate(request.retrieval_context)
        if not result.sufficient:
            request.retrieval_context.metrics["generation_context"] = {
                "sufficient": False,
                "sufficiency_reason_code": result.reason_code,
            }
            return self._cannot_answer(request, result.reason_code, result.reason)

        validated = self._evidence_validator.validate(request.retrieval_context)
        plan = self._compactor.compact(request.retrieval_context, validated)
        projection = self._projector.project(request, plan)
        if projection.projected is None:
            request.retrieval_context.metrics["generation_context"] = {
                "sufficient": False,
                "sufficiency_reason_code": projection.reason_code,
                "validated_candidate_count": len(validated.candidates),
                "validated_path_count": len(validated.paths),
                "compacted_candidate_count": len(plan.candidates),
                "compacted_path_count": len(plan.paths),
                "omitted_evidence_count": len(plan.omitted_evidence),
                "omitted_reason_counts": dict(
                    Counter(item.reason for item in plan.omitted_evidence)
                ),
            }
            return self._cannot_answer(
                request,
                projection.reason_code,
                projection.reason,
            )
        projected = projection.projected
        result = self._projected_validator.evaluate(projected, plan)
        diagnostics = _projection_diagnostics(validated, plan, projected)
        if not result.sufficient:
            diagnostics.update(
                {
                    "sufficient": False,
                    "sufficiency_reason_code": result.reason_code,
                }
            )
            request.retrieval_context.metrics["generation_context"] = diagnostics
            return self._cannot_answer(request, result.reason_code, result.reason)
        diagnostics["sufficient"] = True
        request.retrieval_context.metrics["generation_context"] = diagnostics
        registry = self._projector.build_registry(projected)
        candidate = await self._provider.generate_structured(
            self._projector.provider_request(projected, registry)
        )
        return self._grounding.validate_and_render(
            candidate=candidate,
            projected=projected,
            registry=registry,
            retrieval_contract_version=request.retrieval_context.contract_version,
            provider=self._provider.provider_name,
            model=self._provider.model_name,
        )

    async def aclose(self) -> None:
        await self._provider.aclose()

    @staticmethod
    def _cannot_answer(
        request: AnswerGenerationRequest,
        reason_code: str | None,
        reason: str | None,
    ) -> AnswerResponse:
        return AnswerResponse(
            retrieval_contract_version=request.retrieval_context.contract_version,
            query=request.query,
            answer_text=reason or "Không đủ căn cứ để trả lời.",
            claims=(),
            citations=(),
            reasoning_paths=(),
            temporal_notes=(),
            cannot_answer=True,
            insufficiency_reason=reason_code,
            confidence=0.0,
            provider=None,
            model=None,
            intent=request.retrieval_context.intent.value,
            strategy=request.retrieval_context.strategy.value,
        )


def _projection_diagnostics(validated, plan, projected) -> dict[str, object]:
    omitted_reason_counts = Counter(item.reason for item in projected.omitted_evidence)
    return {
        "validated_candidate_count": len(validated.candidates),
        "validated_path_count": len(validated.paths),
        "compacted_candidate_count": len(plan.candidates),
        "compacted_path_count": len(plan.paths),
        "selected_unit_count": len(projected.selected_unit_ids),
        "selected_path_count": len(projected.paths),
        "selected_unit_ids": list(projected.selected_unit_ids[:10]),
        "selected_unit_ids_truncated": len(projected.selected_unit_ids) > 10,
        "omitted_evidence_count": len(projected.omitted_evidence),
        "omitted_reason_counts": dict(omitted_reason_counts),
        "used_evidence_chars": projected.budget.used_evidence_chars,
        "evidence_budget_chars": projected.budget.evidence_budget_chars,
        "truncated": projected.truncated,
        "admitted_bundle_count": len(projected.admitted_bundle_ids),
    }
