"""Gemini text-generation adapter conforming to ``TextGenerationPort``.

Default provider (free tier). It imports only the shared port + stdlib; the
``google-genai`` SDK is imported lazily so the module loads without it.
"""

from __future__ import annotations

from typing import Any, Callable

from src.infrastructure.llm.errors import (
    TextGenerationDependencyError,
    TextGenerationOutputError,
)
from src.shared.llm_ports import TextGenerationPort


class GeminiTextProvider(TextGenerationPort):
    """Adapter over ``google.genai`` synchronous content generation."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client_factory: Callable[[str], Any] | None = None,
        config_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise TextGenerationDependencyError("Gemini API key is required")
        if not model.strip():
            raise TextGenerationDependencyError("Gemini model is required")
        self._model = model
        self._client = (client_factory or _create_client)(api_key)
        self._config_factory = config_factory or _create_generate_config

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str:
        config = self._config_factory(
            system_instruction=system_prompt,
            temperature=temperature,
            response_mime_type=(
                "application/json" if response_format == "json" else None
            ),
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=config,
        )
        text = getattr(response, "text", None)
        if not text:
            raise TextGenerationOutputError("Gemini returned an empty text payload")
        return text


def _create_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:
        raise TextGenerationDependencyError(
            "Gemini text generation requires the google-genai package"
        ) from exc
    return genai.Client(api_key=api_key)


def _create_generate_config(**kwargs: Any) -> Any:
    try:
        from google.genai import types
    except ImportError as exc:
        raise TextGenerationDependencyError(
            "Gemini text generation requires the google-genai package"
        ) from exc
    cleaned = {key: value for key, value in kwargs.items() if value is not None}
    return types.GenerateContentConfig(**cleaned)
