"""Guarded reconciliation of legacy Chapter-to-Article containment edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.shared.ontology import validators as ontology_validators


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


class HierarchyReconciliationError(RuntimeError):
    """Raised when validated Section chains are not present before cleanup."""


@dataclass(frozen=True, slots=True)
class HierarchyReconciliationReport:
    mapping_count: int
    deleted_legacy_edge_count: int


@dataclass(slots=True)
class SectionHierarchyReconciler:
    session: SessionProtocol

    def reconcile(self, payload: Any) -> HierarchyReconciliationReport:
        if (
            not isinstance(payload, ontology_validators.ValidatedGraphPayload)
            or payload.validation_token is not ontology_validators._VALIDATION_TOKEN
        ):
            raise TypeError(
                "SectionHierarchyReconciler expects a root ValidatedGraphPayload"
            )

        mappings = _section_article_mappings(payload)
        if not mappings:
            return HierarchyReconciliationReport(0, 0)

        rows = list(
            self.session.run(
                _RECONCILE_QUERY,
                mappings=mappings,
            )
        )
        if not rows:
            raise HierarchyReconciliationError(
                "Section hierarchy reconciliation returned no verification result"
            )
        row = rows[0]
        all_chains_exist = bool(_row_value(row, "all_chains_exist"))
        if not all_chains_exist:
            raise HierarchyReconciliationError(
                "Validated Chapter->Section->Article chain is missing; legacy edges were preserved"
            )
        return HierarchyReconciliationReport(
            mapping_count=len(mappings),
            deleted_legacy_edge_count=int(
                _row_value(row, "deleted_legacy_edge_count") or 0
            ),
        )


def _section_article_mappings(payload: Any) -> list[dict[str, str]]:
    chapter_parents: dict[str, list[str]] = {}
    section_articles: list[tuple[str, str]] = []
    for relation in payload.relations:
        if relation.relation_type != "CONTAINS":
            continue
        if relation.head_type == "Chapter" and relation.tail_type == "Section":
            chapter_parents.setdefault(relation.tail_id, []).append(relation.head_id)
        elif relation.head_type == "Section" and relation.tail_type == "Article":
            section_articles.append((relation.head_id, relation.tail_id))

    mappings: list[dict[str, str]] = []
    for section_id, article_id in section_articles:
        parents = sorted(set(chapter_parents.get(section_id, [])))
        if len(parents) != 1:
            raise HierarchyReconciliationError(
                f"Section {section_id} must have exactly one Chapter parent in validated payload"
            )
        mappings.append(
            {
                "chapter_id": parents[0],
                "section_id": section_id,
                "article_id": article_id,
            }
        )
    return sorted(
        mappings,
        key=lambda item: (
            item["chapter_id"],
            item["section_id"],
            item["article_id"],
        ),
    )


def _row_value(row: Any, key: str) -> Any:
    return row.get(key) if isinstance(row, dict) else row[key]


_RECONCILE_QUERY = """
UNWIND $mappings AS mapping
OPTIONAL MATCH (chapter:Chapter {id: mapping.chapter_id})
OPTIONAL MATCH (section:Section {id: mapping.section_id})
OPTIONAL MATCH (article:Article {id: mapping.article_id})
WITH mapping,
     chapter IS NOT NULL
     AND section IS NOT NULL
     AND article IS NOT NULL
     AND EXISTS {
       MATCH (chapter)-[:CONTAINS]->(section)-[:CONTAINS]->(article)
     } AS chain_exists
WITH collect(mapping) AS mappings, collect(chain_exists) AS chain_checks
WITH mappings, all(item IN chain_checks WHERE item) AS all_chains_exist
CALL {
  WITH mappings, all_chains_exist
  UNWIND mappings AS mapping
  OPTIONAL MATCH (chapter:Chapter {id: mapping.chapter_id})
                 -[legacy:CONTAINS]->
                 (article:Article {id: mapping.article_id})
  WITH all_chains_exist, collect(legacy) AS legacy_edges
  FOREACH (
    edge IN CASE WHEN all_chains_exist THEN legacy_edges ELSE [] END
    | DELETE edge
  )
  RETURN CASE
    WHEN all_chains_exist THEN size(legacy_edges)
    ELSE 0
  END AS deleted_legacy_edge_count
}
RETURN all_chains_exist, deleted_legacy_edge_count
"""
