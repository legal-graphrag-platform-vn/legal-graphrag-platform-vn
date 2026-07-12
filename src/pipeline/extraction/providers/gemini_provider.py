from __future__ import annotations

import logging
import threading
import time
from google import genai
from google.genai import types
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from src.pipeline.config import settings
from src.pipeline.extraction.models import (
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
    RelationExtractionResult,
)
from src.pipeline.extraction.prompts import ENTITY_EXTRACTION_PROMPT, RELATION_EXTRACTION_PROMPT
from src.pipeline.extraction.providers.base import (
    BaseProvider,
    FatalExtractionProviderError,
    RetryableExtractionProviderError,
)
from src.pipeline.extraction.structural_context import ArticleExtractionContext

logger = logging.getLogger(__name__)
_request_lock = threading.Lock()
_last_request_at = 0.0

_retry_llm_call = retry(
    retry=retry_if_exception_type(RetryableExtractionProviderError),
    stop=stop_after_attempt(8),
    wait=wait_random_exponential(multiplier=2, min=10, max=180),
    before_sleep=lambda retry_state: logger.warning(
        "Gemini request bị rate-limit; retry lần %d sau %.1f giây",
        retry_state.attempt_number + 1,
        retry_state.next_action.sleep,
    ),
    reraise=True,
)


class GeminiProvider(BaseProvider):
    """Provider trích xuất sử dụng Google Gemini SDK."""

    def _client(self) -> genai.Client:
        return genai.Client(api_key=settings.require_api_key())

    @_retry_llm_call
    def extract_entities(self, article_text: str, *, context: ArticleExtractionContext) -> list[ExtractedEntity]:
        client = self._client()
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            article_text=article_text, structural_context=context.to_prompt_json()
        )
        try:
            _wait_for_request_slot()
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EntityExtractionResult,
                ),
            )
            self.resolved_model = response.model_version or settings.gemini_model
        except Exception as exc:
            _raise_classified_provider_error(exc, settings.gemini_model)
        result = EntityExtractionResult.model_validate_json(response.text)
        return result.entities

    @_retry_llm_call
    def extract_relations(
        self, article_text: str, entities: list[ExtractedEntity], *, context: ArticleExtractionContext
    ) -> list[ExtractedRelation]:
        client = self._client()
        entities_json = EntityExtractionResult(entities=entities).model_dump_json()
        prompt = RELATION_EXTRACTION_PROMPT.format(
            article_text=article_text,
            entities_json=entities_json,
            structural_context=context.to_prompt_json(),
        )
        try:
            _wait_for_request_slot()
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RelationExtractionResult,
                ),
            )
            self.resolved_model = response.model_version or settings.gemini_model
        except Exception as exc:
            _raise_classified_provider_error(exc, settings.gemini_model)
        result = RelationExtractionResult.model_validate_json(response.text)
        return result.relations


def _raise_classified_provider_error(exc: Exception, model: str) -> None:
    message = str(exc)
    normalized = message.lower()
    if any(marker in normalized for marker in ("429", "resource_exhausted")):
        hard_quota_markers = ("perday", "per day", "daily", "limit: 0")
        if any(marker in normalized for marker in hard_quota_markers):
            raise FatalExtractionProviderError(
                f"Fatal Gemini provider error: reason=quota_exhausted, model={model!r}"
            ) from exc
        raise RetryableExtractionProviderError(
            f"Retryable Gemini provider error: reason=rate_limited, model={model!r}"
        ) from exc

    fatal_reasons = (
        (("404", "not_found", "not found", "no longer available"), "model_unavailable"),
        (("401", "unauthorized", "api key"), "authentication_failed"),
        (("403", "permission_denied", "permission denied"), "permission_denied"),
    )
    for markers, reason in fatal_reasons:
        if not any(marker in normalized for marker in markers):
            continue
        raise FatalExtractionProviderError(
            f"Fatal Gemini provider error: reason={reason}, model={model!r}"
        ) from exc
    raise RetryableExtractionProviderError(
        f"Retryable Gemini provider error for model={model!r}: {type(exc).__name__}"
    ) from exc


def _wait_for_request_slot() -> None:
    global _last_request_at
    interval = settings.gemini_min_request_interval_seconds
    if interval <= 0:
        return
    with _request_lock:
        now = time.monotonic()
        remaining = interval - (now - _last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        _last_request_at = time.monotonic()
