"""Intent-aware expansion of canonical legal graph paths."""

from datetime import date

from pydantic import ValidationError

from src.retrieval.mapping import map_retrieved_unit
from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import (
    GraphEdge,
    GraphExpansion,
    GraphExpansionDiagnostics,
    GraphCitationEvidence,
    GraphNodeRef,
    GraphPath,
    IntentType,
    RetrievalFilters,
    RetrievedUnit,
)
from src.retrieval.ports import GraphExpansionPort
from src.retrieval.retriever.policies import policy_for
from src.shared.ontology.contract import RELATION_ENUM


_TEMPORAL_RELATIONS = {"AMENDS", "REPEALS", "REPLACES"}
_TEMPORAL_NODE_LABELS = {"Document", "Article", "Clause"}


class GraphRetriever:
    def __init__(self, repo: GraphExpansionPort) -> None:
        self._repo = repo

    def expand(
        self,
        entry_ids: list[str],
        intent: IntentType,
        *,
        filters: RetrievalFilters | None = None,
    ) -> GraphExpansion:
        if not entry_ids:
            return GraphExpansion()

        active_filters = filters or RetrievalFilters()
        policy = policy_for(intent)
        rows = self._repo.graph_expansion(
            entry_ids,
            policy.relations,
            policy.direction,
            policy.max_depth,
            filters=active_filters,
        )
        paths: list[GraphPath] = []
        units_by_id: dict[str, RetrievedUnit] = {}
        temporal_rejected = 0
        for row in rows:
            path = _map_path(row)
            if not _is_path_temporally_valid(path, active_filters.query_date):
                temporal_rejected += 1
                continue
            paths.append(path)
            if row.get("id") and row.get("document_id"):
                mapped_row = dict(row)
                mapped_row["score"] = 0.0
                unit = map_retrieved_unit(mapped_row, score_field="graph_score")
                if unit.id not in units_by_id:
                    units_by_id[unit.id] = unit

        paths = _deduplicate_topology_paths(paths)
        paths.sort(key=_path_rank_key)
        first_occurrence: dict[str, int] = {}
        for index, path in enumerate(paths, start=1):
            for node in path.nodes:
                node_id = node.citable_unit_id or node.node_id
                if node_id in units_by_id:
                    first_occurrence.setdefault(node_id, index)
        units = sorted(
            units_by_id.values(),
            key=lambda unit: (first_occurrence.get(unit.id, len(paths) + 1), unit.id),
        )
        for rank, unit in enumerate(units, start=1):
            unit.graph_score = 1.0 / rank
        return GraphExpansion(
            paths=paths,
            units=units,
            diagnostics=GraphExpansionDiagnostics(
                accepted_path_count=len(paths),
                temporal_rejected_path_count=temporal_rejected,
            ),
        )


def _map_path(row: dict) -> GraphPath:
    try:
        nodes = tuple(
            GraphNodeRef(
                node_id=_required_text(raw.get("node_id"), "graph node ID"),
                labels=_required_labels(raw.get("labels")),
                effective_from=_native_date(raw.get("effective_from")),
                effective_to=_native_date(raw.get("effective_to")),
                legal_status=_optional_text(raw.get("legal_status")),
                citable_unit_id=_optional_text(raw.get("citable_unit_id")),
            )
            for raw in row.get("path_node_refs") or ()
        )
        edges = tuple(_map_edge(raw) for raw in row.get("path_edge_refs") or ())
        _validate_path_shape(nodes, edges)
        return GraphPath(
            nodes=nodes,
            edges=edges,
            path_description=_describe_path(nodes, edges),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise RetrievalOutputError(f"Malformed graph expansion path: {exc}") from exc


def _map_edge(raw: dict) -> GraphEdge:
    relation_type = _required_text(raw.get("relation_type"), "relation type")
    if relation_type not in RELATION_ENUM:
        raise ValueError(f"non-canonical relation type: {relation_type}")
    effective_from = _native_date(raw.get("effective_from"))
    if relation_type in _TEMPORAL_RELATIONS and effective_from is None:
        raise ValueError(f"{relation_type} requires effective_from")
    return GraphEdge(
        relation_id=_required_text(raw.get("relation_id"), "relation ID"),
        relation_type=relation_type,
        source_id=_required_text(raw.get("source_id"), "edge source ID"),
        target_id=_required_text(raw.get("target_id"), "edge target ID"),
        effective_from=effective_from,
        effective_to=_native_date(raw.get("effective_to")),
        citation_evidence=(
            GraphCitationEvidence(
                relation_id=_required_text(raw.get("relation_id"), "relation ID"),
                citation_text=_optional_text(raw.get("citation_text")),
                citation_type=_optional_text(raw.get("citation_type")),
                extraction_method=_optional_text(raw.get("extraction_method")),
            ),
        )
        if relation_type == "REFERS_TO"
        else (),
    )


def _validate_path_shape(
    nodes: tuple[GraphNodeRef, ...], edges: tuple[GraphEdge, ...]
) -> None:
    if not edges or len(nodes) != len(edges) + 1:
        raise ValueError("graph path node/edge cardinality is invalid")
    relation_ids = [edge.relation_id for edge in edges]
    if len(relation_ids) != len(set(relation_ids)):
        raise ValueError("graph path relation IDs must be unique")
    for left, edge, right in zip(nodes, edges, nodes[1:], strict=False):
        adjacent_ids = {left.node_id, right.node_id}
        if {edge.source_id, edge.target_id} != adjacent_ids:
            raise ValueError(
                f"edge {edge.relation_id} does not connect adjacent path nodes"
            )


def _is_path_temporally_valid(path: GraphPath, query_date: date | None) -> bool:
    if query_date is None:
        return True
    for node in path.nodes:
        if not set(node.labels).intersection(_TEMPORAL_NODE_LABELS):
            continue
        if node.effective_from is None:
            return False
        if node.effective_from > query_date:
            return False
        if node.effective_to is not None and node.effective_to <= query_date:
            return False
    for edge in path.edges:
        if edge.effective_from is not None and edge.effective_from > query_date:
            return False
        if edge.effective_to is not None and edge.effective_to <= query_date:
            return False
    return True


def _native_date(value: object) -> date | None:
    if value is None:
        return None
    native = value.to_native() if hasattr(value, "to_native") else value
    if not isinstance(native, date):
        raise ValueError(f"expected date-compatible value, got {type(value).__name__}")
    return native


def _describe_path(
    nodes: tuple[GraphNodeRef, ...], edges: tuple[GraphEdge, ...]
) -> str:
    if not nodes:
        return "Empty graph path"
    parts = [nodes[0].node_id]
    for current, edge, following in zip(nodes, edges, nodes[1:], strict=False):
        arrow = (
            f"-[{edge.relation_type}]->"
            if edge.source_id == current.node_id
            else f"<-[{edge.relation_type}]-"
        )
        parts.extend((arrow, following.node_id))
    return " ".join(parts)


def _path_rank_key(
    path: GraphPath,
) -> tuple[int, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    source_id = path.nodes[0].node_id if path.nodes else ""
    target_id = path.nodes[-1].node_id if path.nodes else ""
    return (
        len(path.edges),
        source_id,
        target_id,
        tuple(edge.relation_type for edge in path.edges),
        tuple(node.node_id for node in path.nodes),
        tuple(edge.relation_id for edge in path.edges),
    )


def _deduplicate_topology_paths(paths: list[GraphPath]) -> list[GraphPath]:
    grouped: dict[tuple, list[GraphPath]] = {}
    for path in paths:
        key = (
            tuple(node.node_id for node in path.nodes),
            tuple(
                (edge.relation_type, edge.source_id, edge.target_id)
                for edge in path.edges
            ),
        )
        grouped.setdefault(key, []).append(path)

    deduplicated: list[GraphPath] = []
    for group in grouped.values():
        canonical = min(group, key=_path_rank_key)
        merged_edges: list[GraphEdge] = []
        for edge_index, edge in enumerate(canonical.edges):
            citations = {
                evidence.relation_id: evidence
                for path in group
                for evidence in path.edges[edge_index].citation_evidence
            }
            merged_edges.append(
                edge.model_copy(
                    update={
                        "citation_evidence": tuple(
                            citations[key] for key in sorted(citations)
                        ),
                    }
                )
            )
        deduplicated.append(
            canonical.model_copy(
                update={
                    "edges": tuple(merged_edges),
                    "path_description": _describe_path(
                        canonical.nodes, tuple(merged_edges)
                    ),
                }
            )
        )
    return deduplicated


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"missing {field_name}")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("missing graph node labels")
    labels = tuple(str(label).strip() for label in value if str(label).strip())
    if not labels:
        raise ValueError("missing graph node labels")
    return labels
