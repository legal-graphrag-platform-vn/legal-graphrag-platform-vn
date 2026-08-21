"""One canonical answer generation path."""

from __future__ import annotations

from collections import Counter

from src.generation.context_projection import ContextProjector
from src.generation.errors import (
    AnswerProviderDependencyError,
    AnswerProviderOutputError,
    AnswerProviderTimeoutError,
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)
from src.generation.evidence_compaction import EvidenceCompactor
from src.generation.evidence_validation import EvidenceValidator
from src.generation.grounding import GroundingValidator
from src.generation.models import (
    AnswerGenerationRequest,
    AnswerResponse,
    EvidenceRegistry,
    ProjectedAnswerContext,
)
from src.generation.ports import AnswerProviderPort
from src.generation.projected_validation import ProjectedContextValidator
from src.generation.sufficiency import EvidenceSufficiencyPolicy


# A grounding failure means the model produced a schema-valid but ungrounded
# candidate (bad citation/quote/path/temporal claim). One repair attempt lets
# it self-correct from the exact validation error instead of failing the turn
# outright; kept to a single retry since each attempt is a full LLM call.
_GROUNDING_ERRORS = (
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)

# A repair-attempt failure at the provider boundary (empty/malformed LLM output,
# timeout, dependency unavailable) is not the model failing to self-correct —
# it is the one extra LLM call itself misbehaving. Degrade to cannot_answer
# instead of losing a turn that already had a valid first candidate. A second
# _GROUNDING_ERRORS from the repaired candidate is a genuine self-correction
# failure and must still hard-fail (see test_grounding_failure_gives_up_after_one_repair_attempt).
_REPAIR_PROVIDER_ERRORS = (
    AnswerProviderDependencyError,
    AnswerProviderTimeoutError,
    AnswerProviderOutputError,
)


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
        provider_request = self._projector.provider_request(projected, registry)
        candidate = await self._provider.generate_structured(provider_request)
        try:
            return self._render(
                candidate=candidate,
                projected=projected,
                registry=registry,
                request=request,
            )
        except _GROUNDING_ERRORS as exc:
            request.retrieval_context.metrics["generation_context"] = {
                **request.retrieval_context.metrics.get("generation_context", {}),
                "grounding_repair_triggered": True,
                "grounding_repair_reason": f"{type(exc).__name__}: {exc}",
            }
            repair_request = provider_request.model_copy(
                update={
                    "prompt": (
                        provider_request.prompt
                        + "\nBEGIN_REPAIR_FEEDBACK\n"
                        + "Your previous JSON candidate was rejected: "
                        + f"{exc}\n"
                        + "Fix exactly this issue and resend the full corrected "
                        "JSON candidate, following BEGIN_OUTPUT_CONTRACT.\n"
                        + "END_REPAIR_FEEDBACK"
                    )
                }
            )
            try:
                candidate = await self._provider.generate_structured(repair_request)
                return self._render(
                    candidate=candidate,
                    projected=projected,
                    registry=registry,
                    request=request,
                )
            except _REPAIR_PROVIDER_ERRORS as repair_exc:
                request.retrieval_context.metrics["generation_context"] = {
                    **request.retrieval_context.metrics.get("generation_context", {}),
                    "grounding_repair_failed": True,
                    "grounding_repair_failure_reason": (
                        f"{type(repair_exc).__name__}: {repair_exc}"
                    ),
                }
                return self._cannot_answer(
                    request,
                    "ANSWER_REPAIR_FAILED",
                    "Không thể tạo câu trả lời đủ căn cứ sau khi thử sửa lại; "
                    "vui lòng thử lại câu hỏi.",
                )

    def _render(
        self,
        *,
        candidate,
        projected: ProjectedAnswerContext,
        registry: EvidenceRegistry,
        request: AnswerGenerationRequest,
    ) -> AnswerResponse:
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
            direct_answer=None,
            sections=(),
            caveats=(),
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
