"""Read-only Neo4j repository for the document explorer."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from neo4j import Driver


_GRAPH_RELATIONS = [
    "ISSUED_BY",
    "CONTAINS",
    "GUIDES",
    "REFERS_TO",
    "AMENDS",
    "REPEALS",
    "REPLACES",
    "DEFINES",
    "REGULATES",
    "REQUIRES",
]


class Neo4jDocumentBrowserRepo:
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def list_documents(
        self,
        *,
        page: int,
        page_size: int,
        doc_type: str | None,
        issuer: str | None,
        status: str | None,
        year: int | None,
    ) -> dict[str, Any]:
        parameters = {
            "doc_type": doc_type,
            "issuer": issuer.casefold() if issuer else None,
            "status": status,
            "year": year,
            "skip": (page - 1) * page_size,
            "limit": page_size,
        }
        predicate = """
        ($doc_type IS NULL OR document.doc_type = $doc_type)
        AND ($issuer IS NULL OR toLower(document.issuer_name) CONTAINS $issuer)
        AND ($status IS NULL OR document.legal_status = $status)
        AND ($year IS NULL OR document.issued_date.year = $year)
        """
        count_rows = self._run(
            f"""
            MATCH (document:Document)
            WHERE {predicate}
            RETURN count(document) AS total
            """,
            **parameters,
        )
        items = self._run(
            f"""
            MATCH (document:Document)
            WHERE {predicate}
            RETURN {_DOCUMENT_PROJECTION}
            ORDER BY document.issued_date DESC, document.number ASC, document.id ASC
            SKIP $skip LIMIT $limit
            """,
            **parameters,
        )
        return {
            "items": items,
            "total": int(count_rows[0]["total"]) if count_rows else 0,
        }

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        documents = self._run(
            f"""
            MATCH (document:Document {{id: $document_id}})
            RETURN {_DOCUMENT_PROJECTION}
            """,
            document_id=document_id,
        )
        if not documents:
            return None
        nodes = self._run(
            f"""
            MATCH (document:Document {{id: $document_id}})
            MATCH (document)-[:CONTAINS*1..4]->(node)
            RETURN {_BROWSER_NODE_PROJECTION}
            ORDER BY node.id
            """,
            document_id=document_id,
        )
        structural_edges = self._run(
            """
            MATCH (document:Document {id: $document_id})
            MATCH (document)-[:CONTAINS*0..4]->(source)-[:CONTAINS]->(target)
            WHERE (document)-[:CONTAINS*1..4]->(target)
            RETURN source.id AS source, target.id AS target
            ORDER BY source, target
            """,
            document_id=document_id,
        )
        return {
            "document": documents[0],
            "nodes": nodes,
            "structural_edges": structural_edges,
            "relations": self._document_relations(document_id),
        }

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        rows = self._run(
            f"""
            MATCH (document:Document)-[:CONTAINS*1..3]->(article:Article {{id: $article_id}})
            RETURN {_DOCUMENT_PROJECTION},
                   article.id AS article_id,
                   article.number AS article_number,
                   article.title AS article_title,
                   article.content_raw AS article_content_raw
            """,
            article_id=article_id,
        )
        if not rows:
            return None
        children = self._run(
            f"""
            MATCH (article:Article {{id: $article_id}})-[:CONTAINS*1..2]->(node)
            RETURN {_BROWSER_NODE_PROJECTION}
            ORDER BY node.id
            """,
            article_id=article_id,
        )
        return {"article": rows[0], "children": children}

    def get_graph(self, document_id: str, depth: int) -> dict[str, Any] | None:
        exists = self._run(
            "MATCH (document:Document {id: $document_id}) RETURN document.id AS id",
            document_id=document_id,
        )
        if not exists:
            return None
        path_clause = {
            1: "OPTIONAL MATCH path = (base)-[*0..1]-(node)",
            2: "OPTIONAL MATCH path = (base)-[*0..2]-(node)",
        }[depth]
        nodes = self._run(
            f"""
            MATCH (document:Document {{id: $document_id}})
            MATCH (document)-[:CONTAINS*0..4]->(base)
            {path_clause}
            WHERE all(relation IN relationships(path)
                      WHERE type(relation) IN $relations)
              AND node.id IS NOT NULL
            RETURN DISTINCT {_BROWSER_NODE_PROJECTION}
            """,
            document_id=document_id,
            relations=_GRAPH_RELATIONS,
        )
        return {"nodes": nodes}

    def graph_edges(self, node_ids: list[str]) -> list[dict[str, Any]]:
        return self._run(
            """
            MATCH (source)-[relation]->(target)
            WHERE source.id IN $node_ids AND target.id IN $node_ids
              AND type(relation) IN $relations
            RETURN source.id AS source,
                   target.id AS target,
                   type(relation) AS relation_type
            ORDER BY relation_type, source, target
            """,
            node_ids=node_ids,
            relations=_GRAPH_RELATIONS,
        )

    def close(self) -> None:
        self._driver.close()

    def _document_relations(self, document_id: str) -> list[dict[str, Any]]:
        return self._run(
            """
            MATCH (document:Document {id: $document_id})
            MATCH (document)-[:CONTAINS*0..4]->(source)-[relation]->(target)
            MATCH (other:Document)-[:CONTAINS*0..4]->(target)
            WHERE other.id <> document.id
              AND type(relation) IN $relations
            RETURN other.id AS doc_id,
                   other.number AS doc_number,
                   type(relation) AS relation_type,
                   collect(DISTINCT source.id) AS affected_units
            ORDER BY relation_type, doc_number, doc_id
            """,
            document_id=document_id,
            relations=_GRAPH_RELATIONS,
        )

    def _run(self, query: str, **parameters: object) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            return [
                {key: _native(value) for key, value in dict(record).items()}
                for record in session.run(query, **parameters)
            ]


_DOCUMENT_PROJECTION = """
document.id AS id,
document.number AS number,
document.title AS title,
document.doc_type AS doc_type,
document.issuer_name AS issuer_name,
document.issued_date AS issued_date,
document.effective_from AS effective_from,
document.legal_status AS status
"""

_BROWSER_NODE_PROJECTION = """
node.id AS id,
CASE
  WHEN node:Document THEN 'Document'
  WHEN node:Chapter THEN 'Chapter'
  WHEN node:Article THEN 'Article'
  WHEN node:Clause THEN 'Clause'
  WHEN node:Point THEN 'Point'
  WHEN node:LegalConcept THEN 'LegalConcept'
  WHEN node:LegalSubject THEN 'LegalSubject'
  WHEN node:LegalAction THEN 'LegalAction'
  WHEN node:Issuer THEN 'Issuer'
  ELSE head(labels(node))
END AS label,
node.number AS number,
node.title AS title,
node.content_raw AS content_raw,
node.label AS point_label,
node.name AS name
"""


def _native(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        return to_native()
    if isinstance(value, list):
        return [_native(item) for item in value]
    if isinstance(value, dict):
        return {key: _native(item) for key, item in value.items()}
    return value
