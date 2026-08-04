"""Pydantic models cho LLM Information Extraction (Step 2).

Khớp ENTITY_SCHEMA / RELATION_SCHEMA trong plans/04_graph_construction_pipeline.md.
Dùng trực tiếp làm `response_schema` cho Gemini structured output (`google-genai`)
-> Gemini bị ép trả đúng JSON shape ở API level, giảm lỗi "JSON parse fail".
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from src.pipeline.parser.models import LegalNumber

EntityType = Literal[
    "Document",
    "Part",
    "Chapter",
    "Section",
    "Subsection",
    "Article",
    "Clause",
    "Point",
    "Concept",
    "Entity",
    "Action",
]

# Canonical active-voice relation types from plans/legal_ontology.md v1.4.0.
RelationType = Literal[
    "CONTAINS",
    "AMENDS",
    "REPEALS",
    "REPLACES",
    "GUIDES",
    "REFERS_TO",
    "DEFINES",
    "REGULATES",
    "REQUIRES",
]


class ExtractedEntity(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$", description="unique, snake_case")
    type: EntityType
    label: str = Field(min_length=1)

    @field_validator("id", mode="before")
    @classmethod
    def canonicalize_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        decomposed = unicodedata.normalize("NFD", value)
        without_marks = "".join(
            char for char in decomposed if unicodedata.category(char) != "Mn"
        )
        ascii_text = without_marks.replace("đ", "d").replace("Đ", "D").lower()
        return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


class EntityExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)


class ExtractedRelation(BaseModel):
    head: str
    relation: RelationType
    tail: str
    evidence: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RelationExtractionResult(BaseModel):
    relations: list[ExtractedRelation] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Output gộp của 2-pass extraction cho 1 Article — input cho Step 3 Schema Validation."""

    article_number: LegalNumber
    raw_entities: list[ExtractedEntity] = Field(default_factory=list)
    provider: str | None = None
    configured_model: str | None = None
    resolved_model: str | None = None
    completed_at: str | None = None
    checkpoint_id: str | None = None
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
