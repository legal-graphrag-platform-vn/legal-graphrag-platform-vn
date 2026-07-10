"""Pydantic models cho output của Hierarchy Parser.

Khớp đúng Output Format quy định trong plans/04_graph_construction_pipeline.md
và ID Convention trong plans/legal_ontology.md. Các model này được
tái dùng làm input cho LLM Extraction (extraction/llm_extractor.py) để tránh
định nghĩa schema trùng lặp ở nhiều tầng.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

class Point(BaseModel):
    """Điểm — đơn vị nhỏ nhất trong cấu trúc văn bản pháp luật VN."""

    label: str = Field(description="Nhãn điểm, ví dụ 'a'")
    content: str


class Clause(BaseModel):
    """Khoản — unit cơ bản nhất cho retrieval (ADR-02)."""

    number: int
    content: str
    points: list[Point] = Field(default_factory=list)


class Article(BaseModel):
    """Điều."""

    number: int
    title: str | None = None
    content_raw: str
    chapter: str | None = Field(default=None, description="Số chương La Mã, vd 'II'")
    chapter_title: str | None = None
    clauses: list[Clause] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    """Metadata gốc của văn bản (id, số hiệu, ngày tháng)."""

    id: str = Field(description="Canonical graph ID theo ontology, vd 'ldn_2020'")
    title: str
    number: str = Field(description="Số hiệu văn bản, vd '59/2020/QH14'")
    doc_type: str = Field(description="Document type: Law|Decree|Circular|Resolution|Decision")
    normative: bool = Field(default=True, description="True for normative legal documents in the selected corpus")
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
