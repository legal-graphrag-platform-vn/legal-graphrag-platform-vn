"""Gemini structured-output adapter with bounded async execution."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from pydantic import ValidationError

from src.generation.config import GenerationConfig
from src.generation.errors import (
    AnswerProviderDependencyError,
    AnswerProviderOutputError,
    AnswerProviderTimeoutError,
)
from src.generation.models import AnswerCandidate, ProviderAnswerRequest


class GeminiAnswerProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        config: GenerationConfig,
        client_factory: Callable[[str], Any] | None = None,
        generate_config_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise AnswerProviderDependencyError("Gemini API key is required")
        if not model.strip():
            raise AnswerProviderDependencyError("Gemini answer model is required")
        self._model = model
        self._config = config
        self._capacity = asyncio.Semaphore(config.max_concurrency)
        self._client = (client_factory or _create_client)(api_key)
        self._generate_config_factory = (
            generate_config_factory or _create_generate_config
        )
        self._closed = False

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_structured(
        self,
        request: ProviderAnswerRequest,
    ) -> AnswerCandidate:
        if self._closed:
            raise AnswerProviderDependencyError("Gemini answer provider is closed")
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async with self._capacity:
                    return await self._generate_with_retries(request)
        except TimeoutError as exc:
            raise AnswerProviderTimeoutError(
                f"Answer provider exceeded {self._config.timeout_seconds:g} seconds"
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        aio = getattr(self._client, "aio", None)
        close = getattr(aio, "aclose", None)
        if close is not None:
            await close()

    async def _generate_with_retries(
        self,
        request: ProviderAnswerRequest,
    ) -> AnswerCandidate:
        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            try:
                return await self._generate_once(request)
            except _TransientProviderError:
                if attempt + 1 >= attempts:
                    raise AnswerProviderDependencyError(
                        "Gemini answer provider remained unavailable after retries"
                    )
                await asyncio.sleep(0.25 * (2**attempt))
        raise AssertionError("Retry loop exhausted unexpectedly")

    async def _generate_once(
        self,
        request: ProviderAnswerRequest,
    ) -> AnswerCandidate:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=request.prompt,
                config=self._generate_config_factory(
                    system_instruction=request.system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=_gemini_response_schema(),
                    temperature=self._config.temperature,
                    max_output_tokens=self._config.max_output_tokens,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _raise_provider_error(exc)
        text = getattr(response, "text", None)
        if not text:
            raise AnswerProviderOutputError("Gemini returned an empty answer payload")
        try:
            return AnswerCandidate.model_validate_json(text)
        except ValidationError as exc:
            raise AnswerProviderOutputError(
                "Gemini returned an invalid structured answer"
            ) from exc


class _TransientProviderError(RuntimeError):
    pass


def _gemini_response_schema() -> dict[str, Any]:
    """Return the strict domain schema without unsupported Gemini keywords."""
    return _without_additional_properties(AnswerCandidate.model_json_schema())


def _without_additional_properties(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_additional_properties(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, list):
        return [_without_additional_properties(item) for item in value]
    return value


def _create_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:
        raise AnswerProviderDependencyError(
            "Gemini answer generation requires google-genai"
        ) from exc
    return genai.Client(api_key=api_key)


def _create_generate_config(**kwargs: Any) -> Any:
    try:
        from google.genai import types
    except ImportError as exc:
        raise AnswerProviderDependencyError(
            "Gemini answer generation requires google-genai"
        ) from exc
    return types.GenerateContentConfig(**kwargs)


def _raise_provider_error(exc: Exception) -> None:
    message = str(exc).lower()
    if any(
        marker in message
        for marker in ("429", "resource_exhausted", "500", "502", "503", "504")
    ):
        raise _TransientProviderError(type(exc).__name__) from exc
    if any(
        marker in message
        for marker in (
            "401",
            "403",
            "404",
            "unauthorized",
            "permission_denied",
            "api key",
            "not_found",
            "not found",
        )
    ):
        raise AnswerProviderDependencyError(
            "Gemini answer provider authentication/model configuration failed"
        ) from exc
    raise AnswerProviderDependencyError(
        f"Gemini answer provider failed: {type(exc).__name__}"
    ) from exc
