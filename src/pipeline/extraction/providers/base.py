from __future__ import annotations
from abc import ABC, abstractmethod
from src.pipeline.extraction.models import ExtractedEntity, ExtractedRelation
from src.pipeline.extraction.structural_context import ArticleExtractionContext


class ExtractionProviderError(RuntimeError):
    """Base error for extraction provider failures."""


class FatalExtractionProviderError(ExtractionProviderError):
    """Provider failure that must abort the complete extraction run."""


class RetryableExtractionProviderError(ExtractionProviderError):
    """Transient provider failure that may be retried locally."""

class BaseProvider(ABC):
    """Lớp cơ sở cho các LLM Extractor Providers."""

    resolved_model: str | None = None

    @abstractmethod
    def extract_entities(self, article_text: str, *, context: ArticleExtractionContext) -> list[ExtractedEntity]:
        """Trích xuất các thực thể (entities) từ điều luật."""
        pass

    @abstractmethod
    def extract_relations(
        self, article_text: str, entities: list[ExtractedEntity], *, context: ArticleExtractionContext
    ) -> list[ExtractedRelation]:
        """Trích xuất mối quan hệ (relations) giữa các thực thể đã xác định."""
        pass
