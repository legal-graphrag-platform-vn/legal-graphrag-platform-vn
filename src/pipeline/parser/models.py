"""Pydantic models cho output của Hierarchy Parser.

Khớp đúng Output Format quy định trong plans/04_graph_construction_pipeline.md
và ID Convention trong plans/legal_ontology.md. Các model này được
tái dùng làm input cho LLM Extraction (extraction/llm_extractor.py) để tránh
định nghĩa schema trùng lặp ở nhiều tầng.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from src.shared.ontology.hierarchy import (
    normalize_chapter_number,
    normalize_part_number,
    normalize_section_number,
    normalize_subsection_number,
)

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
    part: str | None = Field(default=None, description="Số Phần, ví dụ 'II'")
    chapter: str | None = Field(default=None, description="Số chương La Mã, vd 'II'")
    chapter_title: str | None = None
    section: str | None = Field(
        default=None, description="Số Mục trong Chapter, vd '1'"
    )
    subsection: str | None = Field(
        default=None, description="Số Tiểu mục trong Section, vd '1'"
    )
    clauses: list[Clause] = Field(default_factory=list)
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)


class Part(BaseModel):
    """Phần — structural grouping lớn nhất trong nội dung văn bản."""

    number: LegalNumber
    title: str
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class Section(BaseModel):
    """Mục — structural grouping nằm trực tiếp dưới Chapter."""

    number: LegalNumber
    title: str
    chapter: str
    part: str | None = None
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @field_validator("title", "chapter")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class Subsection(BaseModel):
    """Tiểu mục — structural grouping nằm trực tiếp dưới Section."""

    number: LegalNumber
    title: str
    chapter: str
    section: str
    part: str | None = None
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @field_validator("title", "chapter", "section")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


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
    parts: list[Part] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)
    unparsed_sections: list[UnparsedSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def section_hierarchy_must_be_consistent(self) -> "ParsedDocument":
        part_index: dict[str, Part] = {}
        for part in self.parts:
            key = normalize_part_number(part.number)
            if key in part_index:
                raise ValueError(f"Duplicate Part number: {part.number}")
            part_index[key] = part

        section_index: dict[tuple[str | None, str, str], Section] = {}
        for section in self.sections:
            key = _section_key(section.part, section.chapter, section.number)
            if key in section_index:
                raise ValueError(
                    f"Duplicate Section number: Chapter {section.chapter} Section {section.number}"
                )
            if (
                section.part is not None
                and normalize_part_number(section.part) not in part_index
            ):
                raise ValueError(
                    f"Section {section.number} references missing Part {section.part}"
                )
            section_index[key] = section

        subsection_index: dict[tuple[str | None, str, str, str], Subsection] = {}
        for subsection in self.subsections:
            section_key = _section_key(
                subsection.part, subsection.chapter, subsection.section
            )
            if section_key not in section_index:
                raise ValueError(
                    f"Subsection {subsection.number} references missing Section "
                    f"{subsection.section} in Chapter {subsection.chapter}"
                )
            key = (*section_key, normalize_subsection_number(subsection.number))
            if key in subsection_index:
                raise ValueError(
                    f"Duplicate Subsection number: Section {subsection.section} "
                    f"Subsection {subsection.number}"
                )
            subsection_index[key] = subsection

        referenced_parts: set[str] = set()
        referenced_sections: set[tuple[str | None, str, str]] = set()
        referenced_subsections: set[tuple[str | None, str, str, str]] = set()
        root_modes: set[str] = set()
        chapter_modes: dict[tuple[str | None, str], set[str]] = {}
        section_modes: dict[tuple[str | None, str, str], set[str]] = {}
        chapter_parts: dict[str, str | None] = {}
        for article in self.articles:
            part_key = (
                normalize_part_number(article.part)
                if article.part is not None
                else None
            )
            if part_key is not None:
                if part_key not in part_index:
                    raise ValueError(
                        f"Article {article.number} references missing Part {article.part}"
                    )
                if article.chapter is None:
                    raise ValueError(
                        f"Article {article.number} references Part {article.part} without Chapter"
                    )
                referenced_parts.add(part_key)

            if article.subsection is not None and article.section is None:
                raise ValueError(
                    f"Article {article.number} references Subsection {article.subsection} without Section"
                )
            if article.section is not None and article.chapter is None:
                raise ValueError(
                    f"Article {article.number} references Section {article.section} without Chapter"
                )

            if article.chapter is None:
                root_modes.add("Article")
                continue

            root_modes.add("Part" if article.part is not None else "Chapter")
            chapter_key = (part_key, normalize_chapter_number(article.chapter))
            normalized_chapter = normalize_chapter_number(article.chapter)
            previous_part = chapter_parts.setdefault(normalized_chapter, part_key)
            if previous_part != part_key:
                raise ValueError(
                    f"Chapter {article.chapter} is assigned to multiple Part parents"
                )

            if article.section is None:
                chapter_modes.setdefault(chapter_key, set()).add("Article")
                continue

            chapter_modes.setdefault(chapter_key, set()).add("Section")
            key = _section_key(article.part, article.chapter, article.section)
            if key not in section_index:
                raise ValueError(
                    f"Article {article.number} references missing Section "
                    f"{article.section} in Chapter {article.chapter}"
                )
            referenced_sections.add(key)

            if article.subsection is None:
                section_modes.setdefault(key, set()).add("Article")
                continue

            section_modes.setdefault(key, set()).add("Subsection")
            subsection_key = (*key, normalize_subsection_number(article.subsection))
            if subsection_key not in subsection_index:
                raise ValueError(
                    f"Article {article.number} references missing Subsection "
                    f"{article.subsection} in Section {article.section}"
                )
            referenced_subsections.add(subsection_key)

        if len(root_modes) > 1:
            raise ValueError(
                "Document mixes Part, Chapter, or direct Article child modes"
            )
        for (_, chapter), modes in chapter_modes.items():
            if len(modes) > 1:
                raise ValueError(
                    f"Chapter {chapter} mixes Section and direct Article child modes"
                )
        for (_, chapter, section), modes in section_modes.items():
            if len(modes) > 1:
                raise ValueError(
                    f"Section {section} in Chapter {chapter} mixes Subsection and direct Article child modes"
                )

        orphan_parts = sorted(set(part_index) - referenced_parts)
        if orphan_parts:
            raise ValueError(f"Part {orphan_parts[0]} does not contain any Article")

        orphan_sections = sorted(set(section_index) - referenced_sections)
        if orphan_sections:
            _, chapter, section = orphan_sections[0]
            raise ValueError(
                f"Section {section} in Chapter {chapter} does not contain any Article"
            )
        orphan_subsections = sorted(set(subsection_index) - referenced_subsections)
        if orphan_subsections:
            _, chapter, section, subsection = orphan_subsections[0]
            raise ValueError(
                f"Subsection {subsection} in Section {section} Chapter {chapter} "
                "does not contain any Article"
            )
        return self


def _section_key(
    part: str | None, chapter: str, section: str
) -> tuple[str | None, str, str]:
    return (
        part.strip().lower() if part is not None else None,
        normalize_chapter_number(chapter),
        normalize_section_number(section),
    )
