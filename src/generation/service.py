"""One canonical answer generation path."""

from __future__ import annotations

from src.generation.context_projection import ContextProjector
from src.generation.grounding import GroundingValidator
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from src.generation.ports import AnswerProviderPort
from src.generation.sufficiency import EvidenceSufficiencyPolicy


class AnswerGenerator:
    def __init__(
        self,
        *,
        provider: AnswerProviderPort,
        projector: ContextProjector,
        sufficiency: EvidenceSufficiencyPolicy,
        grounding: GroundingValidator,
    ) -> None:
        self._provider = provider
        self._projector = projector
        self._sufficiency = sufficiency
        self._grounding = grounding

    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        result = self._sufficiency.evaluate(request.retrieval_context)
        if not result.sufficient:
            return AnswerResponse(
                retrieval_contract_version=request.retrieval_context.contract_version,
                query=request.query,
                answer_text=result.reason or "Không đủ căn cứ để trả lời.",
                claims=(),
                citations=(),
                reasoning_paths=(),
                temporal_notes=(),
                cannot_answer=True,
                insufficiency_reason=result.reason_code,
                confidence=0.0,
                provider=None,
                model=None,
                intent=request.retrieval_context.intent.value,
                strategy=request.retrieval_context.strategy.value,
            )

        projected = self._projector.project(request)
        candidate = await self._provider.generate_structured(
            self._projector.provider_request(projected)
        )
        return self._grounding.validate_and_render(
            candidate=candidate,
            projected=projected,
            retrieval_contract_version=request.retrieval_context.contract_version,
            provider=self._provider.provider_name,
            model=self._provider.model_name,
        )

    async def aclose(self) -> None:
        await self._provider.aclose()
