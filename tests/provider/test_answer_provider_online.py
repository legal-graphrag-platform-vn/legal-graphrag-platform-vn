from __future__ import annotations

import asyncio
import os

import pytest

from src.generation.config import GenerationConfig
from src.generation.models import ProviderAnswerRequest
from src.infrastructure.llm.gemini_answer_provider import GeminiAnswerProvider


pytestmark = [pytest.mark.integration, pytest.mark.answer_provider_live]


def test_real_gemini_structured_answer_smoke() -> None:
    if os.getenv("RUN_ANSWER_PROVIDER_INTEGRATION") != "1":
        pytest.skip("Set RUN_ANSWER_PROVIDER_INTEGRATION=1 for live provider smoke")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live provider smoke")

    async def scenario() -> None:
        provider = GeminiAnswerProvider(
            api_key=api_key,
            model=os.getenv("ANSWER_MODEL", "gemini-3.5-flash"),
            config=GenerationConfig(timeout_seconds=60, max_retries=0),
        )
        try:
            candidate = await provider.generate_structured(
                ProviderAnswerRequest(
                    system_instruction=(
                        "Return the requested structured schema. Use only citation doc_art1."
                    ),
                    prompt=(
                        "Evidence doc_art1 states that organizations and individuals "
                        "may establish enterprises. Produce one cited claim."
                    ),
                )
            )
            assert candidate.claims or candidate.cannot_answer
        finally:
            await provider.aclose()

    asyncio.run(scenario())
