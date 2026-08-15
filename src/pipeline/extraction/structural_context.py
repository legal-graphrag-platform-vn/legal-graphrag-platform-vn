"""Canonical structural context and endpoint resolution for extraction."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.pipeline.parser.models import Article, ParsedDocument
from src.shared.ontology.hierarchy import (
    chapter_id,
    normalize_section_number,
    normalize_part_number,
    normalize_subsection_number,
    part_id,
    section_id,
    subsection_id,
)


PROMPT_VERSION = "structural-reference-v5"
ENDPOINT_CONTRACT_VERSION = "canonical-endpoints-v5"


@dataclass(frozen=True, slots=True)
class ArticleExtractionContext:
    raw_doc_code: str
    graph_id: str
    article_number: str
    article_id: str
    clause_ids: dict[str, str]
    point_ids: dict[tuple[str, str], str]

    def to_prompt_json(self) -> str:
        payload = asdict(self)
        payload["point_ids"] = [
            {"clause_number": clause, "label": label, "id": node_id}
            for (clause, label), node_id in self.point_ids.items()
        ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class EndpointResolution:
    raw_id: str
    canonical_id: str | None
    canonical_type: str | None
    status: Literal["resolved", "review", "rejected"]
    method: str
    reason: str | None = None


class StructuralRegistry:
    def __init__(self, parsed: ParsedDocument, raw_doc_code: str) -> None:
        self.graph_id = parsed.document.id
        self.raw_doc_code = raw_doc_code
        self.types: dict[str, str] = {self.graph_id: "Document"}
        self.appendices: dict[str, str] = {}
        self.attached_instruments: dict[str, str] = {}
        self.parts: dict[str, str] = {}
        self.chapters: dict[str, str] = {}
        self.sections: dict[tuple[str | None, str], str] = {}
        self.subsections: dict[tuple[str | None, str, str], str] = {}
        self.articles: dict[str, str] = {}
        self.clauses: dict[tuple[str, str], str] = {}
        self.points: dict[tuple[str, str, str], str] = {}
        self.article_parts: dict[str, str] = {}
        self.article_appendices: dict[str, str] = {}
        self.article_attached_instruments: dict[str, str] = {}
        self.article_chapters: dict[str, str] = {}
        self.article_sections: dict[str, str] = {}
        self.article_subsections: dict[str, str] = {}
        self._article_keys_by_id: dict[str, str] = {}
        self._article_numbers_by_id: dict[str, str] = {}
        self._article_node_ids_by_span: dict[tuple[int, int, str, str | None], str] = {}
        self._appendix_parts: dict[tuple[str, str], str] = {}
        self._appendix_chapters: dict[tuple[str, str], str] = {}
        self._appendix_sections: dict[tuple[str, str | None, str], str] = {}
        self._appendix_subsections: dict[tuple[str, str | None, str, str], str] = {}

        for part in parsed.parts:
            part_number = normalize_part_number(part.number)
            if part_number in self.parts:
                count = sum(1 for p in self.parts if p.startswith(part_number))
                part_number = f"{part_number}_{count + 1}"
            part_node_id = part_id(self.graph_id, part_number)
            self.parts[part_number] = part_node_id
            self.types[part_node_id] = "Part"

        for section in parsed.sections:
            chapter_number = (
                _normalize_chapter_key(section.chapter) if section.chapter else None
            )
            section_number = section.number.strip().lower()
            if chapter_number:
                self._register_chapter(chapter_number)
            key = (chapter_number, section_number)
            if key in self.sections:
                count = sum(
                    1
                    for (c, s) in self.sections
                    if c == key[0] and s.startswith(key[1])
                )
                key = (key[0], f"{key[1]}_{count + 1}")
            section_node_id = (
                section_id(self.graph_id, chapter_number, key[1])
                if chapter_number
                else f"{self.graph_id}_sec{key[1]}"
            )
            self.sections[key] = section_node_id
            self.types[section_node_id] = "Section"

        for subsection in parsed.subsections:
            chapter_number = (
                _normalize_chapter_key(subsection.chapter)
                if subsection.chapter
                else None
            )
            section_number = subsection.section.strip().lower()
            subsection_number = normalize_subsection_number(subsection.number)
            key = (chapter_number, section_number, subsection_number)
            if key in self.subsections:
                count = sum(
                    1
                    for (c, s, sub) in self.subsections
                    if c == key[0] and s == key[1] and sub.startswith(key[2])
                )
                key = (key[0], key[1], f"{key[2]}_{count + 1}")
            subsection_node_id = subsection_id(
                self.graph_id,
                chapter_number,
                section_number,
                key[2],
            )
            self.subsections[key] = subsection_node_id
            if (chapter_number, section_number) not in self.sections:
                matching = [
                    k
                    for k in self.sections
                    if k[0] == chapter_number and k[1].startswith(section_number)
                ]
                if not matching:
                    chapter_label = (
                        f" in Chapter {subsection.chapter}"
                        if subsection.chapter
                        else ""
                    )
                    raise ValueError(
                        f"Subsection {subsection.number} references missing Section "
                        f"{subsection.section}{chapter_label}"
                    )

        article_number_counts = {
            number: sum(1 for item in parsed.articles if item.number == number)
            for number in {item.number for item in parsed.articles}
        }
        for article in parsed.articles:
            if article_number_counts[article.number] > 1:
                if not article.part:
                    raise ValueError(
                        f"Article {article.number} repeats without distinct Part ownership"
                    )
                part_num = normalize_part_number(article.part)
                article_id = f"{self.graph_id}_p{part_num}_art{article.number}"
                article_key = f"p{part_num}_{article.number}"
            else:
                article_id = f"{self.graph_id}_art{article.number}"
                article_key = article.number

            if article_key in self.articles:
                count = sum(1 for k in self.articles if k.startswith(article_key))
                article_key = f"{article_key}_{count + 1}"
                article_id = f"{article_id}_{count + 1}"

            self.articles[article_key] = article_id
            self.types[article_id] = "Article"
            self._article_keys_by_id[article_id] = article_key
            self._article_numbers_by_id[article_id] = article.number
            self._article_node_ids_by_span[
                (
                    article.source_start_char,
                    article.source_end_char,
                    article.number,
                    article.part,
                )
            ] = article_id
            if article.part:
                part_number = normalize_part_number(article.part)
                part_node_id = self.parts.get(part_number)
                if part_node_id is not None:
                    self.article_parts[article_id] = part_node_id
            if article.chapter:
                chapter_number = _normalize_chapter_key(article.chapter)
                self.article_chapters[article_id] = self._register_chapter(
                    chapter_number
                )
                if article.section:
                    section_key = (
                        chapter_number,
                        article.section.strip().lower(),
                    )
                    section_node_id = self.sections.get(section_key)
                    if section_node_id is not None:
                        self.article_sections[article_id] = section_node_id
                        if article.subsection:
                            subsection_key = (
                                chapter_number,
                                article.section.strip().lower(),
                                normalize_subsection_number(article.subsection),
                            )
                            subsection_node_id = self.subsections.get(subsection_key)
                            if subsection_node_id is not None:
                                self.article_subsections[article_id] = (
                                    subsection_node_id
                                )
            elif article.section:
                section_key = (None, article.section.strip().lower())
                section_node_id = self.sections.get(section_key)
                if section_node_id is not None:
                    self.article_sections[article_id] = section_node_id
                    if article.subsection:
                        subsection_key = (
                            None,
                            article.section.strip().lower(),
                            normalize_subsection_number(article.subsection),
                        )
                        subsection_node_id = self.subsections.get(subsection_key)
                        if subsection_node_id is not None:
                            self.article_subsections[article_id] = subsection_node_id

            for clause in article.clauses:
                key = (article_key, clause.number)
                if key in self.clauses:
                    count = sum(
                        1
                        for (a, c) in self.clauses
                        if a == article_key and c.startswith(clause.number)
                    )
                    clause_key = f"{clause.number}_{count + 1}"
                    key = (article_key, clause_key)
                    clause_id = f"{article_id}_cl{clause_key}"
                else:
                    clause_id = f"{article_id}_cl{clause.number}"

                self.clauses[key] = clause_id
                self.types[clause_id] = "Clause"
                for point in clause.points:
                    point_label = point.label.strip().lower()
                    point_key = (
                        article_key,
                        clause.number,
                        point_label,
                    )
                    point_id = f"{clause_id}_p{normalize_point_label(point.label)}"
                    self.points[point_key] = point_id
                    self.types[point_id] = "Point"

        for appendix in parsed.appendices:
            appendix_id = f"{self.graph_id}_app{appendix.scope}"
            self.appendices[appendix.scope] = appendix_id
            self.types[appendix_id] = "Appendix"
            for part in appendix.parts:
                part_number = normalize_part_number(part.number)
                part_node_id = part_id(appendix_id, part.number)
                self._appendix_parts[(appendix.scope, part_number)] = part_node_id
                self.types[part_node_id] = "Part"
            for section in appendix.sections:
                chapter_number = (
                    _normalize_chapter_key(section.chapter) if section.chapter else None
                )
                if chapter_number:
                    chapter_node_id = chapter_id(appendix_id, section.chapter)
                    self._appendix_chapters[(appendix.scope, chapter_number)] = (
                        chapter_node_id
                    )
                    self.types[chapter_node_id] = "Chapter"
                section_number = normalize_section_number(section.number)
                section_node_id = (
                    section_id(appendix_id, section.chapter, section.number)
                    if section.chapter
                    else f"{appendix_id}_sec{section_number}"
                )
                self._appendix_sections[
                    (appendix.scope, chapter_number, section_number)
                ] = section_node_id
                self.types[section_node_id] = "Section"
            for subsection in appendix.subsections:
                chapter_number = (
                    _normalize_chapter_key(subsection.chapter)
                    if subsection.chapter
                    else None
                )
                section_number = normalize_section_number(subsection.section)
                subsection_number = normalize_subsection_number(subsection.number)
                section_node_id = self._appendix_sections.get(
                    (appendix.scope, chapter_number, section_number)
                )
                if section_node_id is None:
                    raise ValueError(
                        f"Appendix {appendix.scope} Subsection {subsection.number} "
                        f"references missing Section {subsection.section}"
                    )
                subsection_node_id = (
                    subsection_id(
                        appendix_id,
                        subsection.chapter,
                        subsection.section,
                        subsection.number,
                    )
                    if subsection.chapter
                    else f"{section_node_id}_subsec{subsection_number}"
                )
                self._appendix_subsections[
                    (
                        appendix.scope,
                        chapter_number,
                        section_number,
                        subsection_number,
                    )
                ] = subsection_node_id
                self.types[subsection_node_id] = "Subsection"
            for article in appendix.articles:
                article_key = f"app{appendix.scope}:{article.number}"
                article_id = f"{appendix_id}_art{article.number}"
                if article_key in self.articles or article_id in self.types:
                    raise ValueError(
                        f"Duplicate Appendix Article identity: {article_id}"
                    )
                self.articles[article_key] = article_id
                self.types[article_id] = "Article"
                self._article_keys_by_id[article_id] = article_key
                self._article_numbers_by_id[article_id] = article.number
                self.article_appendices[article_id] = appendix_id
                self._article_node_ids_by_span[
                    (
                        article.source_start_char,
                        article.source_end_char,
                        article.number,
                        article.part,
                    )
                ] = article_id
                if article.part:
                    part_node_id = self._appendix_parts.get(
                        (appendix.scope, normalize_part_number(article.part))
                    )
                    if part_node_id is not None:
                        self.article_parts[article_id] = part_node_id
                chapter_number = (
                    _normalize_chapter_key(article.chapter) if article.chapter else None
                )
                if chapter_number:
                    chapter_node_id = self._appendix_chapters.get(
                        (appendix.scope, chapter_number)
                    )
                    if chapter_node_id is None:
                        chapter_node_id = chapter_id(appendix_id, article.chapter)
                        self._appendix_chapters[(appendix.scope, chapter_number)] = (
                            chapter_node_id
                        )
                        self.types[chapter_node_id] = "Chapter"
                    self.article_chapters[article_id] = chapter_node_id
                if article.section:
                    section_number = normalize_section_number(article.section)
                    section_node_id = self._appendix_sections.get(
                        (appendix.scope, chapter_number, section_number)
                    )
                    if section_node_id is not None:
                        self.article_sections[article_id] = section_node_id
                        if article.subsection:
                            subsection_node_id = self._appendix_subsections.get(
                                (
                                    appendix.scope,
                                    chapter_number,
                                    section_number,
                                    normalize_subsection_number(article.subsection),
                                )
                            )
                            if subsection_node_id is not None:
                                self.article_subsections[article_id] = (
                                    subsection_node_id
                                )
                for clause in article.clauses:
                    clause_key = (article_key, clause.number)
                    clause_id = f"{article_id}_cl{clause.number}"
                    if clause_key in self.clauses or clause_id in self.types:
                        raise ValueError(
                            f"Duplicate Appendix Clause identity: {clause_id}"
                        )
                    self.clauses[clause_key] = clause_id
                    self.types[clause_id] = "Clause"
                    for point in clause.points:
                        point_label = point.label.strip().lower()
                        point_key = (article_key, clause.number, point_label)
                        point_id = f"{clause_id}_p{normalize_point_label(point.label)}"
                        if point_key in self.points or point_id in self.types:
                            raise ValueError(
                                f"Duplicate Appendix Point identity: {point_id}"
                            )
                        self.points[point_key] = point_id
                        self.types[point_id] = "Point"

        for instrument in parsed.attached_instruments:
            instrument_id = f"{self.graph_id}_inst{instrument.scope}"
            self.attached_instruments[instrument.scope] = instrument_id
            self.types[instrument_id] = "AttachedInstrument"
            instrument_scope = f"inst{instrument.scope}"
            self._register_scoped_hierarchy(
                owner_id=instrument_id,
                scope_key=instrument_scope,
                parts=instrument.parts,
                sections=instrument.sections,
                subsections=instrument.subsections,
                articles=instrument.articles,
                article_owner_map=self.article_attached_instruments,
            )
            for appendix in instrument.appendices:
                appendix_id = f"{instrument_id}_app{appendix.scope}"
                nested_scope = f"{instrument_scope}_app{appendix.scope}"
                self.appendices[nested_scope] = appendix_id
                self.types[appendix_id] = "Appendix"
                self._register_scoped_hierarchy(
                    owner_id=appendix_id,
                    scope_key=nested_scope,
                    parts=appendix.parts,
                    sections=appendix.sections,
                    subsections=appendix.subsections,
                    articles=appendix.articles,
                    article_owner_map=self.article_appendices,
                )

    def _register_scoped_hierarchy(
        self,
        *,
        owner_id: str,
        scope_key: str,
        parts: list,
        sections: list,
        subsections: list,
        articles: list[Article],
        article_owner_map: dict[str, str],
    ) -> None:
        scoped_parts: dict[str, str] = {}
        scoped_chapters: dict[str, str] = {}
        scoped_sections: dict[tuple[str | None, str], str] = {}
        scoped_subsections: dict[tuple[str | None, str, str], str] = {}

        for part in parts:
            number = normalize_part_number(part.number)
            node_id = part_id(owner_id, part.number)
            scoped_parts[number] = node_id
            self._appendix_parts[(scope_key, number)] = node_id
            self.types[node_id] = "Part"
        for section in sections:
            chapter = (
                _normalize_chapter_key(section.chapter) if section.chapter else None
            )
            if chapter:
                chapter_node_id = chapter_id(owner_id, section.chapter)
                scoped_chapters[chapter] = chapter_node_id
                self._appendix_chapters[(scope_key, chapter)] = chapter_node_id
                self.types[chapter_node_id] = "Chapter"
            number = normalize_section_number(section.number)
            node_id = (
                section_id(owner_id, section.chapter, section.number)
                if section.chapter
                else f"{owner_id}_sec{number}"
            )
            scoped_sections[(chapter, number)] = node_id
            self._appendix_sections[(scope_key, chapter, number)] = node_id
            self.types[node_id] = "Section"
        for subsection in subsections:
            chapter = (
                _normalize_chapter_key(subsection.chapter)
                if subsection.chapter
                else None
            )
            section_number = normalize_section_number(subsection.section)
            number = normalize_subsection_number(subsection.number)
            section_node_id = scoped_sections.get((chapter, section_number))
            if section_node_id is None:
                raise ValueError(
                    f"Scoped Subsection {subsection.number} references missing "
                    f"Section {subsection.section}"
                )
            node_id = (
                subsection_id(
                    owner_id,
                    subsection.chapter,
                    subsection.section,
                    subsection.number,
                )
                if subsection.chapter
                else f"{section_node_id}_subsec{number}"
            )
            scoped_subsections[(chapter, section_number, number)] = node_id
            self._appendix_subsections[(scope_key, chapter, section_number, number)] = (
                node_id
            )
            self.types[node_id] = "Subsection"

        for article in articles:
            article_key = f"{scope_key}:{article.number}"
            article_id = f"{owner_id}_art{article.number}"
            if article_key in self.articles or article_id in self.types:
                raise ValueError(f"Duplicate scoped Article identity: {article_id}")
            self.articles[article_key] = article_id
            self.types[article_id] = "Article"
            self._article_keys_by_id[article_id] = article_key
            self._article_numbers_by_id[article_id] = article.number
            article_owner_map[article_id] = owner_id
            self._article_node_ids_by_span[
                (
                    article.source_start_char,
                    article.source_end_char,
                    article.number,
                    article.part,
                )
            ] = article_id
            if article.part:
                part_node_id = scoped_parts.get(normalize_part_number(article.part))
                if part_node_id:
                    self.article_parts[article_id] = part_node_id
            chapter = (
                _normalize_chapter_key(article.chapter) if article.chapter else None
            )
            if chapter:
                chapter_node_id = scoped_chapters.get(chapter)
                if chapter_node_id is None:
                    chapter_node_id = chapter_id(owner_id, article.chapter)
                    scoped_chapters[chapter] = chapter_node_id
                    self._appendix_chapters[(scope_key, chapter)] = chapter_node_id
                    self.types[chapter_node_id] = "Chapter"
                self.article_chapters[article_id] = chapter_node_id
            if article.section:
                section_number = normalize_section_number(article.section)
                section_node_id = scoped_sections.get((chapter, section_number))
                if section_node_id:
                    self.article_sections[article_id] = section_node_id
                    if article.subsection:
                        subsection_node_id = scoped_subsections.get(
                            (
                                chapter,
                                section_number,
                                normalize_subsection_number(article.subsection),
                            )
                        )
                        if subsection_node_id:
                            self.article_subsections[article_id] = subsection_node_id
            for clause in article.clauses:
                clause_key = (article_key, clause.number)
                clause_id = f"{article_id}_cl{clause.number}"
                if clause_key in self.clauses or clause_id in self.types:
                    raise ValueError(f"Duplicate scoped Clause identity: {clause_id}")
                self.clauses[clause_key] = clause_id
                self.types[clause_id] = "Clause"
                for point in clause.points:
                    label = point.label.strip().lower()
                    point_key = (article_key, clause.number, label)
                    point_id = f"{clause_id}_p{normalize_point_label(point.label)}"
                    if point_key in self.points or point_id in self.types:
                        raise ValueError(f"Duplicate scoped Point identity: {point_id}")
                    self.points[point_key] = point_id
                    self.types[point_id] = "Point"

    def _register_chapter(self, chapter_number: str) -> str:
        existing = self.chapters.get(chapter_number)
        canonical_id = chapter_id(self.graph_id, chapter_number)
        if existing is not None and existing != canonical_id:
            raise ValueError(f"Conflicting Chapter identity: {chapter_number}")
        self.chapters[chapter_number] = canonical_id
        self.types[canonical_id] = "Chapter"
        return canonical_id

    @classmethod
    def from_parsed_document(
        cls, parsed: ParsedDocument, raw_doc_code: str
    ) -> "StructuralRegistry":
        return cls(parsed, raw_doc_code)

    def contains(self, canonical_id: str) -> bool:
        return canonical_id in self.types

    def point_by_parent_id(self, clause_id: str, normalized_label: str) -> str | None:
        for (article_number, clause_number, label), point_id in self.points.items():
            if self.clauses.get((article_number, clause_number)) == clause_id:
                if normalize_point_label(label) == normalized_label:
                    return point_id
        return None

    def article_number_for_id(self, article_id: str) -> str | None:
        return self._article_numbers_by_id.get(article_id)

    def article_key_for_id(self, article_id: str) -> str | None:
        return self._article_keys_by_id.get(article_id)

    def article_id_for_model(self, article: Article) -> str | None:
        return self._article_node_ids_by_span.get(
            (
                article.source_start_char,
                article.source_end_char,
                article.number,
                article.part,
            )
        )

    def article_ids_for_number(self, article_number: str) -> tuple[str, ...]:
        return tuple(
            article_id
            for article_id, number in self._article_numbers_by_id.items()
            if number == article_number
        )

    def chapter_for_article_id(self, article_id: str) -> str | None:
        return self.article_chapters.get(article_id)

    def part_for_article_id(self, article_id: str) -> str | None:
        return self.article_parts.get(article_id)

    def section_for_article_id(self, article_id: str) -> str | None:
        return self.article_sections.get(article_id)

    def subsection_for_article_id(self, article_id: str) -> str | None:
        return self.article_subsections.get(article_id)

    def context_for_article(self, article: Article) -> ArticleExtractionContext:
        article_id = self.article_id_for_model(article)
        if article_id is None:
            raise ValueError(f"Article model is not registered: {article.number}")
        article_key = self._article_keys_by_id[article_id]
        return ArticleExtractionContext(
            raw_doc_code=self.raw_doc_code,
            graph_id=self.graph_id,
            article_number=article.number,
            article_id=article_id,
            clause_ids={
                number: node_id
                for (art, number), node_id in self.clauses.items()
                if art == article_key
            },
            point_ids={
                (clause, label): node_id
                for (art, clause, label), node_id in self.points.items()
                if art == article_key
            },
        )

    def resolve(
        self,
        raw_id: str,
        *,
        current_article: str,
        entity_type: str | None = None,
        entity_label: str | None = None,
    ) -> EndpointResolution:
        raw = str(raw_id)
        current_article = str(current_article)
        current_article_id = (
            current_article
            if self.types.get(current_article) == "Article"
            else self.articles.get(current_article)
        )
        current_article_key = (
            self._article_keys_by_id.get(current_article_id or "") or current_article
        )
        if raw in self.types:
            return EndpointResolution(
                raw, raw, self.types[raw], "resolved", "canonical_exact"
            )

        label = (entity_label or "").strip()
        normalized_label = label.lower()
        if entity_type == "Document" and normalized_label in {
            "luật này",
            "văn bản này",
        }:
            return EndpointResolution(
                raw, self.graph_id, "Document", "resolved", "current_document_reference"
            )

        if entity_type == "Appendix" or normalized_label.startswith("phụ lục"):
            if "phụ lục này" in normalized_label:
                node_id = self.article_appendices.get(
                    current_article_id or current_article
                )
            else:
                designator = _appendix_designator(label)
                node_id = self.appendices.get(designator or "")
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Appendix", "resolved", "structural_label"
                )

        if entity_type == "Part" or normalized_label.startswith("phần"):
            if "phần này" in normalized_label:
                node_id = self.part_for_article_id(
                    current_article_id or current_article
                )
            else:
                part_number = _part_number(label)
                appendix_scope = _appendix_scope_from_article_key(current_article_key)
                node_id = (
                    self._appendix_parts.get((appendix_scope, part_number or ""))
                    if appendix_scope
                    else None
                ) or self.parts.get(part_number or "")
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Part", "resolved", "structural_label"
                )

        if entity_type == "Chapter" or normalized_label.startswith("chương"):
            if "chương này" in normalized_label:
                node_id = self.chapter_for_article_id(
                    current_article_id or current_article
                )
            else:
                chapter_number = _chapter_number(label)
                appendix_scope = _appendix_scope_from_article_key(current_article_key)
                node_id = (
                    self._appendix_chapters.get((appendix_scope, chapter_number or ""))
                    if appendix_scope
                    else None
                ) or self.chapters.get(chapter_number or "")
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Chapter", "resolved", "structural_label"
                )

        if entity_type == "Section" or normalized_label.startswith("mục"):
            section_number = _first_number_after("mục", label)
            chapter_number = _chapter_number(label)
            appendix_scope = _appendix_scope_from_article_key(current_article_key)
            node_id = (
                self._appendix_sections.get(
                    (
                        appendix_scope,
                        chapter_number,
                        normalize_section_number(section_number or ""),
                    )
                )
                if appendix_scope
                else None
            ) or self.sections.get((chapter_number, section_number or ""))
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Section", "resolved", "structural_label"
                )

        if entity_type == "Subsection" or normalized_label.startswith("tiểu mục"):
            subsection_number, section_number = _subsection_and_section_numbers(label)
            chapter_number = _chapter_number(label)
            appendix_scope = _appendix_scope_from_article_key(current_article_key)
            node_id = (
                self._appendix_subsections.get(
                    (
                        appendix_scope,
                        chapter_number,
                        normalize_section_number(section_number or ""),
                        subsection_number or "",
                    )
                )
                if appendix_scope
                else None
            ) or self.subsections.get(
                (chapter_number, section_number or "", subsection_number or "")
            )
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Subsection", "resolved", "structural_label"
                )

        article_number = _article_number(label)
        if entity_type == "Article" or normalized_label.startswith("điều"):
            if "điều này" in normalized_label:
                target = current_article_key
            elif article_number and ":" in current_article_key:
                appendix_prefix = current_article_key.split(":", 1)[0]
                scoped_target = f"{appendix_prefix}:{article_number}"
                target = (
                    scoped_target if scoped_target in self.articles else article_number
                )
            else:
                target = article_number
            if target in self.articles:
                node_id = self.articles[target]
                return EndpointResolution(
                    raw, node_id, "Article", "resolved", "structural_label"
                )

        if entity_type == "Clause" or normalized_label.startswith("khoản"):
            clause_number = _first_number_after("khoản", label)
            target_article = article_number or current_article_key
            if article_number and ":" in current_article_key:
                scoped = f"{current_article_key.split(':', 1)[0]}:{article_number}"
                if scoped in self.articles:
                    target_article = scoped
            node_id = self.clauses.get((target_article, clause_number or ""))
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Clause", "resolved", "structural_label"
                )

        if entity_type == "Point" or normalized_label.startswith("điểm"):
            point_label = _point_label(label)
            clause_number = _first_number_after("khoản", label)
            target_article = article_number or current_article_key
            if article_number and ":" in current_article_key:
                scoped = f"{current_article_key.split(':', 1)[0]}:{article_number}"
                if scoped in self.articles:
                    target_article = scoped
            node_id = self.points.get(
                (target_article, clause_number or "", point_label)
            )
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Point", "resolved", "structural_label"
                )

        alias = re.fullmatch(r"dieu_(\d+[a-z]?)", raw)
        if alias:
            target = alias.group(1)
            if ":" in current_article_key:
                scoped = f"{current_article_key.split(':', 1)[0]}:{target}"
                if scoped in self.articles:
                    target = scoped
            node_id = self.articles.get(target)
        else:
            node_id = None
        if node_id:
            return EndpointResolution(
                raw, node_id, "Article", "resolved", "legal_citation"
            )

        return EndpointResolution(
            raw,
            None,
            entity_type,
            "rejected",
            "unresolved",
            "unresolved_local_structural_endpoint",
        )


class DocumentRegistry:
    """Resolve only explicit curated document identities, never fuzzy legal names."""

    def __init__(self, aliases: dict[str, tuple[str, str]]) -> None:
        self.aliases = aliases
        self._document_types = {
            graph_id: doc_type for graph_id, doc_type in aliases.values()
        }

    @classmethod
    def from_manifest(cls, path: Path) -> "DocumentRegistry":
        if not path.exists():
            return cls({})
        payload = json.loads(path.read_text(encoding="utf-8"))
        aliases: dict[str, tuple[str, str]] = {}
        for document in payload.get("documents", []):
            graph_id = str(document["graph_id"])
            doc_type = str(document["doc_type"])
            for value in (
                graph_id,
                document.get("raw_doc_code"),
                document.get("number"),
            ):
                if value:
                    aliases[_normalize_reference(str(value))] = (graph_id, doc_type)
        return cls(aliases)

    def resolve(self, raw_id: str, label: str | None) -> tuple[str, str] | None:
        candidates = [_normalize_reference(raw_id), _normalize_reference(label or "")]
        for candidate in candidates:
            if candidate in self.aliases:
                return self.aliases[candidate]
            for alias, identity in self.aliases.items():
                if alias and alias in candidate:
                    return identity
        return None

    @property
    def document_ids(self) -> frozenset[str]:
        return frozenset(self._document_types)

    def document_type_for_id(self, graph_id: str) -> str | None:
        return self._document_types.get(graph_id)


def normalize_point_label(label: str) -> str:
    value = label.strip().lower()
    return "dd" if value == "đ" else value


def _article_number(label: str) -> str | None:
    match = re.search(r"(?i)điều\s+(\d+[a-z]?)", label)
    return match.group(1).lower() if match else None


def _appendix_designator(label: str) -> str | None:
    match = re.search(
        r"(?i)phụ\s+lục(?:\s+số)?\s+([A-Z0-9]+(?:[./-][A-Z0-9]+)*)",
        label,
    )
    if match is None:
        return None
    decomposed = unicodedata.normalize("NFD", match.group(1))
    ascii_value = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def _appendix_scope_from_article_key(article_key: str) -> str | None:
    if ":" not in article_key:
        return None
    prefix = article_key.split(":", 1)[0]
    return prefix[3:] if prefix.startswith("app") else prefix


def _chapter_number(label: str) -> str | None:
    match = re.search(r"(?i)chương\s+([IVXLCDM]+)", label)
    return _normalize_chapter_key(match.group(1)) if match else None


def _part_number(label: str) -> str | None:
    match = re.search(r"(?i)phần\s+(thứ\s+[a-zà-ỹ]+|[IVXLCDM]+|\d+[a-z]?)", label)
    return normalize_part_number(match.group(1)) if match else None


def _subsection_and_section_numbers(label: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(?i)tiểu\s+mục\s+(\d+[a-z]?)\s+(?:của\s+)?mục\s+(\d+[a-z]?)",
        label,
    )
    if not match:
        return None, None
    return (
        normalize_subsection_number(match.group(1)),
        match.group(2).lower(),
    )


def _normalize_chapter_key(value: str) -> str:
    return value.strip().upper()


def _first_number_after(token: str, label: str) -> str | None:
    match = re.search(rf"(?i){token}\s+(\d+[a-z]?)", label)
    return match.group(1).lower() if match else None


def _point_label(label: str) -> str:
    match = re.search(r"(?i)điểm\s+([a-zđ])", label)
    return match.group(1).lower() if match else ""


def _normalize_reference(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().replace("đ", "d"))
