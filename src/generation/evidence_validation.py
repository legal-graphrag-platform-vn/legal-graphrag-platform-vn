"""Fail-closed validation of retrieval evidence entering answer generation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from src.generation.errors import EvidenceContractError
from src.retrieval.models import GraphPath, RetrievalContext, RetrievedUnit


_CANONICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True)
class EvidenceCandidate:
    unit: RetrievedUnit
    rank: int
    is_sufficient: bool


@dataclass(frozen=True)
class ValidatedPath:
    path: GraphPath
    path_id: str
    rank: int


@dataclass(frozen=True)
class ValidatedEvidence:
    candidates: tuple[EvidenceCandidate, ...]
    paths: tuple[ValidatedPath, ...]


class EvidenceValidator:
    """Validate trusted metadata without re-running retrieval filters."""

    def validate(self, context: RetrievalContext) -> ValidatedEvidence:
        sufficient_ids = {
            item.unit_id for item in context.evidence if item.is_sufficient
        }
        candidates = tuple(
            EvidenceCandidate(
                unit=self._validate_unit(unit, context),
                rank=rank,
                is_sufficient=unit.id in sufficient_ids,
            )
            for rank, unit in enumerate(context.retrieved_units)
        )
        paths = tuple(
            ValidatedPath(
                path=self._validate_path(path),
                path_id=build_path_id(path),
                rank=rank,
            )
            for rank, path in enumerate(context.graph_paths)
        )
        return ValidatedEvidence(candidates=candidates, paths=paths)

    @staticmethod
    def _validate_unit(
        unit: RetrievedUnit,
        context: RetrievalContext,
    ) -> RetrievedUnit:
        _require_canonical_id(unit.id, "unit ID")
        if not unit.content_raw.strip():
            raise EvidenceContractError(f"Evidence {unit.id} has empty content_raw")
        _require_canonical_id(unit.document_id, "document ID")
        if not unit.citation_label.strip():
            raise EvidenceContractError(f"Evidence {unit.id} has no citation label")
        if not unit.deep_link.strip():
            raise EvidenceContractError(f"Evidence {unit.id} has no deep link")

        if unit.label == "Article":
            if unit.article_id != unit.id or unit.clause_id is not None:
                raise EvidenceContractError(
                    f"Article evidence has inconsistent hierarchy IDs: {unit.id}"
                )
        elif unit.label == "Clause":
            if not unit.article_id or unit.clause_id != unit.id:
                raise EvidenceContractError(
                    f"Clause evidence has inconsistent hierarchy IDs: {unit.id}"
                )
        elif not unit.article_id or not unit.clause_id:
            raise EvidenceContractError(
                f"Point evidence has inconsistent hierarchy IDs: {unit.id}"
            )

        filters = context.filters_applied
        if filters.document_ids and unit.document_id not in filters.document_ids:
            raise EvidenceContractError(
                f"Evidence {unit.id} conflicts with applied document filters"
            )
        if filters.legal_statuses and unit.legal_status not in filters.legal_statuses:
            raise EvidenceContractError(
                f"Evidence {unit.id} conflicts with applied legal-status filters"
            )
        return unit.model_copy(update={"content_raw": unit.content_raw.strip()})

    @staticmethod
    def _validate_path(path: GraphPath) -> GraphPath:
        if len(path.nodes) != len(path.relations) + 1:
            raise EvidenceContractError(
                "Graph path node/relation cardinality is invalid"
            )
        if len(path.relation_ids) != len(path.relations):
            raise EvidenceContractError("Graph path relation identity is incomplete")
        if not path.relations:
            raise EvidenceContractError("Graph path must contain at least one relation")
        for node_id in path.nodes:
            _require_canonical_id(node_id, "graph path node ID")
        for relation_type in path.relations:
            if not relation_type.strip():
                raise EvidenceContractError(
                    "Graph path relation type must not be blank"
                )
        for relation_id in path.relation_ids:
            _require_canonical_id(relation_id, "graph path relation ID")
        if not path.path_description.strip():
            raise EvidenceContractError("Graph path description must not be blank")
        return path


def build_path_id(path: GraphPath) -> str:
    canonical = json.dumps(
        {
            "nodes": path.nodes,
            "relations": path.relations,
            "relation_ids": path.relation_ids,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "path_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _require_canonical_id(value: str, field_name: str) -> None:
    if not value or _CANONICAL_ID.fullmatch(value) is None:
        raise EvidenceContractError(f"Invalid canonical {field_name}: {value!r}")
