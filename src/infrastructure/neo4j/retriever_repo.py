"""Neo4j read repository for corpus-independent legal retrieval."""

from __future__ import annotations

from datetime import date
from typing import Any

from neo4j import Driver

from src.shared.retrieval_contract import RetrievalFilters


_OUTGOING_PATH_QUERIES = {
    1: "MATCH path = (entry)-[*1..1]->(related)",
    2: "MATCH path = (entry)-[*1..2]->(related)",
    3: "MATCH path = (entry)-[*1..3]->(related)",
    5: "MATCH path = (entry)-[*1..5]->(related)",
}
_INCOMING_PATH_QUERIES = {
    1: "MATCH path = (entry)<-[*1..1]-(related)",
    2: "MATCH path = (entry)<-[*1..2]-(related)",
    3: "MATCH path = (entry)<-[*1..3]-(related)",
    5: "MATCH path = (entry)<-[*1..5]-(related)",
}
_BOTH_PATH_QUERIES = {
    1: "MATCH path = (entry)-[*1..1]-(related)",
    2: "MATCH path = (entry)-[*1..2]-(related)",
    3: "MATCH path = (entry)-[*1..3]-(related)",
    5: "MATCH path = (entry)-[*1..5]-(related)",
}


class Neo4jRetrieverRepo:
    def __init__(self, driver: Driver):
        self._driver = driver

    def vector_search(
        self,
        index_name: str,
        query_embedding: list[float],
        *,
        filters: RetrievalFilters,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        query = f"""
        CALL db.index.vector.queryNodes($index_name, $candidate_k, $query_embedding)
        YIELD node, score
        {_LEGAL_UNIT_CONTEXT}
        WHERE {_FILTER_PREDICATE}
        RETURN {_UNIT_PROJECTION}, score
        ORDER BY score DESC, id ASC
        LIMIT $k
        """
        return self._run(
            query,
            index_name=index_name,
            query_embedding=query_embedding,
            candidate_k=max(k * 4, k),
            k=k,
            **_filter_parameters(filters),
        )

    def fulltext_search(
        self,
        index_name: str,
        text_query: str,
        *,
        filters: RetrievalFilters,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        query = f"""
        CALL db.index.fulltext.queryNodes($index_name, $text_query, {{limit: $candidate_k}})
        YIELD node, score
        {_LEGAL_UNIT_CONTEXT}
        WHERE {_FILTER_PREDICATE}
        RETURN {_UNIT_PROJECTION}, score
        ORDER BY score DESC, id ASC
        LIMIT $k
        """
        return self._run(
            query,
            index_name=index_name,
            text_query=text_query,
            candidate_k=max(k * 4, k),
            k=k,
            **_filter_parameters(filters),
        )

    def graph_expansion(
        self,
        entry_ids: list[str],
        relations: tuple[str, ...],
        direction: str,
        max_depth: int,
        *,
        filters: RetrievalFilters,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        path_clause = _path_clause(direction=direction, max_depth=max_depth)
        query = f"""
        MATCH (entry)
        WHERE entry.id IN $entry_ids
        {path_clause}
        WHERE all(rel IN relationships(path) WHERE type(rel) IN $relations)
        OPTIONAL MATCH (parent_clause:Clause)-[:CONTAINS]->(related)
        WITH path, related,
             CASE WHEN related:Point THEN parent_clause ELSE related END AS unit
        CALL {{
          WITH path
          UNWIND nodes(path) AS path_node
          OPTIONAL MATCH (path_parent_clause:Clause)-[:CONTAINS]->(path_node)
          RETURN collect({{
            node_id: path_node.id,
            labels: labels(path_node),
            effective_from: path_node.effective_from,
            effective_to: path_node.effective_to,
            legal_status: path_node.legal_status,
            citable_unit_id: CASE
              WHEN path_node:Article OR path_node:Clause THEN path_node.id
              WHEN path_node:Point THEN path_parent_clause.id
              ELSE null
            END
          }}) AS path_node_refs
        }}
        OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(unit)
        OPTIONAL MATCH (document:Document)-[:CONTAINS*1..3]->(unit)
        WITH path, path_node_refs, unit, parent_article, document
        WHERE NOT (unit:Article OR unit:Clause) OR ({_GRAPH_UNIT_FILTER})
        RETURN
          path_node_refs,
          [rel IN relationships(path) | {{
            relation_id: rel.relation_id,
            relation_type: type(rel),
            source_id: startNode(rel).id,
            target_id: endNode(rel).id,
            effective_from: rel.effective_from,
            effective_to: rel.effective_to,
            citation_text: rel.citation_text,
            citation_type: rel.citation_type,
            extraction_method: rel.extraction_method
          }}] AS path_edge_refs,
          CASE WHEN unit:Article OR unit:Clause THEN unit.id ELSE null END AS id,
          CASE WHEN unit:Article THEN 'Article'
               WHEN unit:Clause THEN 'Clause' ELSE null END AS label,
          unit.content_raw AS content_raw,
          unit.title AS title,
          CASE WHEN unit:Article THEN unit.id ELSE parent_article.id END AS article_id,
          CASE WHEN unit:Clause THEN unit.id ELSE null END AS clause_id,
          CASE WHEN unit:Article THEN unit.number ELSE parent_article.number END AS article_number,
          CASE WHEN unit:Clause THEN unit.number ELSE null END AS clause_number,
          document.id AS document_id,
          document.number AS document_number,
          document.title AS document_title,
          null AS source_url,
          unit.effective_from AS effective_from,
          unit.effective_to AS effective_to,
          unit.legal_status AS legal_status,
          unit.version_family_id AS version_family_id
        ORDER BY length(path) ASC,
                 [node IN path_node_refs | node.node_id] ASC
        LIMIT $limit
        """
        return self._run(
            query,
            entry_ids=entry_ids,
            relations=list(relations),
            limit=limit,
            **_filter_parameters(filters),
        )

    def inspect_dependencies(self) -> dict[str, object]:
        query = """
        SHOW INDEXES
        YIELD name, type, state, options
        WHERE type <> 'LOOKUP'
        RETURN name, type, state, options
        ORDER BY name
        """
        rows = self._run(query)
        return {
            "indexes": {
                str(row["name"]): {
                    "type": str(row["type"]),
                    "state": str(row["state"]),
                    "options": dict(row.get("options") or {}),
                }
                for row in rows
            }
        }

    def inspect_temporal_units(self, unit_ids: list[str]) -> list[dict[str, Any]]:
        query = """
        MATCH (node)
        WHERE node.id IN $unit_ids
        RETURN node.id AS id, labels(node) AS labels,
               node.effective_from AS effective_from,
               node.effective_to AS effective_to,
               node.legal_status AS legal_status,
               properties(node) AS properties
        ORDER BY id
        """
        return self._run(query, unit_ids=unit_ids)

    def inspect_runtime_identity(self) -> dict[str, object]:
        component_rows = self._run(
            """
            CALL dbms.components()
            YIELD name, versions, edition
            RETURN name, versions, edition
            ORDER BY name
            """
        )
        database_rows = self._run(
            """
            CALL db.info()
            YIELD name
            RETURN name
            """
        )
        return {
            "database_name": database_rows[0]["name"] if database_rows else None,
            "components": component_rows,
        }

    def inspect_capabilities(self, filters: RetrievalFilters) -> dict[str, object]:
        dependencies = self.inspect_dependencies()
        indexes = dependencies["indexes"]
        query = """
        MATCH (document:Document)
        WHERE ($document_ids = [] OR document.id IN $document_ids)
          AND ($doc_types = [] OR document.doc_type IN $doc_types)
          AND ($legal_statuses = [] OR document.legal_status IN $legal_statuses)
        OPTIONAL MATCH (document)-[:CONTAINS*0..3]->(unit)
        WITH collect(DISTINCT document) + collect(DISTINCT unit) AS scoped_nodes
        WITH scoped_nodes,
             [node IN scoped_nodes
              WHERE node IS NOT NULL
                AND (node:Document OR node:Article OR node:Clause)] AS temporal_nodes
        UNWIND scoped_nodes AS scoped
        OPTIONAL MATCH (scoped)-[relation]-(other)
        RETURN collect(DISTINCT type(relation)) AS relation_types,
               size(temporal_nodes) > 0
               AND all(node IN temporal_nodes
                       WHERE node.effective_from IS NOT NULL)
                   AS scoped_temporal_metadata_available
        """
        rows = self._run(query, **_filter_parameters(filters))
        row = rows[0] if rows else {}
        relation_types = frozenset(
            str(value) for value in row.get("relation_types", []) if value
        )
        multiple_versions = self._multiple_versions_available(filters)
        return {
            "vector_article_index_available": _index_online(
                indexes, "article_embedding"
            ),
            "vector_clause_index_available": _index_online(indexes, "clause_embedding"),
            "fulltext_index_available": _index_online(
                indexes, "legal_article_clause_fulltext"
            ),
            "scoped_temporal_metadata_available": bool(
                row.get("scoped_temporal_metadata_available")
            ),
            "corpus_complete_current_validity_available": False,
            "temporal_relations_available": bool(
                relation_types & {"AMENDS", "REPEALS", "REPLACES"}
            ),
            "guides_relations_available": "GUIDES" in relation_types,
            "structural_hierarchy_available": "CONTAINS" in relation_types,
            "multiple_versions_available": multiple_versions,
            "definition_relations_available": "DEFINES" in relation_types,
            "semantic_multi_hop_graph_available": "REFERS_TO" in relation_types,
            "canonical_relation_types_available": relation_types,
        }

    def _multiple_versions_available(self, filters: RetrievalFilters) -> bool:
        query = """
        MATCH (document:Document)
        WHERE ($document_ids = [] OR document.id IN $document_ids)
          AND ($doc_types = [] OR document.doc_type IN $doc_types)
          AND ($legal_statuses = [] OR document.legal_status IN $legal_statuses)
        OPTIONAL MATCH (document)-[:CONTAINS*0..3]->(scoped)
        WITH collect(DISTINCT document) + collect(DISTINCT scoped) AS scoped_nodes
        UNWIND scoped_nodes AS source
        OPTIONAL MATCH (source)-[relation:AMENDS|REPLACES]-(target)
        RETURN count(relation) > 0 AS available
        """
        rows = self._run(query, **_filter_parameters(filters))
        return bool(rows and rows[0].get("available"))

    def _run(self, query: str, **parameters: object) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(query, **parameters)
            return [dict(record) for record in result]


_LEGAL_UNIT_CONTEXT = """
OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(node)
MATCH (document:Document)-[:CONTAINS*1..3]->(node)
"""

_FILTER_PREDICATE = """
($document_ids = [] OR document.id IN $document_ids)
AND ($doc_types = [] OR document.doc_type IN $doc_types)
AND ($legal_statuses = [] OR document.legal_status IN $legal_statuses)
AND ($query_date IS NULL OR (
  node.effective_from IS NOT NULL
  AND node.effective_from <= $query_date
  AND (node.effective_to IS NULL OR node.effective_to > $query_date)
))
"""

_GRAPH_UNIT_FILTER = _FILTER_PREDICATE.replace("node.", "unit.")

_UNIT_PROJECTION = """
node.id AS id,
CASE WHEN node:Article THEN 'Article' ELSE 'Clause' END AS label,
node.content_raw AS content_raw,
node.title AS title,
CASE WHEN node:Article THEN node.id ELSE parent_article.id END AS article_id,
CASE WHEN node:Clause THEN node.id ELSE null END AS clause_id,
CASE WHEN node:Article THEN node.number ELSE parent_article.number END AS article_number,
CASE WHEN node:Clause THEN node.number ELSE null END AS clause_number,
document.id AS document_id,
document.number AS document_number,
document.title AS document_title,
null AS source_url,
node.effective_from AS effective_from,
node.effective_to AS effective_to,
document.legal_status AS legal_status,
null AS version_family_id
"""


def _path_clause(*, direction: str, max_depth: int) -> str:
    queries = {
        "outgoing": _OUTGOING_PATH_QUERIES,
        "incoming": _INCOMING_PATH_QUERIES,
        "both": _BOTH_PATH_QUERIES,
    }.get(direction)
    if queries is None:
        raise ValueError(f"Unsupported traversal direction: {direction}")
    try:
        return queries[max_depth]
    except KeyError as exc:
        raise ValueError(f"Unsupported traversal depth: {max_depth}") from exc


def _filter_parameters(filters: RetrievalFilters) -> dict[str, list[str] | date | None]:
    return {
        "document_ids": filters.document_ids,
        "doc_types": filters.doc_types,
        "legal_statuses": filters.legal_statuses,
        "query_date": filters.query_date,
    }


def _index_online(indexes: object, name: str) -> bool:
    if not isinstance(indexes, dict):
        return False
    value = indexes.get(name)
    return isinstance(value, dict) and value.get("state") == "ONLINE"
