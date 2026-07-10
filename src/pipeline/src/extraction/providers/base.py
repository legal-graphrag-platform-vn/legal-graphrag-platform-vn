from __future__ import annotations
from abc import ABC, abstractmethod
from src.extraction.models import ExtractedEntity, ExtractedRelation

class BaseProvider(ABC):
    """Lớp cơ sở cho các LLM Extractor Providers."""

    @abstractmethod
    def extract_entities(self, article_text: str) -> list[ExtractedEntity]:
        """Trích xuất các thực thể (entities) từ điều luật."""
        pass

    @abstractmethod
    def extract_relations(self, article_text: str, entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
        """Trích xuất mối quan hệ (relations) giữa các thực thể đã xác định."""
        pass
