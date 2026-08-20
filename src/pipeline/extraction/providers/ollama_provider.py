from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.pipeline.config import settings
from src.pipeline.extraction.models import (
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
    RelationExtractionResult,
)
from src.pipeline.extraction.prompts import ENTITY_EXTRACTION_PROMPT, RELATION_EXTRACTION_PROMPT
from src.pipeline.extraction.providers.base import BaseProvider
from src.pipeline.extraction.structural_context import ArticleExtractionContext

logger = logging.getLogger(__name__)

_retry_llm_call = retry(
    retry=retry_if_exception_type((httpx.HTTPError, json.JSONDecodeError, ValidationError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)


class OllamaProvider(BaseProvider):
    """Provider chuyên dụng cho Ollama Server hỗ trợ thinking models và native JSON mode."""

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        # Nếu base_url có đuôi /v1 thì đổi thành API gốc của Ollama
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = settings.ollama_model
        self.resolved_model = self.model

    def _normalize_id(self, id_str: str) -> str:
        """Chuẩn hóa ID về dạng snake_case không dấu để tuân thủ pattern '^[a-z0-9_]+$'."""
        s = id_str.lower().strip()
        s = re.sub(r"[àáạảãâầấậẩẫăằắặẳẵ]", "a", s)
        s = re.sub(r"[èéẹẻẽêềếệểễ]", "e", s)
        s = re.sub(r"[ìíịỉĩ]", "i", s)
        s = re.sub(r"[òóọỏõôồốộổỗơờớợởỡ]", "o", s)
        s = re.sub(r"[ùúụủũưừứựửữ]", "u", s)
        s = re.sub(r"[ỳýỵỷỹ]", "y", s)
        s = re.sub(r"[đ]", "d", s)
        s = re.sub(r"[^a-z0-9_]", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("_")

    def _clean_json_text(self, text: str) -> str:
        text = re.sub(r"(?is)<think>.*?</think>", "", text)
        text = re.sub(r"(?is)```(?:json)?\s*(.*?)\s*```", r"\1", text)
        return text.strip()

    @_retry_llm_call
    def extract_entities(
        self, article_text: str, *, context: ArticleExtractionContext
    ) -> list[ExtractedEntity]:
        prompt = ENTITY_EXTRACTION_PROMPT.format(
            article_text=article_text, structural_context=context.to_prompt_json()
        )
        system_instruction = (
            "Bạn là trợ lý ảo hỗ trợ trích xuất thông tin pháp luật Việt Nam. "
            "Bạn bắt buộc trả về một đối tượng JSON hợp lệ khớp chính xác với định dạng được yêu cầu."
        )
        schema_desc = EntityExtractionResult.model_json_schema()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_instruction}\nĐầu ra JSON của bạn phải tuân theo JSON Schema này:\n{schema_desc}",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 2048},
        }

        endpoint = f"{self.base_url}/api/chat"
        logger.info("Đang gọi Ollama API (/api/chat) cho thực thể: %s", self.model)

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
            res_data = response.json()

        content = res_data.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Ollama trả về nội dung rỗng.")

        cleaned = self._clean_json_text(content)
        data = json.loads(cleaned)

        if "entities" in data and isinstance(data["entities"], list):
            for ent in data["entities"]:
                if isinstance(ent, dict):
                    ent["id"] = self._normalize_id(str(ent.get("id") or ent.get("label", "")))

        result = EntityExtractionResult.model_validate(data)
        return result.entities

    @_retry_llm_call
    def extract_relations(
        self,
        article_text: str,
        entities: list[ExtractedEntity],
        *,
        context: ArticleExtractionContext,
    ) -> list[ExtractedRelation]:
        entities_json = EntityExtractionResult(entities=entities).model_dump_json()
        prompt = RELATION_EXTRACTION_PROMPT.format(
            article_text=article_text,
            entities_json=entities_json,
            structural_context=context.to_prompt_json(),
        )
        system_instruction = (
            "Bạn là trợ lý ảo hỗ trợ trích xuất thông tin pháp luật Việt Nam. "
            "Bạn bắt buộc trả về một đối tượng JSON hợp lệ khớp chính xác với định dạng được yêu cầu."
        )
        schema_desc = RelationExtractionResult.model_json_schema()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_instruction}\nĐầu ra JSON của bạn phải tuân theo JSON Schema này:\n{schema_desc}",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 2560},
        }

        endpoint = f"{self.base_url}/api/chat"
        logger.info("Đang gọi Ollama API (/api/chat) cho quan hệ: %s", self.model)

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
            res_data = response.json()

        content = res_data.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Ollama trả về nội dung rỗng.")

        cleaned = self._clean_json_text(content)
        data = json.loads(cleaned)

        if "relations" in data and isinstance(data["relations"], list):
            for rel in data["relations"]:
                if isinstance(rel, dict):
                    if "source_id" in rel:
                        rel["source_id"] = self._normalize_id(rel["source_id"])
                    if "target_id" in rel:
                        rel["target_id"] = self._normalize_id(rel["target_id"])

        result = RelationExtractionResult.model_validate(data)
        return result.relations
