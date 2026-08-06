"""Ollama local text-generation adapter conforming to ``TextGenerationPort``.

Talks to the Ollama ``/api/chat`` endpoint over stdlib HTTP, so it adds no
dependency. Intended for local Qwen 3B/4B/7B models. The transport is injectable
for offline testing.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from src.infrastructure.llm.errors import (
    TextGenerationDependencyError,
    TextGenerationOutputError,
)
from src.shared.llm_ports import TextGenerationPort

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]

_DEFAULT_HOST = "http://localhost:11434"


class OllamaTextProvider(TextGenerationPort):
    """Adapter over a local Ollama chat endpoint."""

    def __init__(
        self,
        *,
        model: str,
        host: str = _DEFAULT_HOST,
        timeout: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        if not model.strip():
            raise TextGenerationDependencyError("Ollama model is required")
        self._model = model
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._transport = transport or _http_post_json

    @property
    def provider_name(self) -> str:
        return "ollama"

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
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format == "json":
            payload["format"] = "json"

        data = self._transport(f"{self._host}/api/chat", payload, self._timeout)
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not content:
            raise TextGenerationOutputError("Ollama returned an empty message content")
        return content


def _http_post_json(
    url: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TextGenerationDependencyError(
            f"Ollama endpoint unavailable at {url}: {exc}"
        ) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise TextGenerationOutputError(
            "Ollama returned a non-JSON response body"
        ) from exc
