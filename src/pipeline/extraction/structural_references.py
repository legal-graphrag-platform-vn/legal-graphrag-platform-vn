"""Deterministic resolution of relative legal references."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from src.pipeline.extraction.structural_context import (
    DocumentRegistry,
    StructuralRegistry,
    normalize_point_label,
)
from src.pipeline.parser.hierarchy_parser import canonicalize_source_text
from src.pipeline.parser.models import Article, Clause, Point


RESOLVER_NAME = "vn-structural-reference-resolver"
RESOLVER_VERSION = "2.0.0"
LINKER_NAME = "curated-document-registry"
LINKER_VERSION = "1.0.0"

ReferenceKind = Literal["STRUCTURAL", "EXPLICIT", "SEMANTIC"]
ResolutionStatus = Literal["RESOLVED", "AMBIGUOUS", "UNRESOLVED", "SELF_REFERENCE"]
ResolutionMethod = Literal["RULE", "ENTITY_LINKING", "LLM_CANDIDATE_VALIDATED"]


class SourceContext(BaseModel):
    document_id: str
    article_id: str
    clause_id: str | None = None
    point_id: str | None = None
    source_unit_id: str
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)


class ReferenceMention(BaseModel):
    source_context: SourceContext
    raw_text: str
    reference_kind: ReferenceKind
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(ge=0)
    reference_bundle_id: str


class ResolvedReference(BaseModel):
    mention: ReferenceMention
    target_unit_ids: tuple[str, ...] = ()
    status: ResolutionStatus
    resolution_method: ResolutionMethod
    reason_code: str


@dataclass(frozen=True, slots=True)
class _UnitSegment:
    context: SourceContext
    start: int
    end: int


_POINTS_CURRENT_CLAUSE = re.compile(
    r"(?i)\b(?:các\s+)?điểm\s+"
    r"(?P<labels>[a-zđ](?:\s*,\s*[a-zđ])*(?:\s+và\s+(?:điểm\s+)?[a-zđ])?)"
    r"\s+khoản\s+này\b"
)
_EXPLICIT_POINT = re.compile(
    r"(?i)\bđiểm\s+(?P<label>[a-zđ])\s+khoản\s+(?P<clause>\d+[a-z]?)"
    r"\s+điều\s+(?P<article>\d+[a-z]?)\b"
)
_EXPLICIT_CLAUSE = re.compile(
    r"(?i)\bkhoản\s+(?P<clause>\d+[a-z]?)\s+điều\s+(?P<article>\d+[a-z]?)\b"
)
_CLAUSE_CURRENT_ARTICLE = re.compile(
    r"(?i)\bkhoản\s+(?P<clause>\d+[a-z]?)\s+điều\s+này\b"
)
_CURRENT_CLAUSE = re.compile(r"(?i)\bkhoản\s+này\b")
_EXPLICIT_ARTICLE = re.compile(r"(?i)\bđiều\s+(?P<article>\d+[a-z]?)\b")
_CURRENT_ARTICLE = re.compile(r"(?i)\bđiều\s+này\b")


class StructuralReferenceResolver:
    def __init__(
        self,
        registry: StructuralRegistry,
        source_text: str,
        document_registry: DocumentRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.source_text = canonicalize_source_text(source_text)
        self.document_registry = document_registry or DocumentRegistry({})

    def resolve_article(self, article: Article) -> list[ResolvedReference]:
        references: list[ResolvedReference] = []
        for segment in self._article_segments(article):
            references.extend(self._resolve_segment(segment))
        return references

    def _resolve_segment(self, segment: _UnitSegment) -> list[ResolvedReference]:
        text = self.source_text[segment.start : segment.end]
        occupied: list[tuple[int, int]] = []
        resolved: list[ResolvedReference] = []
        patterns = (
            (_POINTS_CURRENT_CLAUSE, self._resolve_points_current_clause),
            (_EXPLICIT_POINT, self._resolve_explicit_point),
            (_EXPLICIT_CLAUSE, self._resolve_explicit_clause),
            (_CLAUSE_CURRENT_ARTICLE, self._resolve_clause_current_article),
            (_CURRENT_CLAUSE, self._resolve_current_clause),
            (_CURRENT_ARTICLE, self._resolve_current_article),
            (_EXPLICIT_ARTICLE, self._resolve_explicit_article),
        )
        for pattern, handler in patterns:
            for match in pattern.finditer(text):
                local_span = match.span()
                if (
                    pattern is _EXPLICIT_ARTICLE
                    and segment.start + match.start()
                    == segment.context.source_start_char
                ):
                    # The Article heading declares the current unit; it is not a citation.
                    continue
                if any(_overlaps(local_span, prior) for prior in occupied):
                    continue
                occupied.append(local_span)
                external_number = (
                    _external_document_number(_citation_segment(text, match.start()))
                    if pattern in {_EXPLICIT_POINT, _EXPLICIT_CLAUSE, _EXPLICIT_ARTICLE}
                    else None
                )
                mention = self._mention(
                    segment,
                    match,
                    reference_kind="EXPLICIT" if external_number else "STRUCTURAL",
                )
                if external_number:
                    resolved.append(
                        self._resolve_external(mention, match, external_number)
                    )
                    continue
                resolved.append(handler(mention, match))
        return sorted(resolved, key=lambda item: item.mention.source_char_start)

    def _mention(
        self,
        segment: _UnitSegment,
        match: re.Match[str],
        *,
        reference_kind: ReferenceKind,
    ) -> ReferenceMention:
        start = segment.start + match.start()
        end = segment.start + match.end()
        raw_text = self.source_text[start:end]
        bundle_id = reference_bundle_id(
            segment.context.source_unit_id, start, end, raw_text
        )
        return ReferenceMention(
            source_context=segment.context,
            raw_text=raw_text,
            reference_kind=reference_kind,
            source_char_start=start,
            source_char_end=end,
            reference_bundle_id=bundle_id,
        )

    def _resolve_external(
        self,
        mention: ReferenceMention,
        match: re.Match[str],
        document_number: str,
    ) -> ResolvedReference:
        identity = self.document_registry.resolve(document_number, document_number)
        if identity is None:
            return ResolvedReference(
                mention=mention,
                status="AMBIGUOUS",
                resolution_method="ENTITY_LINKING",
                reason_code="missing_external_document_registry",
            )
        graph_id, _ = identity
        article_number = match.groupdict().get("article")
        clause_number = match.groupdict().get("clause")
        point_label = match.groupdict().get("label")
        target = f"{graph_id}_art{article_number.lower()}"
        if clause_number:
            target += f"_cl{clause_number.lower()}"
        if point_label:
            target += f"_p{normalize_point_label(point_label)}"
        return ResolvedReference(
            mention=mention,
            target_unit_ids=(target,),
            status="RESOLVED",
            resolution_method="ENTITY_LINKING",
            reason_code="curated_external_document_resolution",
        )

    def _resolve_points_current_clause(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        context = mention.source_context
        if not context.clause_id:
            return _unresolved(mention, "current_clause_context_missing")
        labels = tuple(re.findall(r"(?i)\b([a-zđ])\b", match.group("labels")))
        targets = tuple(
            self.registry.point_by_parent_id(
                context.clause_id, normalize_point_label(label)
            )
            or ""
            for label in labels
        )
        if not targets or any(not target for target in targets):
            return _unresolved(mention, "relative_point_target_missing")
        return _resolved_or_self(mention, targets)

    def _resolve_explicit_point(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        target = self.registry.points.get(
            (
                match.group("article").lower(),
                match.group("clause").lower(),
                match.group("label").lower(),
            )
        )
        return _resolved_or_missing(mention, target, "explicit_point_target_missing")

    def _resolve_explicit_clause(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        target = self.registry.clauses.get(
            (match.group("article").lower(), match.group("clause").lower())
        )
        return _resolved_or_missing(mention, target, "explicit_clause_target_missing")

    def _resolve_clause_current_article(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        article_number = self.registry.article_number_for_id(
            mention.source_context.article_id
        )
        target = self.registry.clauses.get(
            (article_number or "", match.group("clause").lower())
        )
        return _resolved_or_missing(
            mention, target, "current_article_clause_target_missing"
        )

    def _resolve_current_clause(
        self, mention: ReferenceMention, _: re.Match[str]
    ) -> ResolvedReference:
        return _resolved_or_missing(
            mention, mention.source_context.clause_id, "current_clause_context_missing"
        )

    def _resolve_current_article(
        self, mention: ReferenceMention, _: re.Match[str]
    ) -> ResolvedReference:
        return _resolved_or_missing(
            mention,
            mention.source_context.article_id,
            "current_article_context_missing",
        )

    def _resolve_explicit_article(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        target = self.registry.articles.get(match.group("article").lower())
        return _resolved_or_missing(mention, target, "explicit_article_target_missing")

    def _article_segments(self, article: Article) -> list[_UnitSegment]:
        article_id = self.registry.articles[article.number]
        segments: list[_UnitSegment] = []
        clause_intervals = [
            (clause.source_start_char, clause.source_end_char)
            for clause in article.clauses
        ]
        for start, end in _subtract_intervals(
            article.source_start_char, article.source_end_char, clause_intervals
        ):
            segments.append(
                _UnitSegment(
                    context=SourceContext(
                        document_id=self.registry.graph_id,
                        article_id=article_id,
                        source_unit_id=article_id,
                        source_start_char=article.source_start_char,
                        source_end_char=article.source_end_char,
                    ),
                    start=start,
                    end=end,
                )
            )
        for clause in article.clauses:
            clause_id = self.registry.clauses[(article.number, clause.number)]
            point_intervals = [
                (point.source_start_char, point.source_end_char)
                for point in clause.points
            ]
            for start, end in _subtract_intervals(
                clause.source_start_char, clause.source_end_char, point_intervals
            ):
                segments.append(
                    _UnitSegment(
                        context=_context(
                            self.registry.graph_id, article_id, clause_id, None, clause
                        ),
                        start=start,
                        end=end,
                    )
                )
            for point in clause.points:
                point_id = self.registry.points[
                    (article.number, clause.number, point.label.strip().lower())
                ]
                segments.append(
                    _UnitSegment(
                        context=_context(
                            self.registry.graph_id,
                            article_id,
                            clause_id,
                            point_id,
                            point,
                        ),
                        start=point.source_start_char,
                        end=point.source_end_char,
                    )
                )
        return [segment for segment in segments if segment.end > segment.start]


def reference_bundle_id(
    source_unit_id: str, start: int, end: int, citation_text: str
) -> str:
    normalized = re.sub(
        r"\s+", " ", unicodedata.normalize("NFC", citation_text).strip()
    )
    source = f"{source_unit_id}|{start}|{end}|{normalized}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _context(
    document_id: str,
    article_id: str,
    clause_id: str,
    point_id: str | None,
    unit: Clause | Point,
) -> SourceContext:
    return SourceContext(
        document_id=document_id,
        article_id=article_id,
        clause_id=clause_id,
        point_id=point_id,
        source_unit_id=point_id or clause_id,
        source_start_char=unit.source_start_char,
        source_end_char=unit.source_end_char,
    )


def _resolved_or_missing(
    mention: ReferenceMention, target: str | None, missing_reason: str
) -> ResolvedReference:
    if not target:
        return _unresolved(mention, missing_reason)
    return _resolved_or_self(mention, (target,))


def _resolved_or_self(
    mention: ReferenceMention, targets: tuple[str, ...]
) -> ResolvedReference:
    if len(targets) == 1 and targets[0] == mention.source_context.source_unit_id:
        return ResolvedReference(
            mention=mention,
            target_unit_ids=targets,
            status="SELF_REFERENCE",
            resolution_method="RULE",
            reason_code="self_reference_no_edge",
        )
    return ResolvedReference(
        mention=mention,
        target_unit_ids=targets,
        status="RESOLVED",
        resolution_method="RULE",
        reason_code="deterministic_structural_resolution",
    )


def _unresolved(mention: ReferenceMention, reason: str) -> ResolvedReference:
    return ResolvedReference(
        mention=mention,
        status="UNRESOLVED",
        resolution_method="RULE",
        reason_code=reason,
    )


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _subtract_intervals(
    start: int, end: int, excluded: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    cursor = start
    segments: list[tuple[int, int]] = []
    for excluded_start, excluded_end in sorted(excluded):
        if excluded_end <= cursor or excluded_start >= end:
            continue
        if excluded_start > cursor:
            segments.append((cursor, min(excluded_start, end)))
        cursor = max(cursor, excluded_end)
    if cursor < end:
        segments.append((cursor, end))
    return segments


def _citation_segment(text: str, match_start: int) -> str:
    end = text.find(";", match_start)
    return text[match_start:] if end == -1 else text[match_start:end]


def _external_document_number(text: str) -> str | None:
    match = re.search(r"(?i)\b(?:số\s+)?(\d+/\d{4}/[A-ZĐ0-9-]+)\b", text)
    return match.group(1).upper() if match else None
