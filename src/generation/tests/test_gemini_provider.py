from __future__ import annotations

import asyncio
import json

import pytest

from src.generation.config import GenerationConfig
from src.generation.errors import (
    AnswerProviderDependencyError,
    AnswerProviderOutputError,
    AnswerProviderTimeoutError,
)
from src.generation.models import ProviderAnswerRequest
from src.generation.tests.factories import answer_candidate
from src.infrastructure.llm.gemini_answer_provider import GeminiAnswerProvider


class FakeResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class FakeModels:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.last_kwargs = None

    async def generate_content(self, **kwargs):
        self.last_kwargs = kwargs
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, float):
                await asyncio.sleep(outcome)
                return FakeResponse(answer_candidate().model_dump_json())
            return outcome
        finally:
            self.active -= 1


class FakeAio:
    def __init__(self, models: FakeModels) -> None:
        self.models = models
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.aio = FakeAio(FakeModels(outcomes))


def test_gemini_provider_returns_structured_candidate_and_closes() -> None:
    async def scenario() -> None:
        client = FakeClient([FakeResponse(answer_candidate().model_dump_json())])
        provider = _provider(client)
        result = await provider.generate_structured(_request())
        await provider.aclose()
        await provider.aclose()
        assert result.claims[0].citation_ids == ["doc_art1"]
        assert client.aio.close_count == 1

    asyncio.run(scenario())


def test_gemini_provider_uses_api_compatible_json_schema() -> None:
    async def scenario() -> None:
        client = FakeClient([FakeResponse(answer_candidate().model_dump_json())])
        provider = _provider(client)

        await provider.generate_structured(_request())

        config = client.aio.models.last_kwargs["config"]
        schema = config["response_json_schema"]
        assert "additionalProperties" not in json.dumps(schema)
        assert config["response_mime_type"] == "application/json"

    asyncio.run(scenario())


def test_transient_rate_limit_retries_within_bound() -> None:
    async def scenario() -> None:
        client = FakeClient(
            [
                RuntimeError("429 RESOURCE_EXHAUSTED"),
                FakeResponse(answer_candidate().model_dump_json()),
            ]
        )
        provider = _provider(client, max_retries=1)
        result = await provider.generate_structured(_request())
        assert result.cannot_answer is False
        assert client.aio.models.calls == 2

    asyncio.run(scenario())


def test_authentication_error_fails_without_retry() -> None:
    async def scenario() -> None:
        client = FakeClient([RuntimeError("401 unauthorized")])
        provider = _provider(client, max_retries=2)
        with pytest.raises(AnswerProviderDependencyError):
            await provider.generate_structured(_request())
        assert client.aio.models.calls == 1

    asyncio.run(scenario())


def test_timeout_includes_provider_call() -> None:
    async def scenario() -> None:
        client = FakeClient([0.2])
        provider = _provider(client, timeout_seconds=0.02)
        with pytest.raises(AnswerProviderTimeoutError):
            await provider.generate_structured(_request())

    asyncio.run(scenario())


def test_malformed_output_is_typed() -> None:
    async def scenario() -> None:
        client = FakeClient([FakeResponse(json.dumps({"claims": []}))])
        provider = _provider(client)
        with pytest.raises(AnswerProviderOutputError):
            await provider.generate_structured(_request())

    asyncio.run(scenario())


def test_provider_concurrency_is_bounded() -> None:
    async def scenario() -> None:
        client = FakeClient([0.03, 0.03, 0.03])
        provider = _provider(client, max_concurrency=2)
        await asyncio.gather(
            *[provider.generate_structured(_request()) for _ in range(3)]
        )
        assert client.aio.models.peak == 2

    asyncio.run(scenario())


def _provider(
    client: FakeClient,
    *,
    timeout_seconds: float = 1,
    max_retries: int = 0,
    max_concurrency: int = 1,
) -> GeminiAnswerProvider:
    return GeminiAnswerProvider(
        api_key="test-only",
        model="gemini-test",
        config=GenerationConfig(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_concurrency=max_concurrency,
        ),
        client_factory=lambda _: client,
        generate_config_factory=lambda **kwargs: kwargs,
    )


def _request() -> ProviderAnswerRequest:
    return ProviderAnswerRequest(
        system_instruction="system",
        prompt="prompt",
    )
