"""Deterministic structural compaction and mandatory evidence bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date

from src.generation.evidence_validation import (
    EvidenceCandidate,
    ValidatedEvidence,
    ValidatedPath,
)
from src.generation.models import OmittedEvidence
from src.retrieval.models import IntentType, RetrievalContext


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    intent: IntentType
    unit_ids: tuple[str, ...]
    path_ids: tuple[str, ...]
    temporal_subject_ids: tuple[str, ...]
    version_keys: tuple[str, ...]
    source_rank: int


@dataclass(frozen=True)
class CompactionPlan:
    candidates: tuple[EvidenceCandidate, ...]
    paths: tuple[ValidatedPath, ...]
    required_bundle_sets: tuple[tuple[EvidenceBundle, ...], ...]
    omitted_evidence: tuple[OmittedEvidence, ...]


class EvidenceCompactor:
    def compact(
        self,
        context: RetrievalContext,
        validated: ValidatedEvidence,
    ) -> CompactionPlan:
        protected_ids = {
            node.citable_unit_id
            for path in validated.paths
            for node in path.path.nodes
            if node.citable_unit_id is not None
        }
        candidates, omissions = self._deduplicate(
            validated.candidates,
            protected_ids=protected_ids,
        )
        paths = validated.paths
        required = self._resolve_required_bundles(context, candidates, paths)
        return CompactionPlan(
            candidates=candidates,
            paths=paths,
            required_bundle_sets=required,
            omitted_evidence=omissions,
        )

    @staticmethod
    def _deduplicate(
        candidates: tuple[EvidenceCandidate, ...],
        *,
        protected_ids: set[str],
    ) -> tuple[tuple[EvidenceCandidate, ...], tuple[OmittedEvidence, ...]]:
        retained: list[EvidenceCandidate] = []
        omissions: list[OmittedEvidence] = []
        seen: dict[tuple[str, str | None, str], EvidenceCandidate] = {}
        ordered = sorted(candidates, key=lambda item: (item.rank, item.unit.id))
        for candidate in ordered:
            if candidate.unit.id in protected_ids:
                retained.append(candidate)
                continue
            key = (
                candidate.unit.document_id,
                candidate.unit.version_family_id,
                _normalize_content(candidate.unit.content_raw),
            )
            existing = seen.get(key)
            if existing is not None:
                same_branch = _same_legal_branch(existing, candidate)
                omissions.append(
                    OmittedEvidence(
                        unit_id=candidate.unit.id,
                        reason=(
                            "hierarchical_duplicate"
                            if same_branch
                            else "content_duplicate"
                        ),
                        retained_unit_id=existing.unit.id,
                    )
                )
                continue
            seen[key] = candidate
            retained.append(candidate)
        return tuple(retained), tuple(omissions)

    def _resolve_required_bundles(
        self,
        context: RetrievalContext,
        candidates: tuple[EvidenceCandidate, ...],
        paths: tuple[ValidatedPath, ...],
    ) -> tuple[tuple[EvidenceBundle, ...], ...]:
        intent = context.intent
        if intent in {IntentType.FACTUAL, IntentType.DEFINITION}:
            return tuple(
                (self._bundle(intent, (candidate,), ()),)
                for candidate in candidates
                if candidate.is_eligible
            )
        if intent in {IntentType.HIERARCHY, IntentType.MULTI_HOP}:
            required_relation = "CONTAINS" if intent == IntentType.HIERARCHY else None
            alternatives: list[tuple[EvidenceBundle, ...]] = []
            by_id = {candidate.unit.id: candidate for candidate in candidates}
            for path in paths:
                relation_types = {edge.relation_type for edge in path.path.edges}
                if required_relation and required_relation not in relation_types:
                    continue
                citable_ids = tuple(
                    dict.fromkeys(
                        node.citable_unit_id
                        for node in path.path.nodes
                        if node.citable_unit_id is not None
                    )
                )
                if any(node_id not in by_id for node_id in citable_ids):
                    continue
                path_candidates = tuple(by_id[node_id] for node_id in citable_ids)
                if len(path_candidates) < 2:
                    continue
                alternatives.append((self._bundle(intent, path_candidates, (path,)),))
            return tuple(alternatives)
        if intent == IntentType.VALIDITY:
            query_date = context.temporal.resolved_from
            if query_date is None:
                return ()
            return tuple(
                (
                    self._bundle(
                        intent,
                        (candidate,),
                        (),
                        temporal_subject_ids=(candidate.unit.id,),
                    ),
                )
                for candidate in candidates
                if candidate.is_eligible and _valid_on(candidate, query_date)
            )
        if intent == IntentType.COMPARISON:
            by_version: dict[tuple[str, str], EvidenceCandidate] = {}
            for candidate in candidates:
                if candidate.unit.version_family_id is None:
                    continue
                key = (candidate.unit.version_family_id, candidate.unit.document_id)
                by_version.setdefault(key, candidate)
            grouped_families: dict[str, list[EvidenceCandidate]] = {}
            for (family_id, _), candidate in by_version.items():
                grouped_families.setdefault(family_id, []).append(candidate)
            alternatives: list[tuple[EvidenceBundle, ...]] = []
            for family_id, family_candidates in sorted(grouped_families.items()):
                if len(family_candidates) < 2:
                    continue
                alternatives.append(
                    tuple(
                        self._bundle(
                            intent,
                            (candidate,),
                            (),
                            version_keys=(f"{family_id}|{candidate.unit.document_id}",),
                        )
                        for candidate in sorted(
                            family_candidates,
                            key=lambda item: (item.rank, item.unit.id),
                        )
                    )
                )
            by_id = {candidate.unit.id: candidate for candidate in candidates}
            for path in paths:
                if not any(
                    edge.relation_type in {"AMENDS", "REPLACES"}
                    for edge in path.path.edges
                ):
                    continue
                citable_ids = tuple(
                    dict.fromkeys(
                        node.citable_unit_id
                        for node in path.path.nodes
                        if node.citable_unit_id is not None
                    )
                )
                path_candidates = tuple(
                    by_id[node_id] for node_id in citable_ids if node_id in by_id
                )
                if len(path_candidates) >= 2:
                    alternatives.append(
                        (self._bundle(intent, path_candidates, (path,)),)
                    )
            return tuple(alternatives)
        return ()

    @staticmethod
    def _bundle(
        intent: IntentType,
        candidates: tuple[EvidenceCandidate, ...],
        paths: tuple[ValidatedPath, ...],
        *,
        temporal_subject_ids: tuple[str, ...] = (),
        version_keys: tuple[str, ...] = (),
    ) -> EvidenceBundle:
        unit_ids = tuple(dict.fromkeys(item.unit.id for item in candidates))
        path_ids = tuple(dict.fromkeys(item.path_id for item in paths))
        projection = {
            "intent": intent.value,
            "unit_ids": unit_ids,
            "path_ids": path_ids,
            "temporal_subject_ids": temporal_subject_ids,
            "version_keys": version_keys,
        }
        digest = hashlib.sha256(
            json.dumps(
                projection,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:20]
        return EvidenceBundle(
            bundle_id=f"bundle_{digest}",
            intent=intent,
            unit_ids=unit_ids,
            path_ids=path_ids,
            temporal_subject_ids=temporal_subject_ids,
            version_keys=version_keys,
            source_rank=min(item.rank for item in candidates),
        )


def _normalize_content(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _valid_on(candidate: EvidenceCandidate, query_date: date) -> bool:
    unit = candidate.unit
    return (
        unit.effective_from is not None
        and unit.effective_from <= query_date
        and (unit.effective_to is None or query_date < unit.effective_to)
    )


def _version_key(candidate: EvidenceCandidate) -> str:
    unit = candidate.unit
    return f"{unit.version_family_id or ''}|{unit.document_id}"


def _same_legal_branch(
    left: EvidenceCandidate,
    right: EvidenceCandidate,
) -> bool:
    return left.unit.article_id == right.unit.article_id and (
        left.unit.clause_id == right.unit.clause_id
        or left.unit.clause_id is None
        or right.unit.clause_id is None
    )
