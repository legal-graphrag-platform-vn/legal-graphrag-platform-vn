"""LLM Information Extraction — Hỗ trợ đa provider (Gemini, MiniMax, Qwen, OpenAI).

Các hàm trong module này được giữ nguyên làm wrapper để tương thích ngược
với hệ thống cũ, bên dưới sẽ tự động điều phối cuộc gọi đến class provider
phù hợp dựa trên cấu hình settings.llm_provider.
"""

from __future__ import annotations

import logging

from src.extraction.models import ExtractedEntity, ExtractedRelation, ExtractionResult
from src.extraction.providers import get_provider

logger = logging.getLogger(__name__)


def extract_entities(article_text: str) -> list[ExtractedEntity]:
    """Pass 1 — trích entities (Document/Concept/Entity) được nhắc tới trong 1 Điều."""
    provider = get_provider()
    return provider.extract_entities(article_text)


def extract_relations(article_text: str, entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
    """Pass 2 — trích relations giữa các entities đã tìm thấy ở Pass 1."""
    provider = get_provider()
    return provider.extract_relations(article_text, entities)


def extract_article(article_number: int, article_text: str) -> ExtractionResult:
    """Chạy đủ 2 pass cho 1 Article, gói kết quả lại làm input cho Step 3 Schema Validation."""
    provider = get_provider()
    logger.info(
        "Extracting entities for Điều %d sử dụng provider: %s",
        article_number,
        provider.__class__.__name__,
    )
    entities = extract_entities(article_text)
    logger.info("Điều %d: tìm thấy %d entities, đang extract relations", article_number, len(entities))
    relations = extract_relations(article_text, entities)
    logger.info("Điều %d: tìm thấy %d relations", article_number, len(relations))
    return ExtractionResult(article_number=article_number, entities=entities, relations=relations)
