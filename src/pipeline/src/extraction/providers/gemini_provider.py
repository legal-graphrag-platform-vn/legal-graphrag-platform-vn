from __future__ import annotations

import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings
from src.extraction.models import (
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
    RelationExtractionResult,
)
from src.extraction.prompts import ENTITY_EXTRACTION_PROMPT, RELATION_EXTRACTION_PROMPT
from src.extraction.providers.base import BaseProvider

logger = logging.getLogger(__name__)

_retry_llm_call = retry(
    retry=retry_if_exception_type(APIError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)


class GeminiProvider(BaseProvider):
    """Provider trích xuất sử dụng Google Gemini SDK."""

    def _client(self) -> genai.Client:
        return genai.Client(api_key=settings.require_api_key())

    @_retry_llm_call
    def extract_entities(self, article_text: str) -> list[ExtractedEntity]:
        client = self._client()
        prompt = ENTITY_EXTRACTION_PROMPT.format(article_text=article_text)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EntityExtractionResult,
            ),
        )
        result = EntityExtractionResult.model_validate_json(response.text)
        return result.entities

    @_retry_llm_call
    def extract_relations(self, article_text: str, entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
        if not entities:
            return []
        client = self._client()
        entities_json = EntityExtractionResult(entities=entities).model_dump_json()
        prompt = RELATION_EXTRACTION_PROMPT.format(article_text=article_text, entities_json=entities_json)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RelationExtractionResult,
            ),
        )
        result = RelationExtractionResult.model_validate_json(response.text)
        return result.relations
