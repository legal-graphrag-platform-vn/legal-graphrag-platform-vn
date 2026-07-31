"""Canonical structural context and endpoint resolution for extraction."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal
from pathlib import Path

from src.pipeline.parser.models import Article, ParsedDocument
from src.shared.ontology.hierarchy import chapter_id, section_id


PROMPT_VERSION = "structural-reference-v3"
ENDPOINT_CONTRACT_VERSION = "canonical-endpoints-v3"


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
        self.chapters: dict[str, str] = {}
        self.sections: dict[tuple[str, str], str] = {}
        self.articles: dict[str, str] = {}
        self.clauses: dict[tuple[str, str], str] = {}
        self.points: dict[tuple[str, str, str], str] = {}
        self.article_chapters: dict[str, str] = {}
        self.article_sections: dict[str, str] = {}

        for section in parsed.sections:
            chapter_number = _normalize_chapter_key(section.chapter)
            section_number = section.number.strip().lower()
            self._register_chapter(chapter_number)
            key = (chapter_number, section_number)
            if key in self.sections:
                raise ValueError(
                    f"Duplicate Section number: Chapter {section.chapter} Section {section.number}"
                )
            section_node_id = section_id(self.graph_id, chapter_number, section_number)
            self.sections[key] = section_node_id
            self.types[section_node_id] = "Section"

        for article in parsed.articles:
            article_id = f"{self.graph_id}_art{article.number}"
            if article.number in self.articles:
                raise ValueError(f"Duplicate Article number: {article.number}")
            self.articles[article.number] = article_id
            self.types[article_id] = "Article"
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
                    if section_node_id is None:
                        raise ValueError(
                            f"Article {article.number} references missing Section "
                            f"{article.section} in Chapter {article.chapter}"
                        )
                    self.article_sections[article_id] = section_node_id
            elif article.section:
                raise ValueError(
                    f"Article {article.number} references Section {article.section} without Chapter"
                )
            for clause in article.clauses:
                key = (article.number, clause.number)
                if key in self.clauses:
                    raise ValueError(
                        f"Duplicate Clause number: Article {article.number} Clause {clause.number}"
                    )
                clause_id = f"{article_id}_cl{clause.number}"
                self.clauses[key] = clause_id
                self.types[clause_id] = "Clause"
                for point in clause.points:
                    point_key = (
                        article.number,
                        clause.number,
                        point.label.strip().lower(),
                    )
                    point_id = f"{clause_id}_p{normalize_point_label(point.label)}"
                    if point_key in self.points:
                        raise ValueError(
                            f"Duplicate Point: Article {article.number} Clause {clause.number} {point.label}"
                        )
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
        return next(
            (
                number
                for number, node_id in self.articles.items()
                if node_id == article_id
            ),
            None,
        )

    def chapter_for_article_id(self, article_id: str) -> str | None:
        return self.article_chapters.get(article_id)

    def section_for_article_id(self, article_id: str) -> str | None:
        return self.article_sections.get(article_id)

    def context_for_article(self, article: Article) -> ArticleExtractionContext:
        return ArticleExtractionContext(
            raw_doc_code=self.raw_doc_code,
            graph_id=self.graph_id,
            article_number=article.number,
            article_id=self.articles[article.number],
            clause_ids={
                number: node_id
                for (art, number), node_id in self.clauses.items()
                if art == article.number
            },
            point_ids={
                (clause, label): node_id
                for (art, clause, label), node_id in self.points.items()
                if art == article.number
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

        if entity_type == "Chapter" or normalized_label.startswith("chương"):
            if "chương này" in normalized_label:
                node_id = self.chapter_for_article_id(
                    self.articles.get(current_article, current_article)
                )
            else:
                chapter_number = _chapter_number(label)
                node_id = self.chapters.get(chapter_number or "")
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Chapter", "resolved", "structural_label"
                )

        if entity_type == "Section" or normalized_label.startswith("mục"):
            section_number = _first_number_after("mục", label)
            chapter_number = _chapter_number(label)
            node_id = self.sections.get((chapter_number or "", section_number or ""))
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Section", "resolved", "structural_label"
                )

        article_number = _article_number(label)
        if entity_type == "Article" or normalized_label.startswith("điều"):
            target = (
                current_article if "điều này" in normalized_label else article_number
            )
            if target in self.articles:
                node_id = self.articles[target]
                return EndpointResolution(
                    raw, node_id, "Article", "resolved", "structural_label"
                )

        if entity_type == "Clause" or normalized_label.startswith("khoản"):
            clause_number = _first_number_after("khoản", label)
            target_article = article_number or current_article
            node_id = self.clauses.get((target_article, clause_number or ""))
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Clause", "resolved", "structural_label"
                )

        if entity_type == "Point" or normalized_label.startswith("điểm"):
            point_label = _point_label(label)
            clause_number = _first_number_after("khoản", label)
            target_article = article_number or current_article
            node_id = self.points.get(
                (target_article, clause_number or "", point_label)
            )
            if node_id:
                return EndpointResolution(
                    raw, node_id, "Point", "resolved", "structural_label"
                )

        alias = re.fullmatch(r"dieu_(\d+[a-z]?)", raw)
        if alias and alias.group(1) in self.articles:
            node_id = self.articles[alias.group(1)]
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


def normalize_point_label(label: str) -> str:
    value = label.strip().lower()
    return "dd" if value == "đ" else value


def _article_number(label: str) -> str | None:
    match = re.search(r"(?i)điều\s+(\d+[a-z]?)", label)
    return match.group(1).lower() if match else None


def _chapter_number(label: str) -> str | None:
    match = re.search(r"(?i)chương\s+([IVXLCDM]+)", label)
    return _normalize_chapter_key(match.group(1)) if match else None


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
