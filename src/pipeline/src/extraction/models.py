"""Pydantic models cho LLM Information Extraction (Step 2).

Khớp ENTITY_SCHEMA / RELATION_SCHEMA trong plans/04_graph_construction_pipeline.md.
Dùng trực tiếp làm `response_schema` cho Gemini structured output (`google-genai`)
-> Gemini bị ép trả đúng JSON shape ở API level, giảm lỗi "JSON parse fail".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["Document", "Chapter", "Article", "Clause", "Point", "Concept", "Entity", "Action"]

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

    article_number: int
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
