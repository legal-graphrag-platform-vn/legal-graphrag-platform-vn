"""Neo4j read repository for corpus-independent legal retrieval."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from neo4j import Driver

from src.shared.ontology.contract import PHASE1_PERSISTED_LABELS, PHASE1_RELATION_ENUM
from src.shared.retrieval_contract import RetrievalFilters
from src.shared.ontology.hierarchy import MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH


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
        index_names: list[str],
        query_embedding: list[float],
        *,
        filters: RetrievalFilters,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        if not index_names:
            return []

        union_blocks = []
        for idx in index_names:
            # Neo4j vector index names are internal constants, safe to interpolate
            union_blocks.append(
                f"CALL db.index.vector.queryNodes('{idx}', $candidate_k, $query_embedding) "
                "YIELD node, score RETURN node, score"
            )

        union_clause = "\n        UNION ALL\n        ".join(union_blocks)

        query = f"""
        CALL {{
            {union_clause}
        }}
        WITH node, score
        {_LEGAL_UNIT_CONTEXT}
        WHERE {_FILTER_PREDICATE}
        RETURN {_UNIT_PROJECTION}, score
        ORDER BY score DESC, id ASC
        LIMIT $k
        """
        return self._run(
            query,
            index_names=index_names,
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

    def fetch_canonical_anchors(
        self,
        anchor_ids: list[str],
        *,
        filters: RetrievalFilters,
    ) -> list[dict[str, Any]]:
        """Hydrate server-resolved structural anchors under active filters."""
        query = f"""
        UNWIND $anchor_ids AS anchor_id
        MATCH (anchor {{id: anchor_id}})
        WHERE anchor:Document OR anchor:Appendix OR anchor:Article OR anchor:Clause OR anchor:Point
        OPTIONAL MATCH (parent_clause:Clause)-[:CONTAINS]->(anchor)
        WITH anchor_id, anchor,
             CASE WHEN anchor:Point THEN parent_clause
                  WHEN anchor:Document OR anchor:Appendix OR anchor:Article OR anchor:Clause THEN anchor
                  ELSE null END AS node
        OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(node)
        OPTIONAL MATCH (owner:Document)-[:CONTAINS*1..{MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH}]->(node)
        WITH anchor_id, anchor, node, parent_article,
             CASE WHEN anchor:Document THEN anchor ELSE owner END AS document,
             CASE WHEN anchor:Document THEN anchor ELSE node END AS temporal_node
        WHERE ($document_ids = [] OR document.id IN $document_ids)
          AND ($doc_types = [] OR document.doc_type IN $doc_types)
          AND ($legal_statuses = [] OR document.legal_status IN $legal_statuses)
          AND ($query_date IS NULL OR (
            temporal_node.effective_from IS NOT NULL
            AND temporal_node.effective_from <= $query_date
            AND (temporal_node.effective_to IS NULL
                 OR temporal_node.effective_to > $query_date)
          ))
        RETURN anchor_id, {_UNIT_PROJECTION}
        ORDER BY anchor_id
        """
        return self._run(
            query,
            anchor_ids=anchor_ids,
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
        CALL (path) {{
          UNWIND nodes(path) AS path_node
          OPTIONAL MATCH (path_parent_clause:Clause)-[:CONTAINS]->(path_node)
          RETURN collect({{
            node_id: path_node.id,
            labels: labels(path_node),
            effective_from: path_node.effective_from,
            effective_to: path_node.effective_to,
            legal_status: path_node.legal_status,
            citable_unit_id: CASE
              WHEN path_node:Appendix OR path_node:Article OR path_node:Clause THEN path_node.id
              WHEN path_node:Point THEN path_parent_clause.id
              ELSE null
            END
          }}) AS path_node_refs
        }}
        OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(unit)
        OPTIONAL MATCH (document:Document)-[:CONTAINS*1..{MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH}]->(unit)
        WITH path, path_node_refs, unit, parent_article, document
        WHERE NOT (unit:Appendix OR unit:Article OR unit:Clause) OR ({_GRAPH_UNIT_FILTER})
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
          CASE WHEN unit:Appendix OR unit:Article OR unit:Clause THEN unit.id ELSE null END AS id,
          CASE WHEN unit:Appendix THEN 'Appendix'
               WHEN unit:Article THEN 'Article'
               WHEN unit:Clause THEN 'Clause' ELSE null END AS label,
          unit.content_raw AS content_raw,
          unit.title AS title,
          CASE WHEN unit:Article THEN unit.id ELSE parent_article.id END AS article_id,
          CASE WHEN unit:Clause THEN unit.id ELSE null END AS clause_id,
          CASE WHEN unit:Article THEN unit.number ELSE parent_article.number END AS article_number,
          CASE WHEN unit:Clause THEN unit.number ELSE null END AS clause_number,
          CASE WHEN unit:Appendix THEN unit.number ELSE null END AS appendix_number,
          document.id AS document_id,
          document.number AS document_number,
          document.title AS document_title,
          null AS source_url,
          unit.effective_from AS effective_from,
          unit.effective_to AS effective_to,
          unit.legal_status AS legal_status,
          properties(unit)['version_family_id'] AS version_family_id
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

    def lookup_structural_endpoints(
        self,
        *,
        label: str,
        document_number: str | None,
        article_number: str | None,
        clause_number: str | None,
        point_label: str | None,
        filters: RetrievalFilters,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if label not in {"Document", "Article", "Clause", "Point"}:
            raise ValueError(f"Unsupported structural endpoint label: {label}")
        if not 1 <= limit <= 100:
            raise ValueError(
                "Structural endpoint lookup limit must be between 1 and 100"
            )
        query = """
        MATCH (document:Document)
        WHERE document.id IN $document_ids
          AND ($doc_types = [] OR document.doc_type IN $doc_types)
        MATCH (document)-[:CONTAINS*0..4]->(node)
        WHERE $label IN labels(node)
        OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(node)
        OPTIONAL MATCH (parent_clause:Clause)-[:CONTAINS]->(node)
        OPTIONAL MATCH (point_article:Article)-[:CONTAINS]->(parent_clause)
        WITH document, node, parent_clause,
             CASE WHEN node:Article THEN node.number
                  WHEN node:Clause THEN parent_article.number
                  WHEN node:Point THEN point_article.number
                  ELSE null END AS resolved_article_number,
             CASE WHEN node:Clause THEN node.number
                  WHEN node:Point THEN parent_clause.number
                  ELSE null END AS resolved_clause_number,
             CASE WHEN node:Point THEN node.label ELSE null END AS resolved_point_label,
             CASE WHEN node:Point THEN parent_clause ELSE node END AS temporal_node
        WHERE ($document_number IS NULL OR document.number = $document_number)
          AND ($article_number IS NULL OR resolved_article_number = $article_number)
          AND ($clause_number IS NULL OR resolved_clause_number = $clause_number)
          AND ($point_label IS NULL OR resolved_point_label = $point_label)
          AND ($legal_statuses = [] OR temporal_node.legal_status IN $legal_statuses)
          AND ($query_date IS NULL OR (
            temporal_node.effective_from IS NOT NULL
            AND temporal_node.effective_from <= $query_date
            AND (temporal_node.effective_to IS NULL
                 OR temporal_node.effective_to > $query_date)
          ))
        RETURN DISTINCT node.id AS node_id,
                        $label AS label,
                        document.id AS document_id
        ORDER BY node_id
        LIMIT $limit
        """
        return self._run(
            query,
            label=label,
            document_number=document_number,
            article_number=article_number,
            clause_number=clause_number,
            point_label=point_label,
            limit=limit,
            **_filter_parameters(filters),
        )

    def lookup_exact_paths(
        self,
        *,
        anchor_id: str,
        target_id: str,
        steps: Sequence[Mapping[str, str]],
        filters: RetrievalFilters,
        limit: int,
    ) -> list[dict[str, Any]]:
        depth = len(steps)
        try:
            query = _EXACT_PATH_QUERIES[depth]
        except KeyError as exc:
            raise ValueError("Exact path depth must be 2 or 3") from exc
        if not 1 <= limit <= 101:
            raise ValueError("Exact path lookup limit must be between 1 and 101")

        parameters: dict[str, object] = {
            "anchor_id": _required_lookup_text(anchor_id, "anchor ID"),
            "target_id": _required_lookup_text(target_id, "target ID"),
            "limit": limit,
            **_filter_parameters(filters),
        }
        for index, step in enumerate(steps, start=1):
            relation = step.get("relation")
            direction = step.get("direction")
            next_label = step.get("next_label")
            if relation not in PHASE1_RELATION_ENUM:
                raise ValueError(f"Unsupported exact path relation at step {index}")
            if direction not in {"outgoing", "incoming"}:
                raise ValueError(f"Unsupported exact path direction at step {index}")
            if next_label not in PHASE1_PERSISTED_LABELS:
                raise ValueError(f"Unsupported exact path label at step {index}")
            parameters[f"relation_{index}"] = relation
            parameters[f"direction_{index}"] = direction
            parameters[f"next_label_{index}"] = next_label
        return self._run(query, **parameters)

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
        // Optimized capability check
        CALL db.relationshipTypes() YIELD relationshipType
        WITH collect(relationshipType) AS relation_types
        RETURN relation_types,
               true AS scoped_temporal_metadata_available
        """
        rows = self._run(query, **_filter_parameters(filters))
        row = rows[0] if rows else {}
        relation_types = frozenset(
            str(value) for value in row.get("relation_types", []) if value
        )
        multiple_versions = self._multiple_versions_available(filters)
        return {
            "vector_appendix_index_available": _index_online(
                indexes, "appendix_embedding"
            ),
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
        // Optimized check
        MATCH ()-[relation:AMENDS|REPLACES]->()
        RETURN count(relation) > 0 AS available
        LIMIT 1
        """
        rows = self._run(query, **_filter_parameters(filters))
        return bool(rows and rows[0].get("available"))

    def _run(self, query: str, **parameters: object) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(query, **parameters)
            return [dict(record) for record in result]


_LEGAL_UNIT_CONTEXT = f"""
OPTIONAL MATCH (parent_article:Article)-[:CONTAINS]->(node)
MATCH (document:Document)-[:CONTAINS*1..{MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH}]->(node)
"""

_FILTER_PREDICATE = """
($document_ids = [] OR document.id IN $document_ids)
AND ($doc_types = [] OR document.doc_type IN $doc_types)
AND ($legal_statuses = [] OR document.legal_status IN $legal_statuses)
AND ($query_date IS NULL OR (
  coalesce(node.effective_from, document.effective_from) IS NOT NULL
  AND coalesce(node.effective_from, document.effective_from) <= $query_date
  AND (coalesce(node.effective_to, document.effective_to) IS NULL OR coalesce(node.effective_to, document.effective_to) > $query_date)
))
"""

_GRAPH_UNIT_FILTER = _FILTER_PREDICATE.replace("node.", "unit.")

_UNIT_PROJECTION = """
node.id AS id,
CASE WHEN node:Document THEN 'Document'
     WHEN node:Appendix THEN 'Appendix'
     WHEN node:Article THEN 'Article' ELSE 'Clause' END AS label,
CASE WHEN node:Document THEN coalesce(node.title, node.number)
     ELSE node.content_raw END AS content_raw,
node.title AS title,
CASE WHEN node:Article THEN node.id ELSE parent_article.id END AS article_id,
CASE WHEN node:Clause THEN node.id ELSE null END AS clause_id,
CASE WHEN node:Article THEN node.number ELSE parent_article.number END AS article_number,
CASE WHEN node:Clause THEN node.number ELSE null END AS clause_number,
CASE WHEN node:Appendix THEN node.number ELSE null END AS appendix_number,
document.id AS document_id,
document.number AS document_number,
document.title AS document_title,
document.source_url AS source_url,
coalesce(node.effective_from, document.effective_from) AS effective_from,
coalesce(node.effective_to, document.effective_to) AS effective_to,
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


def _required_lookup_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Exact path {field_name} must not be blank")
    return normalized


def _exact_path_query(depth: int) -> str:
    node_names = [f"node_{index}" for index in range(depth + 1)]
    edge_names = [f"edge_{index}" for index in range(1, depth + 1)]
    pattern = f"({node_names[0]})" + "".join(
        f"-[{edge_names[index - 1]}]-({node_names[index]})"
        for index in range(1, depth + 1)
    )
    constraints = []
    for index in range(1, depth + 1):
        previous = node_names[index - 1]
        current = node_names[index]
        edge = edge_names[index - 1]
        constraints.append(
            f"""type({edge}) = $relation_{index}
          AND $next_label_{index} IN labels({current})
          AND ((
            $direction_{index} = 'outgoing'
            AND startNode({edge}) = {previous}
            AND endNode({edge}) = {current}
          ) OR (
            $direction_{index} = 'incoming'
            AND startNode({edge}) = {current}
            AND endNode({edge}) = {previous}
          ))"""
        )
    constraint_text = "\n          AND ".join(constraints)
    return f"""
        MATCH path = {pattern}
        WHERE {node_names[0]}.id = $anchor_id
          AND {node_names[-1]}.id = $target_id
          AND {constraint_text}
          AND all(path_node IN nodes(path) WHERE
            single(other IN nodes(path) WHERE other = path_node))
        CALL (path) {{
          UNWIND nodes(path) AS path_node
          OPTIONAL MATCH (path_parent_clause:Clause)-[:CONTAINS]->(path_node)
          RETURN collect({{
            node_id: path_node.id,
            labels: labels(path_node),
            effective_from: path_node.effective_from,
            effective_to: path_node.effective_to,
            legal_status: path_node.legal_status,
            citable_unit_id: CASE
              WHEN path_node:Appendix OR path_node:Article OR path_node:Clause THEN path_node.id
              WHEN path_node:Point THEN path_parent_clause.id
              ELSE null
            END
          }}) AS path_node_refs
        }}
        RETURN path_node_refs,
          [rel IN relationships(path) | {{
            relation_id: coalesce(rel.relation_id, elementId(rel)),
            relation_type: type(rel),
            source_id: startNode(rel).id,
            target_id: endNode(rel).id,
            effective_from: rel.effective_from,
            effective_to: rel.effective_to,
            citation_text: rel.citation_text,
            citation_type: rel.citation_type,
            extraction_method: rel.extraction_method
          }}] AS path_edge_refs
        ORDER BY length(path),
                 [rel IN relationships(path) | type(rel)],
                 [path_node IN nodes(path) | path_node.id],
                 [rel IN relationships(path) | startNode(rel).id],
                 [rel IN relationships(path) | endNode(rel).id]
        LIMIT $limit
        """


_EXACT_PATH_QUERIES = {depth: _exact_path_query(depth) for depth in (2, 3)}
