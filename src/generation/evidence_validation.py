"""Fail-closed validation of retrieval evidence entering answer generation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from src.generation.errors import EvidenceContractError
from src.retrieval.models import GraphPath, RetrievalContext, RetrievedUnit
from src.shared.ontology.contract import RELATION_ENUM


_CANONICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


@dataclass(frozen=True)
class EvidenceCandidate:
    unit: RetrievedUnit
    rank: int
    is_eligible: bool


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
        eligible_ids = {item.unit_id for item in context.evidence if item.is_eligible}
        candidates = tuple(
            EvidenceCandidate(
                unit=self._validate_unit(unit, context),
                rank=rank,
                is_eligible=unit.id in eligible_ids,
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
        if len(path.nodes) != len(path.edges) + 1:
            raise EvidenceContractError("Graph path node/edge cardinality is invalid")
        if not path.edges:
            raise EvidenceContractError("Graph path must contain at least one relation")
        node_ids: list[str] = []
        for node in path.nodes:
            _require_canonical_id(node.node_id, "graph path node ID")
            node_ids.append(node.node_id)
            if node.citable_unit_id is not None:
                _require_canonical_id(node.citable_unit_id, "citable unit ID")
        relation_ids: list[str] = []
        for left, edge, right in zip(
            path.nodes, path.edges, path.nodes[1:], strict=False
        ):
            if edge.relation_type not in RELATION_ENUM:
                raise EvidenceContractError(
                    f"Graph path relation type is not canonical: {edge.relation_type}"
                )
            _require_canonical_id(edge.relation_id, "graph path relation ID")
            _require_canonical_id(edge.source_id, "graph edge source ID")
            _require_canonical_id(edge.target_id, "graph edge target ID")
            if {edge.source_id, edge.target_id} != {left.node_id, right.node_id}:
                raise EvidenceContractError(
                    f"Graph edge does not connect adjacent nodes: {edge.relation_id}"
                )
            relation_ids.append(edge.relation_id)
        if len(relation_ids) != len(set(relation_ids)):
            raise EvidenceContractError("Graph path relation IDs must be unique")
        if not path.path_description.strip():
            raise EvidenceContractError("Graph path description must not be blank")
        return path


def build_path_id(path: GraphPath) -> str:
    canonical = json.dumps(
        {
            "nodes": [node.model_dump(mode="json") for node in path.nodes],
            "edges": [edge.model_dump(mode="json") for edge in path.edges],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "path_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _require_canonical_id(value: str, field_name: str) -> None:
    if not value or _CANONICAL_ID.fullmatch(value) is None:
        raise EvidenceContractError(f"Invalid canonical {field_name}: {value!r}")
