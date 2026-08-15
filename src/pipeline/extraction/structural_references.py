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
from src.shared.ontology.hierarchy import (
    normalize_part_number,
    normalize_subsection_number,
)


RESOLVER_NAME = "vn-structural-reference-resolver"
RESOLVER_VERSION = "5.0.0"
LINKER_NAME = "corpus-structural-registry"
LINKER_VERSION = "3.0.0"

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
    source_start_char: int | None = Field(default=None, ge=0)
    source_end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> "SourceContext":
        if (self.source_start_char is None) != (self.source_end_char is None):
            raise ValueError("Source context coordinates must be present as a pair")
        return self


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
    registry_evidences: tuple["RegistryResolutionEvidence", ...] = ()
    projection_evidence: "ProjectionEvidence | None" = None

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

    def all_registry_evidences(self) -> tuple["RegistryResolutionEvidence", ...]:
        """Return the v2 evidence collection with v1 checkpoint compatibility."""

        if self.registry_evidences:
            return self.registry_evidences
        return (self.registry_evidence,) if self.registry_evidence is not None else ()


class StructuralTargetCandidate(BaseModel):
    target_type: Literal[
        "Document",
        "Appendix",
        "Part",
        "Chapter",
        "Section",
        "Subsection",
        "Article",
        "Clause",
        "Point",
    ]
    document_number: str | None = None
    appendix_scope: str | None = None
    appendix_number: str | None = None
    part_number: str | None = None
    chapter_number: str | None = None
    section_number: str | None = None
    subsection_number: str | None = None
    article_number: str | None = None
    clause_number: str | None = None
    point_label: str | None = None

    @model_validator(mode="after")
    def validate_required_parents(self) -> "StructuralTargetCandidate":
        if self.target_type == "Document":
            children = (
                self.appendix_scope,
                self.appendix_number,
                self.part_number,
                self.chapter_number,
                self.section_number,
                self.subsection_number,
                self.article_number,
                self.clause_number,
                self.point_label,
            )
            if any(value is not None for value in children):
                raise ValueError("Document target cannot carry structural child fields")
        elif self.target_type == "Appendix" and self.appendix_scope is None:
            raise ValueError("Appendix target requires appendix_scope")
        elif self.target_type == "Part" and self.part_number is None:
            raise ValueError("Part target requires part_number")
        elif self.target_type == "Chapter" and self.chapter_number is None:
            raise ValueError("Chapter target requires chapter_number")
        elif self.target_type == "Section" and (
            self.chapter_number is None or self.section_number is None
        ):
            raise ValueError(
                "Section target requires chapter_number and section_number"
            )
        elif self.target_type == "Subsection" and (
            self.chapter_number is None
            or self.section_number is None
            or self.subsection_number is None
        ):
            raise ValueError(
                "Subsection target requires chapter, section, and subsection"
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


class ProjectionEvidence(BaseModel):
    """Host-coordinate proof for a relation whose legal source is projected."""

    host_document_id: str
    host_source_unit_id: str
    host_source_type: str
    host_source_ancestor_ids: tuple[str, ...]
    host_source_char_start: int = Field(ge=0)
    host_source_char_end: int = Field(ge=0)
    projection_basis_candidate_id: str


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
_PART_NUMBER = r"(?:thứ\s+[a-zà-ỹ]+|[IVXLCDM]+|\d+[a-z]?)"
_APPENDIX_NUMBER = r"(?:[IVXLCDM]+|\d+[A-Z]*)(?:[./-][A-Z0-9]+)*"
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
_EXTERNAL_SUBSECTION = re.compile(
    rf"(?i)\btiểu\s+mục\s+(?P<subsection>\d+[a-z]?)\s+(?:của\s+)?"
    rf"mục\s+(?P<section>\d+[a-z]?)\s+(?:của\s+)?"
    rf"chương\s+(?P<chapter>[IVXLCDM]+)\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
    r"(?:số\s+)?(?P<document>\d+/\d{4}/[A-ZĐ0-9-]+)\b"
)
_EXTERNAL_PART = re.compile(
    rf"(?i)\bphần\s+(?P<part>{_PART_NUMBER})\s+(?:của\s+)?{_DOCUMENT_KIND}\s+"
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
_EXTERNAL_APPENDIX = re.compile(
    rf"(?i)\bphụ\s+lục(?:\s+số)?\s+(?P<appendix>{_APPENDIX_NUMBER})"
    rf"\s+(?:ban\s+hành\s+kèm\s+theo|kèm\s+theo|của)\s+{_DOCUMENT_KIND}\s+"
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
_LOCAL_SUBSECTION = re.compile(
    r"(?i)\btiểu\s+mục\s+(?P<subsection>\d+[a-z]?)\s+(?:của\s+)?"
    r"mục\s+(?P<section>\d+[a-z]?)\s+(?:của\s+)?"
    r"chương\s+(?P<chapter>[IVXLCDM]+)\b"
)
_CURRENT_PART = re.compile(r"(?i)\bphần\s+này\b")
_CURRENT_APPENDIX = re.compile(r"(?i)\bphụ\s+lục\s+này\b")
_EXPLICIT_LOCAL_APPENDIX = re.compile(
    rf"(?i)\bphụ\s+lục(?:\s+số)?\s+(?P<appendix>{_APPENDIX_NUMBER})"
    r"(?:\s+(?:ban\s+hành\s+)?kèm\s+theo\s+(?:văn\s+bản|luật|"
    r"nghị\s+định|thông\s+tư|quyết\s+định)\s+này)?\b"
)
_EXPLICIT_LOCAL_PART = re.compile(
    rf"(?i)\bphần\s+(?P<part>{_PART_NUMBER})\b"
    r"(?:\s+của\s+(?:luật|văn\s+bản)\s+này\b)?"
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
    r"(?i)\b(?:các\s+)?khoản\s+"
    r"(?P<clauses>\d+[a-z]?(?:\s*,\s*(?:khoản\s+)?\d+[a-z]?)*"
    r"(?:\s+và\s+(?:khoản\s+)?\d+[a-z]?)?)"
    r"\s+điều\s+(?P<article>\d+[a-z]?)\b"
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
        excluded_source_spans: tuple[tuple[int, int], ...] = (),
    ) -> None:
        self.registry = registry
        self.source_text = canonicalize_source_text(source_text)
        self.corpus_registry = corpus_registry
        self.registry_receipt = registry_receipt
        self.excluded_source_spans = tuple(
            sorted(_validate_source_spans(excluded_source_spans, len(self.source_text)))
        )
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
            (_EXTERNAL_SUBSECTION, self._resolve_external_match),
            (_EXTERNAL_SECTION, self._resolve_external_match),
            (_EXTERNAL_CHAPTER, self._resolve_external_match),
            (_EXTERNAL_PART, self._resolve_external_match),
            (_EXTERNAL_ARTICLE, self._resolve_external_match),
            (_EXTERNAL_APPENDIX, self._resolve_external_match),
            (_EXTERNAL_DOCUMENT, self._resolve_external_match),
            (_LOCAL_SUBSECTION, self._resolve_local_subsection),
            (_LOCAL_SECTION, self._resolve_local_section),
            (_CURRENT_APPENDIX, self._resolve_current_appendix),
            (_EXPLICIT_LOCAL_APPENDIX, self._resolve_explicit_local_appendix),
            (_CURRENT_PART, self._resolve_current_part),
            (_EXPLICIT_LOCAL_PART, self._resolve_explicit_local_part),
            (_CURRENT_CHAPTER, self._resolve_current_chapter),
            (_EXPLICIT_LOCAL_CHAPTER, self._resolve_explicit_local_chapter),
            (_POINTS_CURRENT_CLAUSE, self._resolve_points_current_clause),
            (_EXPLICIT_POINT, self._resolve_explicit_point),
            (_EXPLICIT_CLAUSE, self._resolve_explicit_clauses),
            (_CLAUSE_CURRENT_ARTICLE, self._resolve_clause_current_article),
            (_CURRENT_CLAUSE, self._resolve_current_clause),
            (_CURRENT_ARTICLE, self._resolve_current_article),
            (_EXPLICIT_ARTICLE, self._resolve_explicit_article),
        )
        for pattern, handler in patterns:
            for match in pattern.finditer(text):
                local_span = match.span()
                source_span = (
                    segment.start + local_span[0],
                    segment.start + local_span[1],
                )
                if any(
                    _overlaps(source_span, excluded)
                    for excluded in self.excluded_source_spans
                ):
                    continue
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
                    _EXTERNAL_SUBSECTION,
                    _EXTERNAL_SECTION,
                    _EXTERNAL_CHAPTER,
                    _EXTERNAL_PART,
                    _EXTERNAL_ARTICLE,
                    _EXTERNAL_APPENDIX,
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

    def _resolve_current_appendix(
        self, mention: ReferenceMention, _: re.Match[str]
    ) -> ResolvedReference:
        article_key = self.registry.article_key_for_id(
            mention.source_context.article_id
        )
        scope = _appendix_scope_from_article_key(article_key or "")
        target = self.registry.appendices.get(scope or "")
        return _resolved_or_missing(mention, target, "current_appendix_context_missing")

    def _resolve_explicit_local_appendix(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        candidate = _target_candidate(match)
        target = self.registry.appendices.get(candidate.appendix_scope or "")
        return _resolved_or_missing(
            mention,
            target,
            "explicit_appendix_target_missing",
            candidate=candidate,
        )

    def _resolve_local_subsection(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        candidate = _target_candidate(match)
        target = self.registry.subsections.get(
            (
                match.group("chapter").strip().upper(),
                match.group("section").strip().lower(),
                normalize_subsection_number(match.group("subsection")),
            )
        )
        return _resolved_or_missing(
            mention,
            target,
            "explicit_subsection_target_missing",
            candidate=candidate,
        )

    def _resolve_current_part(
        self, mention: ReferenceMention, _: re.Match[str]
    ) -> ResolvedReference:
        target = self.registry.part_for_article_id(mention.source_context.article_id)
        return _resolved_or_missing(mention, target, "current_part_context_missing")

    def _resolve_explicit_local_part(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        candidate = _target_candidate(match)
        target = self.registry.parts.get(normalize_part_number(match.group("part")))
        return _resolved_or_missing(
            mention,
            target,
            "explicit_part_target_missing",
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
                appendix_scope=candidate.appendix_scope,
                part_number=candidate.part_number,
                chapter_number=candidate.chapter_number,
                section_number=candidate.section_number,
                subsection_number=candidate.subsection_number,
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
        article_key = self._reference_article_key(
            mention, match.group("article").lower()
        )
        target = self.registry.points.get(
            (
                article_key or "",
                match.group("clause").lower(),
                match.group("label").lower(),
            )
        )
        return _resolved_or_missing(mention, target, "explicit_point_target_missing")

    def _resolve_explicit_clauses(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        article_key = self._reference_article_key(
            mention, match.group("article").lower()
        )
        targets = tuple(
            self.registry.clauses.get((article_key or "", clause_number)) or ""
            for clause_number in _clause_numbers(match)
        )
        if not targets or any(not target for target in targets):
            return _unresolved(mention, "explicit_clause_target_missing")
        return _resolved_or_self(mention, targets)

    def _resolve_clause_current_article(
        self, mention: ReferenceMention, match: re.Match[str]
    ) -> ResolvedReference:
        article_key = self.registry.article_key_for_id(
            mention.source_context.article_id
        )
        target = self.registry.clauses.get(
            (article_key or "", match.group("clause").lower())
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
        article_key = self._reference_article_key(
            mention, match.group("article").lower()
        )
        target = self.registry.articles.get(article_key or "")
        return _resolved_or_missing(mention, target, "explicit_article_target_missing")

    def _reference_article_key(
        self, mention: ReferenceMention, article_number: str
    ) -> str | None:
        candidates = self.registry.article_ids_for_number(article_number)
        if len(candidates) == 1:
            return self.registry.article_key_for_id(candidates[0])
        current_part = self.registry.part_for_article_id(
            mention.source_context.article_id
        )
        same_part = tuple(
            article_id
            for article_id in candidates
            if self.registry.part_for_article_id(article_id) == current_part
        )
        if current_part is not None and len(same_part) == 1:
            return self.registry.article_key_for_id(same_part[0])
        return None

    def _article_segments(self, article: Article) -> list[_UnitSegment]:
        article_id = self.registry.article_id_for_model(article)
        if article_id is None:
            raise ValueError(f"Article is not registered: {article.number}")
        article_key = self.registry.article_key_for_id(article_id)
        if article_key is None:
            raise ValueError(f"Article key is not registered: {article_id}")
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
            clause_id = self.registry.clauses[(article_key, clause.number)]
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
                    (article_key, clause.number, point.label.strip().lower())
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


def _validate_source_spans(
    spans: tuple[tuple[int, int], ...], source_length: int
) -> tuple[tuple[int, int], ...]:
    validated: list[tuple[int, int]] = []
    for start, end in spans:
        if start < 0 or end <= start or end > source_length:
            raise ValueError(f"Invalid excluded source span: ({start}, {end})")
        validated.append((start, end))
    return tuple(validated)


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
    appendix = groups.get("appendix")
    part = groups.get("part")
    chapter = groups.get("chapter")
    section = groups.get("section")
    subsection = groups.get("subsection")
    article = groups.get("article")
    clause = groups.get("clause")
    point = groups.get("label")
    if appendix:
        target_type = "Appendix"
    elif point:
        target_type = "Point"
    elif clause:
        target_type = "Clause"
    elif article:
        target_type = "Article"
    elif subsection:
        target_type = "Subsection"
    elif section:
        target_type = "Section"
    elif chapter:
        target_type = "Chapter"
    elif part:
        target_type = "Part"
    else:
        target_type = "Document"
    return StructuralTargetCandidate(
        target_type=target_type,
        document_number=document.upper() if document else None,
        appendix_scope=_normalize_appendix_scope(appendix) if appendix else None,
        appendix_number=appendix.upper() if appendix else None,
        part_number=normalize_part_number(part) if part else None,
        chapter_number=chapter.upper() if chapter else None,
        section_number=section.lower() if section else None,
        subsection_number=(
            normalize_subsection_number(subsection) if subsection else None
        ),
        article_number=article.lower() if article else None,
        clause_number=clause.lower() if clause else None,
        point_label=point.lower() if point else None,
    )


def _normalize_appendix_scope(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def _appendix_scope_from_article_key(article_key: str) -> str | None:
    if not article_key.startswith("app") or ":" not in article_key:
        return None
    return article_key[3:].split(":", 1)[0]


def _clause_numbers(match: re.Match[str]) -> tuple[str, ...]:
    groups = match.groupdict()
    if groups.get("clauses"):
        return tuple(
            number.lower()
            for number in re.findall(r"(?i)\b(\d+[a-z]?)\b", groups["clauses"])
        )
    clause = groups.get("clause")
    return (clause.lower(),) if clause else ()


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
