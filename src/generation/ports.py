"""Ports implemented by answer provider infrastructure."""

from __future__ import annotations

from typing import Protocol

from src.generation.models import AnswerCandidate, ProviderAnswerRequest


class AnswerProviderPort(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def generate_structured(
        self,
        request: ProviderAnswerRequest,
    ) -> AnswerCandidate: ...

    async def aclose(self) -> None: ...
