"""Whole-payload consistency checks before write-time ontology validation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from src.shared.ontology.hierarchy import legal_number_sort_key


STRUCTURAL_PAIRS = {
    ("Document", "Part"),
    ("Document", "Chapter"),
    ("Document", "Section"),
    ("Part", "Chapter"),
    ("Part", "Section"),
    ("Part", "Article"),
    ("Chapter", "Section"),
    ("Chapter", "Article"),
    ("Section", "Subsection"),
    ("Section", "Article"),
    ("Subsection", "Article"),
    ("Document", "Article"),
    ("Document", "Appendix"),
    ("Document", "AttachedInstrument"),
    ("AttachedInstrument", "Appendix"),
    ("AttachedInstrument", "Part"),
    ("AttachedInstrument", "Chapter"),
    ("AttachedInstrument", "Section"),
    ("AttachedInstrument", "Article"),
    ("Appendix", "Part"),
    ("Appendix", "Chapter"),
    ("Appendix", "Section"),
    ("Appendix", "Article"),
    ("Article", "Clause"),
    ("Clause", "Point"),
}
STRUCTURAL_LABELS = {
    "Document",
    "Appendix",
    "AttachedInstrument",
    "Part",
    "Chapter",
    "Section",
    "Subsection",
    "Article",
    "Clause",
    "Point",
}
GROUPING_CHILD_MODES = {
    "Chapter": {"Section", "Article"},
    "Section": {"Subsection", "Article"},
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
    discriminator = relation_identity_discriminator(
        str(relation.get("type", "")), relation.get("properties") or {}
    )
    return "|".join(
        [
            str(relation.get("head_id", "")),
            str(relation.get("type", "")),
            str(relation.get("tail_id", "")),
            discriminator,
        ]
    )


def deterministic_relation_id(
    head_id: str, relation_type: str, tail_id: str, discriminator: str | None = None
) -> str:
    source = "|".join([head_id, relation_type, tail_id, discriminator or ""])
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def relation_identity_discriminator(relation_type: str, properties: Mapping) -> str:
    if relation_type in TEMPORAL_RELATIONS:
        return str(properties.get("effective_from") or "")
    if relation_type == "REQUIRES":
        return str(properties.get("source_article") or "")
    if relation_type == "REFERS_TO":
        citation_type = str(properties.get("citation_type") or "")
        citation_text = normalize_citation_text(
            str(properties.get("citation_text") or "")
        )
        return f"{citation_type}|{citation_text}"
    return ""


def normalize_citation_text(value: str) -> str:
    """Canonicalize citation identity without removing Vietnamese characters."""
    normalized = unicodedata.normalize("NFC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def validate_payload_consistency(payload: Mapping) -> PayloadConsistencyReport:
    nodes = list(payload.get("nodes", []))
    relations = list(payload.get("relations", []))
    errors: list[str] = []

    node_ids = [str(node.get("id", "")) for node in nodes]
    node_counts = Counter(node_ids)
    duplicate_node_ids = {
        node_id for node_id, count in node_counts.items() if count > 1
    }
    for node_id in sorted(duplicate_node_ids):
        errors.append(f"Duplicate node id: {node_id}")

    node_types = {str(node.get("id")): str(node.get("type")) for node in nodes}
    node_numbers = {str(node.get("id")): node.get("number") for node in nodes}
    seen_relation_identities: set[str] = set()
    duplicate_relation_identity_count = 0
    relation_count_by_type: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)
    reference_bundles: dict[str, list[Mapping]] = defaultdict(list)
    structural_parents: dict[str, list[str]] = defaultdict(list)
    structural_children: dict[str, list[str]] = defaultdict(list)
    structural_child_types: dict[str, set[str]] = defaultdict(set)

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

        discriminator = relation_identity_discriminator(
            relation_type, relation.get("properties") or {}
        )
        expected_relation_id = deterministic_relation_id(
            head_id, relation_type, tail_id, discriminator
        )
        actual_relation_id = (relation.get("properties") or {}).get("relation_id")
        if not actual_relation_id:
            errors.append(f"Missing relation_id for {identity}")
        elif actual_relation_id != expected_relation_id:
            errors.append(f"Malformed relation_id for {identity}")

        if relation_type == "CONTAINS":
            pair = (node_types.get(head_id), node_types.get(tail_id))
            if pair not in STRUCTURAL_PAIRS:
                errors.append(f"Invalid CONTAINS chain: {pair[0]} -> {pair[1]}")
            elif head_id in node_types and tail_id in node_types:
                structural_parents[tail_id].append(head_id)
                structural_children[head_id].append(tail_id)
                if (
                    pair[0] in GROUPING_CHILD_MODES
                    and pair[1] in GROUPING_CHILD_MODES[pair[0]]
                ):
                    structural_child_types[head_id].add(pair[1])
        elif relation_type == "REFERS_TO":
            bundle_id = str(
                (relation.get("properties") or {}).get("reference_bundle_id") or ""
            )
            if bundle_id:
                reference_bundles[bundle_id].append(relation)

        if head_id in node_types and tail_id in node_types:
            degree[head_id] += 1
            degree[tail_id] += 1
            adjacency[head_id].add(tail_id)
            adjacency[tail_id].add(head_id)

    _validate_structural_hierarchy(
        node_types,
        node_numbers,
        structural_parents,
        structural_children,
        structural_child_types,
        errors,
    )

    for bundle_id, bundle_relations in reference_bundles.items():
        expected_counts = {
            (relation.get("properties") or {}).get("reference_target_count")
            for relation in bundle_relations
        }
        if len(expected_counts) != 1:
            errors.append(f"Conflicting reference_target_count for bundle: {bundle_id}")
            continue
        expected_count = next(iter(expected_counts))
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count < 1
        ):
            errors.append(f"Invalid reference_target_count for bundle: {bundle_id}")
        elif len(bundle_relations) != expected_count:
            errors.append(
                f"Incomplete reference bundle {bundle_id}: "
                f"expected {expected_count}, got {len(bundle_relations)}"
            )

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


def _validate_structural_hierarchy(
    node_types: Mapping[str, str],
    node_numbers: Mapping[str, object],
    structural_parents: Mapping[str, list[str]],
    structural_children: Mapping[str, list[str]],
    structural_child_types: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    for node_id, node_type in node_types.items():
        if node_type not in STRUCTURAL_LABELS or node_type == "Document":
            continue
        parents = structural_parents.get(node_id, [])
        if len(parents) != 1:
            errors.append(
                f"Structural node {node_id} must have exactly one CONTAINS parent; "
                f"got {len(parents)}"
            )

    for parent_id, child_types in structural_child_types.items():
        parent_type = node_types[parent_id]
        if len(child_types) > 1:
            if parent_type == "Chapter" and child_types == {"Article", "Section"}:
                ordering_error = _chapter_preamble_ordering_error(
                    chapter_id=parent_id,
                    node_types=node_types,
                    node_numbers=node_numbers,
                    structural_children=structural_children,
                )
                if ordering_error is not None:
                    errors.append(ordering_error)
                continue
            errors.append(
                f"{parent_type} {parent_id} mixes structural child modes: "
                f"{', '.join(sorted(child_types))}"
            )

    for node_id, node_type in node_types.items():
        if node_type not in STRUCTURAL_LABELS or node_type == "Document":
            continue
        visited: set[str] = set()
        current = node_id
        while node_types.get(current) != "Document":
            if current in visited:
                errors.append(f"Structural CONTAINS cycle reaches {node_id}")
                break
            visited.add(current)
            parents = structural_parents.get(current, [])
            if len(parents) != 1:
                break
            current = parents[0]


def _chapter_preamble_ordering_error(
    *,
    chapter_id: str,
    node_types: Mapping[str, str],
    node_numbers: Mapping[str, object],
    structural_children: Mapping[str, list[str]],
) -> str | None:
    direct_article_ids = [
        child_id
        for child_id in structural_children.get(chapter_id, [])
        if node_types.get(child_id) == "Article"
    ]
    section_article_ids: list[str] = []
    for child_id in structural_children.get(chapter_id, []):
        if node_types.get(child_id) == "Section":
            section_article_ids.extend(
                _descendant_article_ids(
                    child_id,
                    node_types=node_types,
                    structural_children=structural_children,
                )
            )

    direct_numbers = [node_numbers.get(node_id) for node_id in direct_article_ids]
    section_numbers = [node_numbers.get(node_id) for node_id in section_article_ids]
    if (
        not direct_numbers
        or not section_numbers
        or any(number in (None, "") for number in direct_numbers + section_numbers)
    ):
        return f"Chapter {chapter_id} cannot validate mixed child ordering"

    latest_direct = max(
        (str(number) for number in direct_numbers), key=legal_number_sort_key
    )
    first_section = min(
        (str(number) for number in section_numbers), key=legal_number_sort_key
    )
    if legal_number_sort_key(latest_direct) >= legal_number_sort_key(first_section):
        return (
            f"Chapter {chapter_id} direct Article {latest_direct} must precede "
            f"first Section Article {first_section}"
        )
    return None


def _descendant_article_ids(
    root_id: str,
    *,
    node_types: Mapping[str, str],
    structural_children: Mapping[str, list[str]],
) -> list[str]:
    article_ids: list[str] = []
    queue = deque(structural_children.get(root_id, []))
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        if node_types.get(node_id) == "Article":
            article_ids.append(node_id)
            continue
        queue.extend(structural_children.get(node_id, []))
    return article_ids


def validate_payload_consistency_or_raise(payload: Mapping) -> PayloadConsistencyReport:
    report = validate_payload_consistency(payload)
    if not report.valid:
        raise PayloadConsistencyError(report.errors)
    return report


def _connected_component_count(
    node_ids: Iterable[str], adjacency: Mapping[str, set[str]]
) -> int:
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
