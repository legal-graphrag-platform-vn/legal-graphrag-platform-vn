"""Fail-closed graph candidates derived from provider reference evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict

from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.parser.models import ParsedDocument


PROVIDER_RELATION_CANDIDATE_VERSION = "provider-relation-candidate-v1"

ProviderDocumentIndex = Mapping[tuple[str, str], str]
ProviderUnitIndex = Mapping[tuple[str, str, str], tuple[str, str]]
ProviderFailureIndex = Mapping[tuple[str, str, str | None], str]


class ProviderRelationCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["provider-relation-candidate-v1"] = (
        PROVIDER_RELATION_CANDIDATE_VERSION
    )
    candidate_id: str
    provider_relation_id: str | None
    relation_candidate: Literal[
        "AMENDS", "REPEALS", "REFERS_TO", "POSITIONAL_ANCHOR", "UNKNOWN"
    ]
    source_ownership: Literal["HOST", "PROJECTED"]
    host_source_id: str | None
    canonical_source_id: str | None
    canonical_source_type: str | None
    canonical_target_ids: tuple[str, ...] = ()
    canonical_target_types: tuple[str, ...] = ()
    status: Literal["RESOLVED", "UNRESOLVED", "AMBIGUOUS", "NOT_APPLICABLE"]
    reason_code: str
    evidence: str
    reference: ProviderReferenceMentionV1

    @property
    def canonical_target_id(self) -> str | None:
        return (
            self.canonical_target_ids[0]
            if len(self.canonical_target_ids) == 1
            else None
        )


def load_provider_relation_candidates(
    path: Path,
) -> tuple[ProviderRelationCandidateV1, ...]:
    if not path.is_file():
        return ()
    candidates: list[ProviderRelationCandidateV1] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            candidate = ProviderRelationCandidateV1.model_validate_json(line)
        except Exception as exc:
            raise ValueError(
                f"Malformed provider relation candidate at {path}:{line_number}"
            ) from exc
        if candidate.candidate_id in seen_ids:
            raise ValueError(
                f"Duplicate provider relation candidate: {candidate.candidate_id}"
            )
        seen_ids.add(candidate.candidate_id)
        candidates.append(candidate)
    return tuple(candidates)


def build_provider_relation_candidates(
    parsed: ParsedDocument,
    source_text: str,
    references: tuple[ProviderReferenceMentionV1, ...],
    *,
    provider_document_index: ProviderDocumentIndex | None = None,
    provider_unit_index: ProviderUnitIndex | None = None,
    provider_failure_index: ProviderFailureIndex | None = None,
) -> tuple[ProviderRelationCandidateV1, ...]:
    document_index = provider_document_index or {}
    unit_index = provider_unit_index or {}
    failure_index = provider_failure_index or {}
    registry = StructuralRegistry.from_parsed_document(
        parsed,
        references[0].provider_source_document_id if references else parsed.document.id,
    )
    candidates: list[ProviderRelationCandidateV1] = []
    for reference in references:
        host_source_id, host_source_type = _smallest_source_unit(
            parsed, registry, reference.source_char_start, reference.source_char_end
        )
        projected = _inside_open_replacement_quote(
            source_text, reference.source_char_start
        )
        projected_source = (
            _projected_source_endpoint(reference, references, source_text, unit_index)
            if projected
            else None
        )
        relation = _classify_relation(reference, source_text)
        evidence = _source_line(source_text, reference.source_char_start)
        target_document_key = (
            reference.provider,
            reference.provider_target_document_id or "",
        )
        target_document_exists = target_document_key in document_index
        if target_document_exists and not reference.provider_target_item_ids:
            resolved_targets = (document_index[target_document_key],)
            resolved_target_types = ("Document",)
        else:
            resolved_targets = tuple(
                unit_index[
                    (
                        reference.provider,
                        reference.provider_target_document_id or "",
                        item,
                    )
                ][0]
                for item in reference.provider_target_item_ids
                if (
                    reference.provider,
                    reference.provider_target_document_id or "",
                    item,
                )
                in unit_index
            )
            resolved_target_types = tuple(
                unit_index[
                    (
                        reference.provider,
                        reference.provider_target_document_id or "",
                        item,
                    )
                ][1]
                for item in reference.provider_target_item_ids
                if (
                    reference.provider,
                    reference.provider_target_document_id or "",
                    item,
                )
                in unit_index
            )

        if relation == "POSITIONAL_ANCHOR":
            status = "NOT_APPLICABLE"
            reason = "positional_anchor_no_graph_edge"
        elif relation == "UNKNOWN":
            status = "AMBIGUOUS"
            reason = "governing_operation_ambiguous"
        elif projected and projected_source is None:
            status = "UNRESOLVED"
            reason = "projected_source_owner_not_resolved"
        elif not projected and host_source_id is None:
            status = "UNRESOLVED"
            reason = "source_structural_unit_not_found"
        elif not reference.provider_target_document_id or not target_document_exists:
            status = "UNRESOLVED"
            reason = "target_document_not_in_corpus"
        elif reference.provider_target_item_ids and len(resolved_targets) != len(
            reference.provider_target_item_ids
        ):
            status = "UNRESOLVED"
            reason = next(
                (
                    failure_index[
                        (
                            reference.provider,
                            reference.provider_target_document_id or "",
                            item,
                        )
                    ]
                    for item in reference.provider_target_item_ids
                    if (
                        reference.provider,
                        reference.provider_target_document_id or "",
                        item,
                    )
                    in failure_index
                ),
                "target_provider_item_unresolved",
            )
        else:
            status = "RESOLVED"
            reason = "provider_endpoints_resolved"

        candidates.append(
            ProviderRelationCandidateV1(
                candidate_id=_candidate_id(reference),
                provider_relation_id=reference.provider_relation_id,
                relation_candidate=relation,
                source_ownership="PROJECTED" if projected else "HOST",
                host_source_id=host_source_id,
                canonical_source_id=(
                    projected_source[0]
                    if projected_source is not None
                    else None
                    if projected
                    else host_source_id
                ),
                canonical_source_type=(
                    projected_source[1]
                    if projected_source is not None
                    else None
                    if projected
                    else host_source_type
                ),
                canonical_target_ids=resolved_targets,
                canonical_target_types=resolved_target_types,
                status=status,
                reason_code=reason,
                evidence=evidence,
                reference=reference,
            )
        )
    return tuple(candidates)


def write_provider_relation_candidates(
    path: Path, candidates: tuple[ProviderRelationCandidateV1, ...]
) -> None:
    content = "".join(
        json.dumps(
            candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        )
        + "\n"
        for candidate in candidates
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _classify_relation(reference: ProviderReferenceMentionV1, source_text: str) -> str:
    if reference.provider_link_type == "REFERENCE":
        return "REFERS_TO"
    if reference.provider_link_type != "CHANGE_CONTENT":
        return "UNKNOWN"
    line_start = source_text.rfind("\n", 0, reference.source_char_start) + 1
    prefix = (
        re.sub(r"\s+", " ", source_text[line_start : reference.source_char_start])
        .strip()
        .lower()
    )
    if re.search(r"\bbổ sung\b.+\bvào\s+sau\s*$", prefix):
        return "POSITIONAL_ANCHOR"
    if re.search(r"\bsửa đổi(?:\s*,\s*bổ sung)?\s*$", prefix):
        return "AMENDS"
    if re.search(r"\bbãi bỏ(?:\s+(?:các|toàn bộ))?\s*$", prefix):
        return "REPEALS"
    if re.search(r"\b(?:thay|bổ sung)\b.+\btại\s*$", prefix):
        return "AMENDS"
    return "UNKNOWN"


def _smallest_source_unit(
    parsed: ParsedDocument,
    registry: StructuralRegistry,
    start: int,
    end: int,
) -> tuple[str | None, str | None]:
    for article in parsed.articles:
        for clause in article.clauses:
            for point in clause.points:
                if point.source_start_char <= start and end <= point.source_end_char:
                    key = (article.number, clause.number, point.label.strip().lower())
                    return registry.points.get(key), "Point"
            if clause.source_start_char <= start and end <= clause.source_end_char:
                return registry.clauses.get((article.number, clause.number)), "Clause"
        if article.source_start_char <= start and end <= article.source_end_char:
            return registry.articles.get(article.number), "Article"
    return None, None


def _inside_open_replacement_quote(source_text: str, offset: int) -> bool:
    prefix = source_text[:offset]
    return prefix.rfind("“") > prefix.rfind("”")


def _projected_source_endpoint(
    reference: ProviderReferenceMentionV1,
    references: tuple[ProviderReferenceMentionV1, ...],
    source_text: str,
    unit_index: ProviderUnitIndex,
) -> tuple[str, str] | None:
    """Resolve quoted content ownership from its governing amendment target."""

    governing_references = sorted(
        (
            candidate
            for candidate in references
            if candidate.provider_link_type == "CHANGE_CONTENT"
            and candidate.source_char_end <= reference.source_char_start
            and _quote_opened_between(
                source_text, candidate.source_char_end, reference.source_char_start
            )
        ),
        key=lambda candidate: candidate.source_char_end,
        reverse=True,
    )
    for governing in governing_references:
        endpoints = {
            unit_index[
                (
                    governing.provider,
                    governing.provider_target_document_id or "",
                    item_id,
                )
            ]
            for item_id in governing.provider_target_item_ids
            if (
                governing.provider,
                governing.provider_target_document_id or "",
                item_id,
            )
            in unit_index
        }
        if len(endpoints) == 1:
            return next(iter(endpoints))
    return None


def _quote_opened_between(source_text: str, start: int, end: int) -> bool:
    segment = source_text[start:end]
    return segment.rfind("“") > segment.rfind("”")


def _source_line(source_text: str, offset: int) -> str:
    start = source_text.rfind("\n", 0, offset) + 1
    end = source_text.find("\n", offset)
    return source_text[start : len(source_text) if end < 0 else end].strip()


def _candidate_id(reference: ProviderReferenceMentionV1) -> str:
    identity = "|".join(
        (
            reference.provider,
            reference.provider_source_document_id,
            reference.provider_source_item_id or "",
            reference.provider_target_document_id or "",
            ",".join(reference.provider_target_item_ids),
            reference.provider_relation_id or "",
            str(reference.source_char_start),
            str(reference.source_char_end),
        )
    )
    return f"provider-rel-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"
