"""Generate graph-quality reports from Neo4j and validated decision artifacts."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.shared.ontology.payload_consistency_validator import validate_payload_consistency
from src.shared.ontology.validators import validate_relation


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


@dataclass(slots=True)
class GraphQualityReporter:
    session: SessionProtocol

    def generate_for_document(self, graph_id: str) -> dict:
        node_ids = self._written_node_ids(graph_id)
        label_counts = self._label_counts(node_ids)
        article_stats = self._embedding_stats(node_ids, "Article")
        clause_stats = self._embedding_stats(node_ids, "Clause")
        duplicate_node_id_count = self._duplicate_node_id_count(node_ids)
        dangling_endpoint_count = self._dangling_endpoint_count(node_ids)
        edges = self._written_edges(node_ids)
        relation_counts = Counter(str(edge["relation_type"]) for edge in edges)
        duplicate_relation_identity_count = _duplicate_relation_identity_count(edges)
        orphan_node_count = _orphan_node_count(node_ids, edges)
        connected_component_count = _count_components(
            node_ids,
            [[str(edge["source"]), str(edge["target"])] for edge in edges],
        )
        ontology_report = self._ontology_violation_report(edges)
        node_count = len(node_ids)
        edge_count = len(edges)

        return {
            "document_count": label_counts.get("Document", 0),
            "issuer_count": label_counts.get("Issuer", 0),
            "article_count": article_stats["total"],
            "clause_count": clause_stats["total"],
            "legal_concept_count": label_counts.get("LegalConcept", 0),
            "legal_subject_count": label_counts.get("LegalSubject", 0),
            "legal_action_count": label_counts.get("LegalAction", 0),
            "semantic_node_count": sum(label_counts.get(label, 0) for label in ("LegalConcept", "LegalSubject", "LegalAction")),
            "relation_count_by_type": dict(relation_counts),
            "ontology_violation_count": ontology_report["count"],
            "ontology_violation_rate": ontology_report["rate"],
            "ontology_violations": ontology_report["violations"],
            "duplicate_node_id_count": duplicate_node_id_count,
            "duplicate_relation_identity_count": duplicate_relation_identity_count,
            "dangling_endpoint_count": dangling_endpoint_count,
            "orphan_node_count": orphan_node_count,
            "article_semantic_coverage": _article_semantic_coverage(edges, article_stats["total"]),
            "graph_density": _directed_density(node_count, edge_count),
            "average_degree": _average_degree(node_count, edge_count),
            "topology_convention": {
                "graph_density": "directed E/(N*(N-1)) without self-loops",
                "average_degree": "undirected projection 2E/N",
            },
            "embedding_coverage": {
                "Article": article_stats["coverage"],
                "Clause": clause_stats["coverage"],
            },
            "connected_component_count": connected_component_count,
            "source": "neo4j",
        }

    def _written_node_ids(self, graph_id: str) -> set[str]:
        row = _single_row(
            self.session.run(
                (
                    "MATCH (d:Document {id: $graph_id}) "
                    "OPTIONAL MATCH (d)-[:CONTAINS*0..4]->(s) "
                    "WITH collect(DISTINCT d) + collect(DISTINCT s) AS structural_nodes "
                    "WITH [n IN structural_nodes WHERE n IS NOT NULL AND n.id IS NOT NULL] AS structural_nodes "
                    "WITH structural_nodes, [n IN structural_nodes | n.id] AS structural_ids "
                    "UNWIND structural_nodes AS sn "
                    "OPTIONAL MATCH (sn)-[:ISSUED_BY|DEFINES|REGULATES|REFERS_TO|AMENDS|REPEALS|REPLACES|GUIDES]-(x) "
                    "WITH structural_nodes, structural_ids, collect(DISTINCT x) AS one_hop_nodes "
                    "OPTIONAL MATCH (a)-[r:REQUIRES]->(b) "
                    "WHERE r.source_article IN structural_ids "
                    "WITH structural_nodes, one_hop_nodes, collect(DISTINCT a) AS a_nodes, collect(DISTINCT b) AS b_nodes "
                    "WITH structural_nodes + one_hop_nodes + a_nodes + b_nodes AS all_nodes "
                    "UNWIND all_nodes AS n "
                    "WITH DISTINCT n WHERE n IS NOT NULL AND n.id IS NOT NULL "
                    "RETURN collect(n.id) AS node_ids"
                ),
                graph_id=graph_id,
            )
        )
        return {str(node_id) for node_id in (_row_value(row, "node_ids") or [])}

    def _label_counts(self, node_ids: set[str]) -> dict[str, int]:
        rows = list(
            self.session.run(
                "MATCH (n) WHERE n.id IN $node_ids RETURN labels(n) AS labels, count(n) AS count",
                node_ids=list(node_ids),
            )
        )
        counts: Counter[str] = Counter()
        for row in rows:
            count = int(_row_value(row, "count") or 0)
            for label in _row_value(row, "labels") or []:
                counts[str(label)] += count
        return dict(counts)

    def _embedding_stats(self, node_ids: set[str], label: str) -> dict[str, float | int]:
        row = _single_row(
            self.session.run(
                f"MATCH (n:{label}) WHERE n.id IN $node_ids RETURN count(n) AS total, count(n.embedding) AS embedded",
                node_ids=list(node_ids),
            )
        )
        total = int(_row_value(row, "total") or 0)
        embedded = int(_row_value(row, "embedded") or 0)
        return {
            "total": total,
            "embedded": embedded,
            "coverage": _coverage(embedded, total),
        }

    def _duplicate_node_id_count(self, node_ids: set[str]) -> int:
        row = _single_row(
            self.session.run(
                (
                    "MATCH (n) "
                    "WHERE n.id IN $node_ids "
                    "WITH n.id AS id, count(n) AS c "
                    "WHERE c > 1 "
                    "RETURN count(*) AS count"
                ),
                node_ids=list(node_ids),
            )
        )
        return int(_row_value(row, "count") or 0)

    def _dangling_endpoint_count(self, node_ids: set[str]) -> int:
        row = _single_row(
            self.session.run(
                (
                    "MATCH (a)-[r]-(b) "
                    "WHERE a.id IN $node_ids AND (b.id IS NULL OR b.id = '') "
                    "RETURN count(DISTINCT r) AS count"
                ),
                node_ids=list(node_ids),
            )
        )
        return int(_row_value(row, "count") or 0)

    def _written_edges(self, node_ids: set[str]) -> list[dict[str, Any]]:
        rows = list(
            self.session.run(
                (
                    "MATCH (a)-[r]->(b) "
                    "WHERE a.id IN $node_ids AND b.id IN $node_ids "
                    "RETURN a.id AS source, labels(a) AS source_labels, a.doc_type AS source_doc_type, "
                    "type(r) AS relation_type, properties(r) AS properties, r.relation_id AS relation_id, "
                    "b.id AS target, labels(b) AS target_labels, b.doc_type AS target_doc_type"
                ),
                node_ids=list(node_ids),
            )
        )
        return [
            {
                "source": _row_value(row, "source"),
                "source_labels": _row_value(row, "source_labels") or [],
                "source_doc_type": _row_value(row, "source_doc_type"),
                "relation_type": _row_value(row, "relation_type"),
                "properties": _row_value(row, "properties") or {},
                "relation_id": _row_value(row, "relation_id"),
                "target": _row_value(row, "target"),
                "target_labels": _row_value(row, "target_labels") or [],
                "target_doc_type": _row_value(row, "target_doc_type"),
            }
            for row in rows
        ]

    def _ontology_violation_report(self, edges: list[dict[str, Any]]) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        for edge in edges:
            head_label = _canonical_label(edge["source_labels"])
            tail_label = _canonical_label(edge["target_labels"])
            relation_type = str(edge["relation_type"] or "")
            ok, error = validate_relation(
                head_label,
                relation_type,
                tail_label,
                head_id=edge["source"],
                tail_id=edge["target"],
                properties=edge["properties"],
                head_doc_type=edge["source_doc_type"],
                tail_doc_type=edge["target_doc_type"],
            )
            if not ok:
                violations.append(
                    {
                        "head_id": edge["source"],
                        "relation_type": relation_type,
                        "tail_id": edge["target"],
                        "error": error,
                    }
                )

        total = len(edges)
        return {
            "count": len(violations),
            "rate": 0.0 if total == 0 else len(violations) / total,
            "violations": violations[:50],
        }


def build_graph_quality_report(payload: dict) -> dict:
    consistency = validate_payload_consistency(payload)
    node_counts = Counter(node.get("type") for node in payload.get("nodes", []))
    relation_counts = Counter(relation.get("type") for relation in payload.get("relations", []))
    article_nodes = [node for node in payload.get("nodes", []) if node.get("type") == "Article"]
    clause_nodes = [node for node in payload.get("nodes", []) if node.get("type") == "Clause"]
    embedded_articles = [node for node in article_nodes if node.get("embedding")]
    embedded_clauses = [node for node in clause_nodes if node.get("embedding")]

    return {
        "document_count": node_counts.get("Document", 0),
        "article_count": node_counts.get("Article", 0),
        "clause_count": node_counts.get("Clause", 0),
        "semantic_node_count": sum(node_counts.get(label, 0) for label in ("LegalConcept", "LegalSubject", "LegalAction")),
        "relation_count_by_type": dict(relation_counts),
        "ontology_violation_rate": 0.0 if consistency.valid else 1.0,
        "duplicate_node_id_count": consistency.duplicate_node_id_count,
        "duplicate_relation_identity_count": consistency.duplicate_relation_identity_count,
        "dangling_endpoint_count": sum(1 for error in consistency.errors if "dangling" in error.lower()),
        "orphan_node_count": consistency.orphan_node_count,
        "article_semantic_coverage": _payload_article_semantic_coverage(payload, len(article_nodes)),
        "graph_density": _directed_density(len(payload.get("nodes", [])), len(payload.get("relations", []))),
        "average_degree": _average_degree(len(payload.get("nodes", [])), len(payload.get("relations", []))),
        "topology_convention": {
            "graph_density": "directed E/(N*(N-1)) without self-loops",
            "average_degree": "undirected projection 2E/N",
        },
        "embedding_coverage": {
            "Article": _coverage(len(embedded_articles), len(article_nodes)),
            "Clause": _coverage(len(embedded_clauses), len(clause_nodes)),
        },
        "connected_component_count": consistency.connected_component_count,
        "consistency_errors": list(consistency.errors),
    }


def write_graph_quality_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph_quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Graph Quality Report",
        "",
        f"- document_count: {report['document_count']}",
        f"- article_count: {report['article_count']}",
        f"- clause_count: {report['clause_count']}",
        f"- semantic_node_count: {report['semantic_node_count']}",
        f"- ontology_violation_rate: {report['ontology_violation_rate']}",
        f"- duplicate_node_id_count: {report['duplicate_node_id_count']}",
        f"- duplicate_relation_identity_count: {report['duplicate_relation_identity_count']}",
        f"- dangling_endpoint_count: {report['dangling_endpoint_count']}",
        f"- orphan_node_count: {report['orphan_node_count']}",
        f"- article_semantic_coverage: {report['article_semantic_coverage']}",
        f"- graph_density: {report['graph_density']}",
        f"- average_degree: {report['average_degree']}",
        f"- connected_component_count: {report['connected_component_count']}",
    ]
    decisions = report.get("extraction_decisions")
    if decisions:
        lines.extend(
            [
                "",
                "## Extraction Decisions",
                "",
                f"- extracted_relation_total: {decisions['extracted_relation_total']}",
                f"- accepted_count: {decisions['accepted_count']}",
                f"- review_count: {decisions['review_count']}",
                f"- rejected_count: {decisions['rejected_count']}",
                f"- acceptance_rate: {decisions['acceptance_rate']}",
                f"- review_rate: {decisions['review_rate']}",
                f"- rejection_rate: {decisions['rejection_rate']}",
            ]
        )
    (out_dir / "graph_quality.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _coverage(done: int, total: int) -> float:
    return 1.0 if total == 0 else done / total


def _directed_density(node_count: int, edge_count: int) -> float:
    if node_count < 2:
        return 0.0
    return edge_count / (node_count * (node_count - 1))


def _average_degree(node_count: int, edge_count: int) -> float:
    if node_count == 0:
        return 0.0
    return (2 * edge_count) / node_count


def _article_semantic_coverage(edges: list[dict[str, Any]], article_total: int) -> float:
    connected: set[str] = set()
    for edge in edges:
        if edge.get("relation_type") == "CONTAINS":
            continue
        if "Article" in edge.get("source_labels", []):
            connected.add(str(edge["source"]))
        if "Article" in edge.get("target_labels", []):
            connected.add(str(edge["target"]))
    return _coverage(len(connected), article_total)


def _payload_article_semantic_coverage(payload: dict, article_total: int) -> float:
    node_types = {str(node.get("id")): node.get("type") for node in payload.get("nodes", [])}
    connected: set[str] = set()
    for relation in payload.get("relations", []):
        if relation.get("type") == "CONTAINS":
            continue
        for key in ("head_id", "tail_id"):
            node_id = str(relation.get(key))
            if node_types.get(node_id) == "Article":
                connected.add(node_id)
    return _coverage(len(connected), article_total)


def decision_stats_from_paths(processed_doc_dir: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    reasons: Counter[str] = Counter()
    for decision in ("accepted", "review", "rejected"):
        path = processed_doc_dir / f"{decision}.jsonl"
        records = _read_jsonl(path)
        counts[decision] = len(records)
        for record in records:
            reason = record.get("review_reason") or record.get("rejection_reason") or record.get("reason")
            if reason:
                reasons[str(reason)] += 1
    total = sum(counts.values())
    return {
        "extracted_relation_total": total,
        "accepted_count": counts["accepted"],
        "review_count": counts["review"],
        "rejected_count": counts["rejected"],
        "acceptance_rate": 0.0 if total == 0 else counts["accepted"] / total,
        "review_rate": 0.0 if total == 0 else counts["review"] / total,
        "rejection_rate": 0.0 if total == 0 else counts["rejected"] / total,
        "decision_reason_counts": dict(reasons),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _count_components(node_ids: set[str], edges: list[list[str]]) -> int:
    if not node_ids:
        return 0
    adjacency = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if len(edge) != 2:
            continue
        head, tail = edge
        if head in adjacency and tail in adjacency:
            adjacency[head].add(tail)
            adjacency[tail].add(head)

    seen: set[str] = set()
    components = 0
    for node_id in node_ids:
        if node_id in seen:
            continue
        components += 1
        stack = [node_id]
        seen.add(node_id)
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
    return components


def _duplicate_relation_identity_count(edges: list[dict[str, Any]]) -> int:
    relation_ids = [
        str(edge["relation_id"])
        for edge in edges
        if edge.get("relation_id") not in (None, "")
    ]
    counts = Counter(relation_ids)
    return sum(1 for count in counts.values() if count > 1)


def _orphan_node_count(node_ids: set[str], edges: list[dict[str, Any]]) -> int:
    degree: Counter[str] = Counter()
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source in node_ids and target in node_ids:
            degree[source] += 1
            degree[target] += 1
    return sum(1 for node_id in node_ids if degree[node_id] == 0)


def _canonical_label(labels: list[str]) -> str:
    priority = [
        "Document",
        "Issuer",
        "Chapter",
        "Article",
        "Clause",
        "Point",
        "LegalConcept",
        "LegalSubject",
        "LegalAction",
    ]
    for label in priority:
        if label in labels:
            return label
    return labels[0] if labels else ""


def _single_row(rows: Any) -> Any:
    rows = list(rows)
    if not rows:
        return {}
    return rows[0]


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]
