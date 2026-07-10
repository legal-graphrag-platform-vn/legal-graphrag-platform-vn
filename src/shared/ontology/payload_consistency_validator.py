"""Whole-payload consistency checks before write-time ontology validation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping


STRUCTURAL_PAIRS = {
    ("Document", "Chapter"),
    ("Chapter", "Article"),
    ("Document", "Article"),
    ("Article", "Clause"),
    ("Clause", "Point"),
}
TEMPORAL_RELATIONS = {"AMENDS", "REPEALS", "REPLACES"}


class PayloadConsistencyError(ValueError):
    """Raised when a graph payload is internally inconsistent."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True, slots=True)
class PayloadConsistencyReport:
    valid: bool
    errors: tuple[str, ...] = ()
    duplicate_node_id_count: int = 0
    duplicate_relation_identity_count: int = 0
    orphan_node_count: int = 0
    connected_component_count: int = 0
    relation_count_by_type: dict[str, int] = field(default_factory=dict)


def relation_identity(relation: Mapping) -> str:
    effective_from = (relation.get("properties") or {}).get("effective_from", "")
    if relation.get("type") not in TEMPORAL_RELATIONS:
        effective_from = ""
    return "|".join(
        [
            str(relation.get("head_id", "")),
            str(relation.get("type", "")),
            str(relation.get("tail_id", "")),
            str(effective_from or ""),
        ]
    )


def deterministic_relation_id(head_id: str, relation_type: str, tail_id: str, effective_from: str | None = None) -> str:
    source = "|".join([head_id, relation_type, tail_id, effective_from or ""])
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def validate_payload_consistency(payload: Mapping) -> PayloadConsistencyReport:
    nodes = list(payload.get("nodes", []))
    relations = list(payload.get("relations", []))
    errors: list[str] = []

    node_ids = [str(node.get("id", "")) for node in nodes]
    node_counts = Counter(node_ids)
    duplicate_node_ids = {node_id for node_id, count in node_counts.items() if count > 1}
    for node_id in sorted(duplicate_node_ids):
        errors.append(f"Duplicate node id: {node_id}")

    node_types = {str(node.get("id")): str(node.get("type")) for node in nodes}
    seen_relation_identities: set[str] = set()
    duplicate_relation_identity_count = 0
    relation_count_by_type: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)

    for relation in relations:
        head_id = str(relation.get("head_id", ""))
        tail_id = str(relation.get("tail_id", ""))
        relation_type = str(relation.get("type", ""))
        relation_count_by_type[relation_type] += 1

        if head_id not in node_types:
            errors.append(f"Dangling relation head_id: {head_id}")
        if tail_id not in node_types:
            errors.append(f"Dangling relation tail_id: {tail_id}")

        identity = relation_identity(relation)
        if identity in seen_relation_identities:
            duplicate_relation_identity_count += 1
            errors.append(f"Duplicate relation identity: {identity}")
        seen_relation_identities.add(identity)

        effective_from = (relation.get("properties") or {}).get("effective_from") if relation_type in TEMPORAL_RELATIONS else None
        expected_relation_id = deterministic_relation_id(head_id, relation_type, tail_id, effective_from)
        actual_relation_id = (relation.get("properties") or {}).get("relation_id")
        if not actual_relation_id:
            errors.append(f"Missing relation_id for {identity}")
        elif actual_relation_id != expected_relation_id:
            errors.append(f"Malformed relation_id for {identity}")

        if relation_type == "CONTAINS":
            pair = (node_types.get(head_id), node_types.get(tail_id))
            if pair not in STRUCTURAL_PAIRS:
                errors.append(f"Invalid CONTAINS chain: {pair[0]} -> {pair[1]}")

        if head_id in node_types and tail_id in node_types:
            degree[head_id] += 1
            degree[tail_id] += 1
            adjacency[head_id].add(tail_id)
            adjacency[tail_id].add(head_id)

    orphan_count = 0
    for node_id, node_type in node_types.items():
        if node_type not in {"Document"} and degree[node_id] == 0:
            orphan_count += 1
            errors.append(f"Orphan node: {node_id}")

    component_count = _connected_component_count(node_types.keys(), adjacency)

    return PayloadConsistencyReport(
        valid=not errors,
        errors=tuple(errors),
        duplicate_node_id_count=len(duplicate_node_ids),
        duplicate_relation_identity_count=duplicate_relation_identity_count,
        orphan_node_count=orphan_count,
        connected_component_count=component_count,
        relation_count_by_type=dict(relation_count_by_type),
    )


def validate_payload_consistency_or_raise(payload: Mapping) -> PayloadConsistencyReport:
    report = validate_payload_consistency(payload)
    if not report.valid:
        raise PayloadConsistencyError(report.errors)
    return report


def _connected_component_count(node_ids: Iterable[str], adjacency: Mapping[str, set[str]]) -> int:
    unvisited = set(node_ids)
    count = 0
    while unvisited:
        count += 1
        start = unvisited.pop()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    queue.append(neighbor)
    return count
