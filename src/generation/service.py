"""One canonical answer generation path."""

from __future__ import annotations

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
        result = self._sufficiency.evaluate(request.retrieval_context)
        if not result.sufficient:
            return self._cannot_answer(request, result.reason_code, result.reason)

        validated = self._evidence_validator.validate(request.retrieval_context)
        plan = self._compactor.compact(request.retrieval_context, validated)
        projection = self._projector.project(request, plan)
        if projection.projected is None:
            return self._cannot_answer(
                request,
                projection.reason_code,
                projection.reason,
            )
        projected = projection.projected
        result = self._projected_validator.evaluate(projected, plan)
        if not result.sufficient:
            return self._cannot_answer(request, result.reason_code, result.reason)
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
