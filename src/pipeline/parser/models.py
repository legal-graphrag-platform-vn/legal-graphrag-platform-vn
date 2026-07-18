"""Pydantic models cho output của Hierarchy Parser.

Khớp đúng Output Format quy định trong plans/04_graph_construction_pipeline.md
và ID Convention trong plans/legal_ontology.md. Các model này được
tái dùng làm input cho LLM Extraction (extraction/llm_extractor.py) để tránh
định nghĩa schema trùng lặp ở nhiều tầng.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

LegalNumber = Annotated[str, BeforeValidator(lambda value: str(value).strip())]


class Point(BaseModel):
    """Điểm — đơn vị nhỏ nhất trong cấu trúc văn bản pháp luật VN."""

    label: str = Field(description="Nhãn điểm, ví dụ 'a'")
    content: str
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)


class Clause(BaseModel):
    """Khoản — unit cơ bản nhất cho retrieval (ADR-02)."""

    number: LegalNumber
    content: str
    points: list[Point] = Field(default_factory=list)
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def point_labels_must_be_unique(self) -> "Clause":
        seen: set[str] = set()
        duplicates: set[str] = set()
        for point in self.points:
            label = point.label.strip().lower()
            if label in seen:
                duplicates.add(label)
            seen.add(label)
        if duplicates:
            labels = ", ".join(sorted(duplicates))
            raise ValueError(
                f"Duplicate Point label(s) in Clause {self.number}: {labels}"
            )
        return self


class Article(BaseModel):
    """Điều."""

    number: LegalNumber
    title: str | None = None
    content_raw: str
    chapter: str | None = Field(default=None, description="Số chương La Mã, vd 'II'")
    chapter_title: str | None = None
    clauses: list[Clause] = Field(default_factory=list)
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)


class UnparsedSection(BaseModel):
    """Losslessly preserved source section outside the active graph ontology."""

    section_type: Literal["APPENDIX"]
    heading: str
    content_raw: str
    source_document_id: str
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentInfo(BaseModel):
    """Metadata gốc của văn bản (id, số hiệu, ngày tháng)."""

    id: str = Field(description="Canonical graph ID theo ontology, vd 'ldn_2020'")
    title: str
    number: str = Field(description="Số hiệu văn bản, vd '59/2020/QH14'")
    doc_type: str = Field(
        description="Document type: Law|Decree|Circular|Resolution|Decision"
    )
    normative: bool = Field(
        default=True,
        description="True for normative legal documents in the selected corpus",
    )
    issued_by: str | None = None
    issued_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    issuer_name: str | None = None
    legal_status: str = Field(default="ACTIVE")


class ParsedDocument(BaseModel):
    """Output đầy đủ của Hierarchy Parser — input cho Step 2 LLM Extraction."""

    document: DocumentInfo
    articles: list[Article] = Field(default_factory=list)
    unparsed_sections: list[UnparsedSection] = Field(default_factory=list)
