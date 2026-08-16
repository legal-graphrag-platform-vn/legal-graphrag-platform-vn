"""Guarded reconciliation of superseded flattened hierarchy edges."""

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
    part_mapping_count: int = 0
    subsection_mapping_count: int = 0


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

        section_mappings = _section_article_mappings(payload)
        part_mappings = _part_chapter_mappings(payload)
        subsection_mappings = _subsection_article_mappings(payload)
        if not section_mappings and not part_mappings and not subsection_mappings:
            return HierarchyReconciliationReport(0, 0)

        deleted = 0
        deleted += self._reconcile_mappings(
            section_mappings,
            _RECONCILE_QUERY,
            "Validated Chapter->Section->Article chain is missing",
        )
        deleted += self._reconcile_mappings(
            part_mappings,
            _PART_RECONCILE_QUERY,
            "Validated Document->Part->Chapter chain is missing",
        )
        deleted += self._reconcile_mappings(
            subsection_mappings,
            _SUBSECTION_RECONCILE_QUERY,
            "Validated Section->Subsection->Article chain is missing",
        )
        return HierarchyReconciliationReport(
            mapping_count=(
                len(section_mappings) + len(part_mappings) + len(subsection_mappings)
            ),
            deleted_legacy_edge_count=deleted,
            part_mapping_count=len(part_mappings),
            subsection_mapping_count=len(subsection_mappings),
        )

    def _reconcile_mappings(
        self,
        mappings: list[dict[str, str]],
        query: str,
        missing_message: str,
    ) -> int:
        if not mappings:
            return 0
        rows = list(self.session.run(query, mappings=mappings))
        if not rows:
            raise HierarchyReconciliationError(
                "Hierarchy reconciliation returned no verification result"
            )
        row = rows[0]
        if not bool(_row_value(row, "all_chains_exist")):
            raise HierarchyReconciliationError(
                f"{missing_message}; legacy edges were preserved"
            )
        return int(_row_value(row, "deleted_legacy_edge_count") or 0)


def _section_article_mappings(payload: Any) -> list[dict[str, str]]:
    chapter_parents: dict[str, list[str]] = {}
    section_articles: list[tuple[str, str]] = []
    subsection_parents: dict[str, list[str]] = {}
    subsection_articles: list[tuple[str, str]] = []
    for relation in payload.relations:
        if relation.relation_type != "CONTAINS":
            continue
        if relation.head_type == "Chapter" and relation.tail_type == "Section":
            chapter_parents.setdefault(relation.tail_id, []).append(relation.head_id)
        elif relation.head_type == "Section" and relation.tail_type == "Article":
            section_articles.append((relation.head_id, relation.tail_id))
        elif relation.head_type == "Section" and relation.tail_type == "Subsection":
            subsection_parents.setdefault(relation.tail_id, []).append(relation.head_id)
        elif relation.head_type == "Subsection" and relation.tail_type == "Article":
            subsection_articles.append((relation.head_id, relation.tail_id))

    for subsection_id, article_id in subsection_articles:
        parents = sorted(set(subsection_parents.get(subsection_id, [])))
        if len(parents) != 1:
            raise HierarchyReconciliationError(
                f"Subsection {subsection_id} must have exactly one Section parent "
                "in validated payload"
            )
        section_articles.append((parents[0], article_id))

    mappings: list[dict[str, str]] = []
    for section_id, article_id in section_articles:
        parents = sorted(set(chapter_parents.get(section_id, [])))
        if len(parents) > 1:
            raise HierarchyReconciliationError(
                f"Section {section_id} must have at most one Chapter parent in validated payload"
            )
        if len(parents) == 1:
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


def _part_chapter_mappings(payload: Any) -> list[dict[str, str]]:
    document_parents: dict[str, list[str]] = {}
    part_chapters: list[tuple[str, str]] = []
    for relation in payload.relations:
        if relation.relation_type != "CONTAINS":
            continue
        if relation.head_type == "Document" and relation.tail_type == "Part":
            document_parents.setdefault(relation.tail_id, []).append(relation.head_id)
        elif relation.head_type == "Part" and relation.tail_type == "Chapter":
            part_chapters.append((relation.head_id, relation.tail_id))

    mappings: list[dict[str, str]] = []
    for part_id, chapter_id in part_chapters:
        parents = sorted(set(document_parents.get(part_id, [])))
        if len(parents) != 1:
            raise HierarchyReconciliationError(
                f"Part {part_id} must have exactly one Document parent in validated payload"
            )
        mappings.append(
            {
                "document_id": parents[0],
                "part_id": part_id,
                "chapter_id": chapter_id,
            }
        )
    return sorted(
        mappings,
        key=lambda item: (item["document_id"], item["part_id"], item["chapter_id"]),
    )


def _subsection_article_mappings(payload: Any) -> list[dict[str, str]]:
    section_parents: dict[str, list[str]] = {}
    subsection_articles: list[tuple[str, str]] = []
    for relation in payload.relations:
        if relation.relation_type != "CONTAINS":
            continue
        if relation.head_type == "Section" and relation.tail_type == "Subsection":
            section_parents.setdefault(relation.tail_id, []).append(relation.head_id)
        elif relation.head_type == "Subsection" and relation.tail_type == "Article":
            subsection_articles.append((relation.head_id, relation.tail_id))

    mappings: list[dict[str, str]] = []
    for subsection_id, article_id in subsection_articles:
        parents = sorted(set(section_parents.get(subsection_id, [])))
        if len(parents) != 1:
            raise HierarchyReconciliationError(
                f"Subsection {subsection_id} must have exactly one Section parent in validated payload"
            )
        mappings.append(
            {
                "section_id": parents[0],
                "subsection_id": subsection_id,
                "article_id": article_id,
            }
        )
    return sorted(
        mappings,
        key=lambda item: (
            item["section_id"],
            item["subsection_id"],
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


_PART_RECONCILE_QUERY = """
UNWIND $mappings AS mapping
OPTIONAL MATCH (document:Document {id: mapping.document_id})
OPTIONAL MATCH (part:Part {id: mapping.part_id})
OPTIONAL MATCH (chapter:Chapter {id: mapping.chapter_id})
WITH mapping,
     document IS NOT NULL
     AND part IS NOT NULL
     AND chapter IS NOT NULL
     AND EXISTS {
       MATCH (document)-[:CONTAINS]->(part)-[:CONTAINS]->(chapter)
     } AS chain_exists
WITH collect(mapping) AS mappings, collect(chain_exists) AS chain_checks
WITH mappings, all(item IN chain_checks WHERE item) AS all_chains_exist
CALL {
  WITH mappings, all_chains_exist
  UNWIND mappings AS mapping
  OPTIONAL MATCH (document:Document {id: mapping.document_id})
                 -[legacy:CONTAINS]->
                 (chapter:Chapter {id: mapping.chapter_id})
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


_SUBSECTION_RECONCILE_QUERY = """
UNWIND $mappings AS mapping
OPTIONAL MATCH (section:Section {id: mapping.section_id})
OPTIONAL MATCH (subsection:Subsection {id: mapping.subsection_id})
OPTIONAL MATCH (article:Article {id: mapping.article_id})
WITH mapping,
     section IS NOT NULL
     AND subsection IS NOT NULL
     AND article IS NOT NULL
     AND EXISTS {
       MATCH (section)-[:CONTAINS]->(subsection)-[:CONTAINS]->(article)
     } AS chain_exists
WITH collect(mapping) AS mappings, collect(chain_exists) AS chain_checks
WITH mappings, all(item IN chain_checks WHERE item) AS all_chains_exist
CALL {
  WITH mappings, all_chains_exist
  UNWIND mappings AS mapping
  OPTIONAL MATCH (section:Section {id: mapping.section_id})
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
