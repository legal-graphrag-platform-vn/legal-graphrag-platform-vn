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
    legal_number_sort_key,
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
        seen: dict[str, Point] = {}
        deduped: list[Point] = []
        for point in self.points:
            label = point.label.strip().lower()
            if label in seen:
                existing = seen[label]
                existing.content = f"{existing.content} {point.content}".strip()
                existing.source_end_char = max(
                    existing.source_end_char, point.source_end_char
                )
            else:
                seen[label] = point
                deduped.append(point)
        self.points = deduped
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
    """Mục — structural grouping nằm dưới Chapter hoặc trực thuộc Part/Document."""

    number: LegalNumber
    title: str
    chapter: str | None = None
    part: str | None = None
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class Subsection(BaseModel):
    """Tiểu mục — structural grouping nằm trực tiếp dưới Section."""

    number: LegalNumber
    title: str
    section: str
    chapter: str | None = None
    part: str | None = None
    source_start_char: int = Field(default=0, ge=0)
    source_end_char: int = Field(default=0, ge=0)

    @field_validator("title", "section")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class Appendix(BaseModel):
    """Phụ lục — citable structural owner scoped under one Document."""

    scope: str = Field(pattern=r"^[a-z0-9_]+$")
    number: LegalNumber | None = None
    heading: str
    title: str | None = None
    appendix_kind: Literal["LEGAL_CONTENT", "FORM", "LIST", "TABLE", "UNCLASSIFIED"] = (
        "UNCLASSIFIED"
    )
    content_raw: str
    parts: list[Part] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("heading", "content_raw")
    @classmethod
    def required_source_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class AttachedInstrument(BaseModel):
    """Văn bản pháp lý được ban hành kèm theo một Document chủ."""

    scope: str = Field(pattern=r"^[a-z0-9_]+$")
    heading: str
    adoption_text: str
    title: str | None = None
    instrument_kind: Literal["REGULATION", "CHARTER", "STANDARD"]
    content_raw: str
    parts: list[Part] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)
    appendices: list[Appendix] = Field(default_factory=list)
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("heading", "adoption_text", "content_raw")
    @classmethod
    def required_source_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class UnparsedSection(BaseModel):
    """Losslessly preserved source section outside the active graph ontology."""

    section_type: Literal["TABLE_OF_CONTENTS", "UNPARSED_BODY"]
    heading: str | None = None
    content_raw: str
    source_document_id: str
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ParseWarning(BaseModel):
    """A recoverable parser condition recorded beside the hierarchy artifact."""

    code: str
    message: str
    source_line: int | None = Field(default=None, ge=1)
    source_start_char: int | None = Field(default=None, ge=0)
    source_end_char: int | None = Field(default=None, ge=0)


class ParseDiagnostics(BaseModel):
    """Auditable result of one permissive parse attempt."""

    parser_name: Literal["hierarchy_parser"] = "hierarchy_parser"
    parser_version: Literal["2.1"] = "2.1"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["PARSED", "PARSED_WITH_WARNINGS", "SOURCE_PRESERVED"]
    article_count: int = Field(ge=0)
    unparsed_section_count: int = Field(ge=0)
    warnings: list[ParseWarning] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    """Metadata gốc của văn bản (id, số hiệu, ngày tháng)."""

    id: str = Field(description="Canonical graph ID theo ontology, vd 'ldn_2020'")
    title: str
    number: str = Field(description="Số hiệu văn bản, vd '59/2020/QH14'")
    doc_type: str = Field(
        description="Document type: Law|Decree|Circular|Resolution|Decision"
    )
    normative: bool | None = None
    issued_by: str | None = None
    issued_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    issuer_name: str | None = None
    legal_status: str = Field(default="ACTIVE")
    source_url: str | None = None
    sector: str | None = None
    field: str | None = None
    signer_title: str | None = None
    signer_name: str | None = None


class ParsedDocument(BaseModel):
    """Output đầy đủ của Hierarchy Parser — input cho Step 2 LLM Extraction."""

    document: DocumentInfo
    articles: list[Article] = Field(default_factory=list)
    parts: list[Part] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)
    appendices: list[Appendix] = Field(default_factory=list)
    attached_instruments: list[AttachedInstrument] = Field(default_factory=list)
    unparsed_sections: list[UnparsedSection] = Field(default_factory=list)
    parser_metadata: ParseDiagnostics | None = None

    @model_validator(mode="after")
    def section_hierarchy_must_be_consistent(self) -> "ParsedDocument":
        appendix_scopes: set[str] = set()
        for appendix in self.appendices:
            original_scope = appendix.scope
            count = 1
            while appendix.scope in appendix_scopes:
                appendix.scope = f"{original_scope}_{count}"
                count += 1
            appendix_scopes.add(appendix.scope)

        instrument_scopes: set[str] = set()
        for instrument in self.attached_instruments:
            original_scope = instrument.scope
            count = 1
            while instrument.scope in instrument_scopes:
                instrument.scope = f"{original_scope}_{count}"
                count += 1
            instrument_scopes.add(instrument.scope)

        article_numbers: set[tuple[str | None, str]] = set()
        for article in self.articles:
            key = (
                normalize_part_number(article.part) if article.part else None,
                article.number,
            )
            if key in article_numbers:
                raise ValueError(f"Duplicate Article number: {article.number}")
            article_numbers.add(key)

        part_index: dict[str, Part] = {}
        for part in self.parts:
            key = normalize_part_number(part.number)
            if key in part_index:
                raise ValueError(f"Duplicate Part number: {part.number}")
            part_index[key] = part

        section_index: dict[tuple[str | None, str | None, str], Section] = {}
        for section in self.sections:
            key = _section_key(section.part, section.chapter, section.number)
            if key in section_index:
                count = sum(
                    1
                    for (p, c, s) in section_index
                    if p == key[0] and c == key[1] and s.startswith(section.number)
                )
                key = (key[0], key[1], f"{section.number}_{count + 1}")
            if (
                section.part is not None
                and normalize_part_number(section.part) not in part_index
            ):
                raise ValueError(
                    f"Section {section.number} references missing Part {section.part}"
                )
            section_index[key] = section

        subsection_index: dict[tuple[str | None, str | None, str, str], Subsection] = {}
        for subsection in self.subsections:
            section_key = _section_key(
                subsection.part, subsection.chapter, subsection.section
            )
            if section_key not in section_index:
                chapter_label = (
                    f" in Chapter {subsection.chapter}" if subsection.chapter else ""
                )
                raise ValueError(
                    f"Subsection {subsection.number} references missing Section "
                    f"{subsection.section}{chapter_label}"
                )
            key = (*section_key, normalize_subsection_number(subsection.number))
            if key in subsection_index:
                raise ValueError(
                    f"Duplicate Subsection number: Section {subsection.section} "
                    f"Subsection {subsection.number}"
                )
            subsection_index[key] = subsection

        referenced_parts: set[str] = set()
        referenced_sections: set[tuple[str | None, str | None, str]] = set()
        referenced_subsections: set[tuple[str | None, str | None, str, str]] = set()
        root_modes: set[str] = set()
        chapter_modes: dict[tuple[str | None, str], set[str]] = {}
        chapter_direct_articles: dict[tuple[str | None, str], list[str]] = {}
        chapter_section_articles: dict[tuple[str | None, str], list[str]] = {}
        section_modes: dict[tuple[str | None, str | None, str], set[str]] = {}
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
                referenced_parts.add(part_key)

            if article.subsection is not None and article.section is None:
                raise ValueError(
                    f"Article {article.number} references Subsection {article.subsection} without Section"
                )

            if article.chapter is None:
                if article.section is not None:
                    key = _section_key(article.part, None, article.section)
                    if key not in section_index:
                        # Try matching with suffixed key
                        matching = [
                            k
                            for k in section_index
                            if k[0] == key[0]
                            and k[1] is None
                            and k[2].startswith(article.section)
                        ]
                        if not matching:
                            raise ValueError(
                                f"Article {article.number} references missing Section {article.section}"
                            )
                        key = matching[0]
                    referenced_sections.add(key)
                root_modes.add(
                    "Part"
                    if article.part is not None
                    else ("Section" if article.section is not None else "Article")
                )
                continue

            root_modes.add("Part" if article.part is not None else "Chapter")
            chapter_key = (part_key, normalize_chapter_number(article.chapter))

            if article.section is None:
                chapter_modes.setdefault(chapter_key, set()).add("Article")
                chapter_direct_articles.setdefault(chapter_key, []).append(
                    article.number
                )
                continue

            chapter_modes.setdefault(chapter_key, set()).add("Section")
            chapter_section_articles.setdefault(chapter_key, []).append(article.number)
            key = _section_key(article.part, article.chapter, article.section)
            if key not in section_index:
                matching = [
                    k
                    for k in section_index
                    if k[0] == key[0]
                    and k[1] == key[1]
                    and k[2].startswith(article.section)
                ]
                if not matching:
                    raise ValueError(
                        f"Article {article.number} references missing Section "
                        f"{article.section} in Chapter {article.chapter}"
                    )
                key = matching[0]
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
        for section_key, modes in section_modes.items():
            if "SUBSECTION" in modes and "ARTICLE" in modes:
                # Allowed: Some documents have Sections that contain direct Articles and also Subsections.
                pass

        orphan_sections = set(section_index) - referenced_sections
        if orphan_sections:
            self.sections = [
                s
                for s in self.sections
                if _section_key(s.part, s.chapter, s.number) in referenced_sections
            ]
        orphan_subsections = set(subsection_index) - referenced_subsections
        if orphan_subsections:
            self.subsections = [
                sub
                for sub in self.subsections
                if (
                    *_section_key(sub.part, sub.chapter, sub.section),
                    normalize_subsection_number(sub.number),
                )
                in referenced_subsections
            ]
        return self


def _section_key(
    part: str | None, chapter: str | None, section: str
) -> tuple[str | None, str | None, str]:
    return (
        part.strip().lower() if part is not None else None,
        normalize_chapter_number(chapter) if chapter is not None else None,
        normalize_section_number(section),
    )


def _validate_chapter_preamble_order(
    *,
    chapter: str,
    direct_article_numbers: list[str],
    section_article_numbers: list[str],
) -> None:
    latest_direct = max(direct_article_numbers, key=legal_number_sort_key)
    first_section = min(section_article_numbers, key=legal_number_sort_key)
    if legal_number_sort_key(latest_direct) >= legal_number_sort_key(first_section):
        raise ValueError(
            f"Chapter {chapter} direct Article {latest_direct} must precede "
            f"first Section Article {first_section}"
        )
