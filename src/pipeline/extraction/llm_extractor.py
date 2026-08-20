"""LLM Information Extraction — Hỗ trợ đa provider (Gemini, MiniMax, Qwen, OpenAI).

Các hàm trong module này được giữ nguyên làm wrapper để tương thích ngược
với hệ thống cũ, bên dưới sẽ tự động điều phối cuộc gọi đến class provider
phù hợp dựa trên cấu hình settings.llm_provider.
"""

from __future__ import annotations

import logging

from src.pipeline.extraction.entity_normalization import normalize_entities_for_relations
from src.pipeline.extraction.models import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)
from src.pipeline.extraction.providers import get_provider
from src.pipeline.extraction.structural_context import ArticleExtractionContext

logger = logging.getLogger(__name__)


def extract_entities(
    article_text: str, *, context: ArticleExtractionContext
) -> list[ExtractedEntity]:
    """Pass 1 — trích entities (Document/Concept/Entity) được nhắc tới trong 1 Điều."""
    provider = get_provider()
    return provider.extract_entities(article_text, context=context)


def extract_relations(
    article_text: str,
    entities: list[ExtractedEntity],
    *,
    context: ArticleExtractionContext,
) -> list[ExtractedRelation]:
    """Pass 2 — trích relations giữa các entities đã tìm thấy ở Pass 1."""
    provider = get_provider()
    return provider.extract_relations(article_text, entities, context=context)


def extract_article(
    article_number: str, article_text: str, *, context: ArticleExtractionContext
) -> ExtractionResult:
    """Chạy đủ 2 pass cho 1 Article, gói kết quả lại làm input cho Step 3 Schema Validation."""
    provider = get_provider()
    logger.info(
        "Extracting entities for Điều %s sử dụng provider: %s",
        article_number,
        provider.__class__.__name__,
    )
    raw_entities, relations = provider.extract_article(article_text, context=context)
    entities = normalize_entities_for_relations(raw_entities)
    logger.info(
        "Điều %s: tìm thấy %d entities, %d relations",
        article_number,
        len(entities),
        len(relations),
    )
    return ExtractionResult(
        article_number=article_number,
        raw_entities=raw_entities,
        entities=entities,
        relations=relations,
        resolved_model=provider.resolved_model,
    )
