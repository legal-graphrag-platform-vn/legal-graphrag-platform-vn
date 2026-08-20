"""Shared entity ID normalization — dùng chung giữa llm_extractor.py và providers/*.

Tách riêng để tránh circular import: providers/base.py cần chuẩn hóa entities
trước khi gọi extract_relations, còn llm_extractor.py import providers.
"""

from __future__ import annotations

import re
import unicodedata

from src.pipeline.extraction.models import ExtractedEntity


def normalize_entities_for_relations(
    entities: list[ExtractedEntity],
) -> list[ExtractedEntity]:
    """Canonicalize semantic IDs before pass 2 and omit parser-owned local structure."""
    normalized: dict[str, ExtractedEntity] = {}
    for entity in entities:
        if entity.type in {
            "Part",
            "Chapter",
            "Section",
            "Subsection",
            "Article",
            "Clause",
            "Point",
        }:
            continue
        canonical_id = (
            _semantic_id(entity.label)
            if entity.type in {"Concept", "Entity", "Action"}
            else entity.id
        )
        candidate = ExtractedEntity(
            id=canonical_id, type=entity.type, label=entity.label
        )
        existing = normalized.get(canonical_id)
        if existing is None:
            normalized[canonical_id] = candidate
        else:
            # Deterministically resolve duplicate canonical_id from LLM output variations
            preferred_type = candidate.type if candidate.type == "Entity" and existing.type != "Entity" else existing.type
            preferred_label = candidate.label if len(candidate.label) > len(existing.label) else existing.label
            normalized[canonical_id] = ExtractedEntity(id=canonical_id, type=preferred_type, label=preferred_label)
    return list(normalized.values())


def _semantic_id(label: str) -> str:
    decomposed = unicodedata.normalize("NFD", label)
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    ascii_text = without_marks.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_") or "unknown"
