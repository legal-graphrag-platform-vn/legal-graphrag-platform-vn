"""LLM Information Extraction — Hỗ trợ đa provider (Gemini, MiniMax, Qwen, OpenAI).

Các hàm trong module này được giữ nguyên làm wrapper để tương thích ngược
với hệ thống cũ, bên dưới sẽ tự động điều phối cuộc gọi đến class provider
phù hợp dựa trên cấu hình settings.llm_provider.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from src.pipeline.extraction.models import ExtractedEntity, ExtractedRelation, ExtractionResult
from src.pipeline.extraction.providers import get_provider
from src.pipeline.extraction.structural_context import ArticleExtractionContext

logger = logging.getLogger(__name__)


def extract_entities(article_text: str, *, context: ArticleExtractionContext) -> list[ExtractedEntity]:
    """Pass 1 — trích entities (Document/Concept/Entity) được nhắc tới trong 1 Điều."""
    provider = get_provider()
    return provider.extract_entities(article_text, context=context)


def extract_relations(
    article_text: str, entities: list[ExtractedEntity], *, context: ArticleExtractionContext
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
    raw_entities = provider.extract_entities(article_text, context=context)
    entities = normalize_entities_for_relations(raw_entities)
    logger.info("Điều %s: tìm thấy %d entities, đang extract relations", article_number, len(entities))
    relations = provider.extract_relations(article_text, entities, context=context)
    logger.info("Điều %s: tìm thấy %d relations", article_number, len(relations))
    return ExtractionResult(
        article_number=article_number,
        raw_entities=raw_entities,
        entities=entities,
        relations=relations,
        resolved_model=provider.resolved_model,
    )


def normalize_entities_for_relations(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    """Canonicalize semantic IDs before pass 2 and omit parser-owned local structure."""
    normalized: dict[str, ExtractedEntity] = {}
    for entity in entities:
        if entity.type in {"Article", "Chapter", "Clause", "Point"}:
            continue
        canonical_id = _semantic_id(entity.label) if entity.type in {"Concept", "Entity", "Action"} else entity.id
        candidate = ExtractedEntity(id=canonical_id, type=entity.type, label=entity.label)
        existing = normalized.get(canonical_id)
        if existing is not None and existing != candidate:
            raise ValueError(f"Conflicting entity normalization for {canonical_id}")
        normalized[canonical_id] = candidate
    return list(normalized.values())


def _semantic_id(label: str) -> str:
    decomposed = unicodedata.normalize("NFD", label)
    without_marks = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    ascii_text = without_marks.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_") or "unknown"
