"""Application adapter for Gemini exact-linear query planning."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from pydantic import ValidationError

from src.retrieval.planning.config import QueryPlannerConfig
from src.retrieval.planning.errors import (
    QueryPlannerDependencyError,
    QueryPlannerInvalidPlanError,
    QueryPlannerTimeoutError,
)
from src.retrieval.planning.models import UnlinkedSemanticPlan
from src.retrieval.planning.prompts import build_query_planner_request


logger = logging.getLogger(__name__)


class GeminiQueryPlanner:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        config: QueryPlannerConfig,
        client_factory: Callable[[str], Any] | None = None,
        generate_config_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise QueryPlannerDependencyError("Gemini API key is required")
        if not model.strip():
            raise QueryPlannerDependencyError("Gemini query planner model is required")
        self._model = model.strip()
        self._config = config
        self._capacity = asyncio.Semaphore(config.max_concurrency)
        self._client = (client_factory or _create_client)(api_key)
        self._generate_config_factory = generate_config_factory or _create_config
        self._closed = False

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    async def plan(self, query: str) -> UnlinkedSemanticPlan:
        if self._closed:
            raise QueryPlannerDependencyError("Gemini query planner is closed")
        request = build_query_planner_request(query)
        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async with self._capacity:
                    return await self._generate_with_retries(request)
        except TimeoutError as exc:
            raise QueryPlannerTimeoutError(
                f"Query planner exceeded {self._config.timeout_seconds:g} seconds"
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(getattr(self._client, "aio", None), "aclose", None)
        if close is not None:
            await close()

    async def _generate_with_retries(self, request) -> UnlinkedSemanticPlan:
        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            try:
                return await self._generate_once(request)
            except _TransientPlannerError:
                if attempt + 1 >= attempts:
                    raise QueryPlannerDependencyError(
                        "Gemini query planner remained unavailable after retries"
                    )
                await asyncio.sleep(0.25 * (2**attempt))
        raise AssertionError("Retry loop exhausted unexpectedly")

    async def _generate_once(self, request) -> UnlinkedSemanticPlan:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=request.prompt,
                config=self._generate_config_factory(
                    system_instruction=request.system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=_response_schema(),
                    temperature=self._config.temperature,
                    max_output_tokens=self._config.max_output_tokens,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _raise_provider_error(exc)
        try:
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, UnlinkedSemanticPlan):
                return parsed
            if parsed is not None:
                return UnlinkedSemanticPlan.model_validate(parsed)
            text = getattr(response, "text", None)
            if not text:
                raise QueryPlannerInvalidPlanError(
                    "Gemini returned an empty query plan"
                )
            return UnlinkedSemanticPlan.model_validate_json(text)
        except ValidationError as exc:
            logger.warning(
                "Gemini query plan validation failed: model=%s error_types=%s",
                self._model,
                sorted({error["type"] for error in exc.errors()}),
            )
            raise QueryPlannerInvalidPlanError(
                "Gemini returned an invalid query plan"
            ) from exc


class _TransientPlannerError(RuntimeError):
    pass


def _response_schema() -> dict[str, Any]:
    return _strip_additional_properties(UnlinkedSemanticPlan.model_json_schema())


def _strip_additional_properties(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_additional_properties(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, list):
        return [_strip_additional_properties(item) for item in value]
    return value


def _create_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as exc:
        raise QueryPlannerDependencyError(
            "Gemini query planning requires google-genai"
        ) from exc
    return genai.Client(api_key=api_key)


def _create_config(**kwargs: Any) -> Any:
    try:
        from google.genai import types
    except ImportError as exc:
        raise QueryPlannerDependencyError(
            "Gemini query planning requires google-genai"
        ) from exc
    return types.GenerateContentConfig(**kwargs)


def _raise_provider_error(exc: Exception) -> None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        if code in {408, 409, 429} or 500 <= code < 600:
            raise _TransientPlannerError(type(exc).__name__) from exc
        if 400 <= code < 500:
            raise QueryPlannerDependencyError(
                "Gemini query planner request/authentication/model failed"
            ) from exc
    if isinstance(exc, (ConnectionError, TimeoutError)):
        raise _TransientPlannerError(type(exc).__name__) from exc
    message = str(exc).lower()
    if any(marker in message for marker in ("429", "500", "502", "503", "504")):
        raise _TransientPlannerError(type(exc).__name__) from exc
    raise QueryPlannerDependencyError(
        f"Gemini query planner failed: {type(exc).__name__}"
    ) from exc
