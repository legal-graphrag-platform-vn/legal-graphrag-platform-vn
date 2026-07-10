from __future__ import annotations

import json
import logging
import re
from openai import OpenAI
from openai import APIError as OpenAIAPIError
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
    retry=retry_if_exception_type(OpenAIAPIError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)


class OpenAICompatibleProvider(BaseProvider):
    """Generic provider cho các API tương thích với OpenAI (MiniMax, Qwen, OpenAI, v.v.)."""

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type.lower()

    def _clean_json_text(self, text: str) -> str:
        # 1. Loại bỏ các khối suy nghĩ <think>...</think> của các reasoning models (vd DeepSeek-R1, MiniMax-M3)
        text = re.sub(r'(?is)<think>.*?</think>', '', text)
        # 2. Loại bỏ các block markdown code ```json ... ``` hoặc ``` ... ```
        text = re.sub(r'(?is)```(?:json)?\s*(.*?)\s*```', r'\1', text)
        return text.strip()

    def _normalize_id(self, id_str: str) -> str:
        """Chuẩn hóa ID về dạng snake_case không dấu để tuân thủ pattern '^[a-z0-9_]+$'."""
        s = id_str.lower().strip()
        # Loại bỏ dấu tiếng Việt
        s = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', s)
        s = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', s)
        s = re.sub(r'[ìíịỉĩ]', 'i', s)
        s = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', s)
        s = re.sub(r'[ùúụủũưừứựửữ]', 'u', s)
        s = re.sub(r'[ỳýỵỷỹ]', 'y', s)
        s = re.sub(r'[đ]', 'd', s)
        # Thay thế ký tự đặc biệt khác bằng gạch dưới
        s = re.sub(r'[^a-z0-9_]', '_', s)
        # Thu gọn nhiều gạch dưới
        s = re.sub(r'_+', '_', s)
        return s.strip('_')

    def _get_client_and_model(self) -> tuple[OpenAI, str]:
        api_key = settings.require_api_key()
        if self.provider_type == "minimax":
            base_url = settings.minimax_base_url
            model = settings.minimax_model
        elif self.provider_type == "qwen":
            base_url = settings.qwen_base_url
            model = settings.qwen_model
        elif self.provider_type == "ollama":
            base_url = settings.ollama_base_url
            model = settings.ollama_model
        else:  # openai hoặc provider chung
            base_url = settings.openai_base_url if settings.openai_base_url else None
            model = settings.openai_model

        client = OpenAI(api_key=api_key, base_url=base_url)
        return client, model

    @_retry_llm_call
    def extract_entities(self, article_text: str) -> list[ExtractedEntity]:
        client, model = self._get_client_and_model()
        prompt = ENTITY_EXTRACTION_PROMPT.format(article_text=article_text)

        system_instruction = (
            "Bạn là trợ lý ảo hỗ trợ trích xuất thông tin pháp luật Việt Nam. "
            "Bạn bắt buộc trả về một đối tượng JSON hợp lệ khớp chính xác với định dạng được yêu cầu."
        )

        try:
            # Thử sử dụng OpenAI Structured Outputs (beta.chat.completions.parse)
            logger.info("Đang gọi OpenAI API với Structured Outputs (Beta Parse)")
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format=EntityExtractionResult,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError("Kết quả trả về rỗng hoặc không thể parse.")
            return parsed.entities
        except Exception as e:
            logger.warning(
                "Structured Outputs không được hỗ trợ bởi provider này, chuyển sang fallback JSON mode. Lỗi: %s", e
            )
            # Fallback sang standard JSON mode
            schema_desc = EntityExtractionResult.model_json_schema()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"{system_instruction}\nĐầu ra JSON của bạn phải tuân theo JSON Schema này:\n{schema_desc}",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("API trả về nội dung rỗng.")
            cleaned = self._clean_json_text(content)
            data = json.loads(cleaned)
            if "entities" in data and isinstance(data["entities"], list):
                for ent in data["entities"]:
                    if isinstance(ent, dict) and "id" in ent:
                        ent["id"] = self._normalize_id(ent["id"])
            result = EntityExtractionResult.model_validate(data)
            return result.entities

    @_retry_llm_call
    def extract_relations(self, article_text: str, entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
        if not entities:
            return []
        client, model = self._get_client_and_model()
        entities_json = EntityExtractionResult(entities=entities).model_dump_json()
        prompt = RELATION_EXTRACTION_PROMPT.format(article_text=article_text, entities_json=entities_json)

        system_instruction = (
            "Bạn là trợ lý ảo hỗ trợ trích xuất thông tin pháp luật Việt Nam. "
            "Bạn bắt buộc trả về một đối tượng JSON hợp lệ khớp chính xác với định dạng được yêu cầu."
        )

        try:
            # Thử sử dụng OpenAI Structured Outputs (beta.chat.completions.parse)
            logger.info("Đang gọi OpenAI API với Structured Outputs (Beta Parse)")
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format=RelationExtractionResult,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise ValueError("Kết quả trả về rỗng hoặc không thể parse.")
            return parsed.relations
        except Exception as e:
            logger.warning(
                "Structured Outputs không được hỗ trợ bởi provider này, chuyển sang fallback JSON mode. Lỗi: %s", e
            )
            # Fallback sang standard JSON mode
            schema_desc = RelationExtractionResult.model_json_schema()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"{system_instruction}\nĐầu ra JSON của bạn phải tuân theo JSON Schema này:\n{schema_desc}",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("API trả về nội dung rỗng.")
            cleaned = self._clean_json_text(content)
            data = json.loads(cleaned)
            if "relations" in data and isinstance(data["relations"], list):
                for rel in data["relations"]:
                    if isinstance(rel, dict):
                        if "head" in rel:
                            rel["head"] = self._normalize_id(rel["head"])
                        if "tail" in rel:
                            rel["tail"] = self._normalize_id(rel["tail"])
            result = RelationExtractionResult.model_validate(data)
            return result.relations
