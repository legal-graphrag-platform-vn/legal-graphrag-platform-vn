"""Intent-aware expansion of canonical legal graph paths."""

from datetime import date

from src.retrieval.mapping import map_retrieved_unit
from src.retrieval.models import (
    GraphExpansion,
    GraphPath,
    IntentType,
    RetrievalFilters,
    RetrievedUnit,
)
from src.retrieval.ports import GraphExpansionPort
from src.retrieval.retriever.policies import policy_for


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
        for row in rows:
            nodes = [str(node_id) for node_id in row.get("path_nodes", [])]
            relations = [str(relation) for relation in row.get("path_relations", [])]
            relation_ids = [
                str(relation_id) for relation_id in row.get("path_relation_ids", [])
            ]
            is_temporal_valid = _is_path_temporally_valid(
                row.get("path_temporal_nodes", []), active_filters.query_date
            )
            paths.append(
                GraphPath(
                    nodes=nodes,
                    relations=relations,
                    relation_ids=relation_ids,
                    path_description=_describe_path(nodes, relations),
                    is_temporal_valid=is_temporal_valid,
                )
            )
            if row.get("id") and row.get("document_id") and is_temporal_valid:
                mapped_row = dict(row)
                mapped_row["score"] = 0.0
                unit = map_retrieved_unit(mapped_row, score_field="graph_score")
                if unit.id not in units_by_id:
                    units_by_id[unit.id] = unit

        paths.sort(key=_path_rank_key)
        first_occurrence: dict[str, int] = {}
        for index, path in enumerate(paths, start=1):
            for node_id in path.nodes:
                if node_id in units_by_id:
                    first_occurrence.setdefault(node_id, index)
        units = sorted(
            units_by_id.values(),
            key=lambda unit: (first_occurrence.get(unit.id, len(paths) + 1), unit.id),
        )
        for rank, unit in enumerate(units, start=1):
            unit.graph_score = 1.0 / rank
        return GraphExpansion(paths=paths, units=units)


def _is_path_temporally_valid(nodes: list[dict], query_date: date | None) -> bool:
    if query_date is None:
        return True
    for node in nodes:
        labels = set(node.get("labels") or [])
        if not labels.intersection({"Document", "Article", "Clause"}):
            continue
        effective_from = _native_date(node.get("effective_from"))
        effective_to = _native_date(node.get("effective_to"))
        if effective_from is None:
            return False
        if effective_from > query_date:
            return False
        if effective_to is not None and effective_to <= query_date:
            return False
    return True


def _native_date(value: object) -> date | None:
    if value is None:
        return None
    native = value.to_native() if hasattr(value, "to_native") else value
    return native if isinstance(native, date) else None


def _describe_path(nodes: list[str], relations: list[str]) -> str:
    if not nodes:
        return "Empty graph path"
    parts = [nodes[0]]
    for relation, target in zip(relations, nodes[1:], strict=False):
        parts.extend((f"-[{relation}]->", target))
    return " ".join(parts)


def _path_rank_key(
    path: GraphPath,
) -> tuple[int, str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    source_id = path.nodes[0] if path.nodes else ""
    target_id = path.nodes[-1] if path.nodes else ""
    return (
        len(path.relations),
        source_id,
        target_id,
        tuple(path.relations),
        tuple(path.nodes),
        tuple(path.relation_ids),
    )
