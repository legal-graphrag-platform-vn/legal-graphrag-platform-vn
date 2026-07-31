"""Deterministic resolution of relative legal references."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.pipeline.extraction.corpus_structural_registry import (
    CorpusStructuralRegistry,
    RegistryBuildReceipt,
    RegistryDocument,
    RegistryUnit,
)
from src.pipeline.extraction.structural_context import (
    StructuralRegistry,
    normalize_point_label,
)
from src.pipeline.parser.hierarchy_parser import canonicalize_source_text
from src.pipeline.parser.models import Article, Clause, Point


RESOLVER_NAME = "vn-structural-reference-resolver"
RESOLVER_VERSION = "4.0.0"
LINKER_NAME = "corpus-structural-registry"
LINKER_VERSION = "1.0.0"

ReferenceKind = Literal["STRUCTURAL", "EXPLICIT", "SEMANTIC"]
ResolutionStatus = Literal["RESOLVED", "AMBIGUOUS", "UNRESOLVED"]
ReferenceScope = Literal["LOCAL", "EXTERNAL", "UNKNOWN"]
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
    target_candidate: "StructuralTargetCandidate | None" = None
    status: ResolutionStatus
    reference_scope: ReferenceScope
    is_self_reference: bool = False
    resolution_method: ResolutionMethod
    reason_code: str
    registry_evidence: "RegistryResolutionEvidence | None" = None

    @model_validator(mode="after")
    def validate_self_reference_contract(self) -> "ResolvedReference":
        expected = (
            self.status == "RESOLVED"
            and self.reference_scope == "LOCAL"
            and len(self.target_unit_ids) == 1
            and self.target_unit_ids[0] == self.mention.source_context.source_unit_id
        )
        if self.is_self_reference != expected:
            raise ValueError(
                "is_self_reference must be derived from resolved endpoint identity"
            )
        return self


class StructuralTargetCandidate(BaseModel):
    target_type: Literal["Document", "Chapter", "Section", "Article", "Clause", "Point"]
    document_number: str | None = None
    chapter_number: str | None = None
    section_number: str | None = None
    article_number: str | None = None
    clause_number: str | None = None
    point_label: str | None = None

    @model_validator(mode="after")
    def validate_required_parents(self) -> "StructuralTargetCandidate":
        if self.target_type == "Document":
            children = (
                self.chapter_number,
                self.section_number,
                self.article_number,
                self.clause_number,
                self.point_label,
            )
            if any(value is not None for value in children):
                raise ValueError("Document target cannot carry structural child fields")
        elif self.target_type == "Chapter" and self.chapter_number is None:
            raise ValueError("Chapter target requires chapter_number")
        elif self.target_type == "Section" and (
            self.chapter_number is None or self.section_number is None
        ):
            raise ValueError(
                "Section target requires chapter_number and section_number"
            )
        elif self.target_type == "Article" and self.article_number is None:
            raise ValueError("Article target requires article_number")
        elif self.target_type == "Clause" and (
            self.article_number is None or self.clause_number is None
        ):
            raise ValueError("Clause target requires article_number and clause_number")
        elif self.target_type == "Point" and (
            self.article_number is None
            or self.clause_number is None
            or self.point_label is None
        ):
            raise ValueError("Point target requires article, clause, and point")
        return self


class RegistryResolutionEvidence(BaseModel):
    build_id: str
    snapshot_hash: str
    provenance_hash: str
    source_id: str
    source_type: str
    source_document_id: str
    source_ancestor_ids: tuple[str, ...]
    target_id: str
    target_type: str
    target_document_id: str
    target_ancestor_ids: tuple[str, ...]


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
_DOCUMENT_KIND = (
    r"(?:Luật|Nghị\s+định|Thông\s+tư|Quyết\s+định|Nghị\s+quyết|Pháp\s+lệnh|Hiến\s+pháp)"
)
_EXTERNAL_POINT = re.compile(
    rf"(?i)\bđiểm\s+(?P<label>[a-zđ])\s+khoản\s+(?P<clause>\d+[a-z]?)"
    rf"\s+điều\s+(?P<article>\d+[a-z]?)\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
    r"(?:số\s+)?(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_CLAUSE = re.compile(
    rf"(?i)\bkhoản\s+(?P<clause>\d+[a-z]?)\s+điều\s+(?P<article>\d+[a-z]?)"
    rf"\s+(?:của\s+)?{_DOCUMENT_KIND}\s+(?:số\s+)?"
    r"(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_SECTION = re.compile(
    rf"(?i)\bmục\s+(?P<section>\d+[a-z]?)\s+(?:của\s+)?"
    rf"chương\s+(?P<chapter>[IVXLCDM]+)\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
    r"(?:số\s+)?(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_CHAPTER = re.compile(
    rf"(?i)\bchương\s+(?P<chapter>[IVXLCDM]+)\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
    r"(?:số\s+)?(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_ARTICLE = re.compile(
    rf"(?i)\bđiều\s+(?P<article>\d+[a-z]?)\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
    r"(?:số\s+)?(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_DOCUMENT = re.compile(
    rf"(?i)\b{_DOCUMENT_KIND}\s+(?:số\s+)?"
    r"(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_LOCAL_SECTION = re.compile(
    r"(?i)\bmục\s+(?P<section>\d+[a-z]?)\s+(?:của\s+)?"
    r"chương\s+(?P<chapter>[IVXLCDM]+)\b"
)
_CURRENT_CHAPTER = re.compile(r"(?i)\bchương\s+này\b")
_EXPLICIT_LOCAL_CHAPTER = re.compile(
    r"(?i)\bchương\s+(?P<chapter>[IVXLCDM]+)\b"
    r"(?:\s+của\s+(?:luật|văn\s+bản)\s+này\b)?"
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
        corpus_registry: CorpusStructuralRegistry | None = None,
        registry_receipt: RegistryBuildReceipt | None = None,
    ) -> None:
        self.registry = registry
        self.source_text = canonicalize_source_text(source_text)
        self.corpus_registry = corpus_registry
        self.registry_receipt = registry_receipt
        if (corpus_registry is None) != (registry_receipt is None):
            raise ValueError(
                "corpus_registry and registry_receipt must be provided together"
            )
        if (
            corpus_registry is not None
            and registry_receipt is not None
            and corpus_registry.snapshot_hash != registry_receipt.snapshot_hash
        ):
            raise ValueError("Registry receipt does not match loaded content snapshot")

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
            (_EXTERNAL_POINT, self._resolve_external_match),
            (_EXTERNAL_CLAUSE, self._resolve_external_match),
            (_EXTERNAL_SECTION, self._resolve_external_match),
            (_EXTERNAL_CHAPTER, self._resolve_external_match),
            (_EXTERNAL_ARTICLE, self._resolve_external_match),
            (_EXTERNAL_DOCUMENT, self._resolve_external_match),
            (_LOCAL_SECTION, self._resolve_local_section),
            (_CURRENT_CHAPTER, self._resolve_current_chapter),
            (_EXPLICIT_LOCAL_CHAPTER, self._resolve_explicit_local_chapter),
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
                is_external = pattern in {
                    _EXTERNAL_POINT,
                    _EXTERNAL_CLAUSE,
                    _EXTERNAL_SECTION,
                    _EXTERNAL_CHAPTER,
                    _EXTERNAL_ARTICLE,
                    _EXTERNAL_DOCUMENT,
                }
                mention = self._mention(
                    segment,
                    match,
                    reference_kind=("EXPLICIT" if is_external else "STRUCTURAL"),
                )
                resolved.append(handler(mention, match))
        return sorted(resolved, key=lambda item: item.mention.source_char_start)

    def _resolve_external_match(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        return self._resolve_external(mention, _target_candidate(match))

    def _resolve_local_section(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        candidate = _target_candidate(match)
        target = self.registry.sections.get(
            (
                match.group("chapter").strip().upper(),
                match.group("section").strip().lower(),
            )
        )
        return _resolved_or_missing(
            mention,
            target,
            "explicit_section_target_missing",
            candidate=candidate,
        )

    def _resolve_current_chapter(
        self, mention: ReferenceMention, _: re.Match[str]
    ) -> ResolvedReference:
        target = self.registry.chapter_for_article_id(mention.source_context.article_id)
        return _resolved_or_missing(
            mention,
            target,
            "current_chapter_context_missing",
        )

    def _resolve_explicit_local_chapter(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        candidate = _target_candidate(match)
        target = self.registry.chapters.get(match.group("chapter").strip().upper())
        return _resolved_or_missing(
            mention,
            target,
            "explicit_chapter_target_missing",
            candidate=candidate,
        )

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
        self, mention: ReferenceMention, candidate: StructuralTargetCandidate
    ) -> ResolvedReference:
        if self.corpus_registry is None or self.registry_receipt is None:
            return _external_unresolved(
                mention,
                candidate,
                "target_document_not_in_snapshot",
            )
        source_candidates = self.corpus_registry.endpoint_candidates(
            mention.source_context.source_unit_id
        )
        if len(source_candidates) == 0:
            return _external_unresolved(
                mention, candidate, "source_endpoint_not_in_snapshot"
            )
        if len(source_candidates) > 1:
            return _external_ambiguous(mention, candidate, "source_endpoint_ambiguous")
        source = source_candidates[0]
        if not isinstance(source, RegistryUnit):
            return _external_unresolved(
                mention, candidate, "source_endpoint_type_invalid"
            )
        if source.document_id != mention.source_context.document_id:
            return _external_unresolved(
                mention, candidate, "source_document_ownership_ambiguous"
            )

        document_candidates = self.corpus_registry.document_candidates(
            candidate.document_number or ""
        )
        if len(document_candidates) == 0:
            return _external_unresolved(
                mention, candidate, "target_document_not_in_snapshot"
            )
        if len(document_candidates) > 1:
            return _external_ambiguous(
                mention, candidate, "target_document_identity_ambiguous"
            )
        target_document = document_candidates[0]
        scope: ReferenceScope = (
            "LOCAL" if target_document.document_id == source.document_id else "EXTERNAL"
        )
        if candidate.target_type == "Document":
            target_candidates: tuple[RegistryDocument | RegistryUnit, ...] = (
                target_document,
            )
        else:
            target_candidates = self.corpus_registry.unit_candidates(
                document_id=target_document.document_id,
                unit_type=candidate.target_type,
                chapter_number=candidate.chapter_number,
                section_number=candidate.section_number,
                article_number=candidate.article_number,
                clause_number=candidate.clause_number,
                point_label=candidate.point_label,
            )
        if len(target_candidates) == 0:
            return _external_unresolved(
                mention,
                candidate,
                "target_structural_unit_not_found",
                scope=scope,
            )
        if len(target_candidates) > 1:
            return _external_ambiguous(
                mention,
                candidate,
                "target_structural_unit_ambiguous",
                scope=scope,
            )
        target = target_candidates[0]
        target_id = (
            target.document_id
            if isinstance(target, RegistryDocument)
            else target.unit_id
        )
        target_type = (
            "Document" if isinstance(target, RegistryDocument) else target.unit_type
        )
        target_ancestors = (
            () if isinstance(target, RegistryDocument) else target.ancestor_ids
        )
        is_self = scope == "LOCAL" and target_id == source.unit_id
        return ResolvedReference(
            mention=mention,
            target_unit_ids=(target_id,),
            target_candidate=candidate,
            status="RESOLVED",
            reference_scope=scope,
            is_self_reference=is_self,
            resolution_method="ENTITY_LINKING",
            reason_code=(
                "same_document_reference_not_external"
                if scope == "LOCAL"
                else "registry_external_structural_resolution"
            ),
            registry_evidence=RegistryResolutionEvidence(
                build_id=self.registry_receipt.build_id,
                snapshot_hash=self.registry_receipt.snapshot_hash,
                provenance_hash=self.registry_receipt.provenance_hash,
                source_id=source.unit_id,
                source_type=source.unit_type,
                source_document_id=source.document_id,
                source_ancestor_ids=source.ancestor_ids,
                target_id=target_id,
                target_type=target_type,
                target_document_id=target_document.document_id,
                target_ancestor_ids=target_ancestors,
            ),
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
    mention: ReferenceMention,
    target: str | None,
    missing_reason: str,
    *,
    candidate: StructuralTargetCandidate | None = None,
) -> ResolvedReference:
    if not target:
        return _unresolved(mention, missing_reason, candidate=candidate)
    return _resolved_or_self(mention, (target,), candidate=candidate)


def _resolved_or_self(
    mention: ReferenceMention,
    targets: tuple[str, ...],
    *,
    candidate: StructuralTargetCandidate | None = None,
) -> ResolvedReference:
    if len(targets) == 1 and targets[0] == mention.source_context.source_unit_id:
        return ResolvedReference(
            mention=mention,
            target_unit_ids=targets,
            target_candidate=candidate,
            status="RESOLVED",
            reference_scope="LOCAL",
            is_self_reference=True,
            resolution_method="RULE",
            reason_code="self_reference_no_edge",
        )
    return ResolvedReference(
        mention=mention,
        target_unit_ids=targets,
        target_candidate=candidate,
        status="RESOLVED",
        reference_scope="LOCAL",
        is_self_reference=False,
        resolution_method="RULE",
        reason_code="deterministic_structural_resolution",
    )


def _unresolved(
    mention: ReferenceMention,
    reason: str,
    *,
    candidate: StructuralTargetCandidate | None = None,
) -> ResolvedReference:
    return ResolvedReference(
        mention=mention,
        target_candidate=candidate,
        status="UNRESOLVED",
        reference_scope="LOCAL",
        is_self_reference=False,
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


def _target_candidate(match: re.Match[str]) -> StructuralTargetCandidate:
    groups = match.groupdict()
    document = groups.get("document")
    chapter = groups.get("chapter")
    section = groups.get("section")
    article = groups.get("article")
    clause = groups.get("clause")
    point = groups.get("label")
    if point:
        target_type = "Point"
    elif clause:
        target_type = "Clause"
    elif article:
        target_type = "Article"
    elif section:
        target_type = "Section"
    elif chapter:
        target_type = "Chapter"
    else:
        target_type = "Document"
    return StructuralTargetCandidate(
        target_type=target_type,
        document_number=document.upper() if document else None,
        chapter_number=chapter.upper() if chapter else None,
        section_number=section.lower() if section else None,
        article_number=article.lower() if article else None,
        clause_number=clause.lower() if clause else None,
        point_label=point.lower() if point else None,
    )


def _external_unresolved(
    mention: ReferenceMention,
    candidate: StructuralTargetCandidate,
    reason: str,
    *,
    scope: ReferenceScope = "EXTERNAL",
) -> ResolvedReference:
    return ResolvedReference(
        mention=mention,
        target_candidate=candidate,
        status="UNRESOLVED",
        reference_scope=scope,
        is_self_reference=False,
        resolution_method="ENTITY_LINKING",
        reason_code=reason,
    )


def _external_ambiguous(
    mention: ReferenceMention,
    candidate: StructuralTargetCandidate,
    reason: str,
    *,
    scope: ReferenceScope = "EXTERNAL",
) -> ResolvedReference:
    return ResolvedReference(
        mention=mention,
        target_candidate=candidate,
        status="AMBIGUOUS",
        reference_scope=scope,
        is_self_reference=False,
        resolution_method="ENTITY_LINKING",
        reason_code=reason,
    )
