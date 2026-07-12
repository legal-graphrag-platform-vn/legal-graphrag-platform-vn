"""Canonical payload/Neo4j projections for Gate 4 evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.shared.ontology.contract import LEGACY_RELATION_ALIASES


LEGAL_EXCLUDED_PROPERTIES = {
    "embedding", "embedding_model", "embedding_provider", "embedding_dimension",
    "embedding_normalized", "embedding_content_hash", "embedding_created_at", "updated_at",
}
DATE_PROPERTIES = {"effective_from", "effective_to", "issued_date"}
DATETIME_PROPERTIES = {"created_at", "updated_at", "embedding_created_at"}
EMBEDDING_PROPERTIES = {
    "embedding", "embedding_model", "embedding_provider", "embedding_dimension",
    "embedding_normalized", "embedding_content_hash", "embedding_created_at",
}


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


def payload_projection(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    nodes = []
    for node in payload.get("nodes", []):
        properties = {
            key: value for key, value in node.items()
            if key not in {"type", *LEGAL_EXCLUDED_PROPERTIES} and value is not None
        }
        nodes.append({"id": str(node["id"]), "labels": [str(node["type"])], "properties": _normalize_properties(properties)})
    relations = []
    for relation in payload.get("relations", []):
        properties = {
            key: value for key, value in (relation.get("properties") or {}).items()
            if key not in LEGAL_EXCLUDED_PROPERTIES and value is not None
        }
        relations.append({
            "relation_id": str(properties.get("relation_id", "")),
            "type": str(relation["type"]),
            "source_id": str(relation["head_id"]),
            "target_id": str(relation["tail_id"]),
            "properties": _normalize_properties(properties),
        })
    return _sorted_projection(nodes, relations)


def graph_projection(session: SessionProtocol, node_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    node_rows = list(session.run(
        "MATCH (n) WHERE n.id IN $node_ids RETURN n.id AS id, labels(n) AS labels, properties(n) AS properties",
        node_ids=node_ids,
    ))
    relation_rows = list(session.run(
        "MATCH (a)-[r]->(b) WHERE a.id IN $node_ids AND b.id IN $node_ids "
        "RETURN r.relation_id AS relation_id, type(r) AS type, a.id AS source_id, b.id AS target_id, properties(r) AS properties",
        node_ids=node_ids,
    ))
    nodes = [
        {
            "id": str(row["id"]),
            "labels": sorted(str(label) for label in row["labels"]),
            "properties": _normalize_properties({
                k: v for k, v in dict(row["properties"]).items()
                if k not in LEGAL_EXCLUDED_PROPERTIES and v is not None
            }),
        }
        for row in node_rows
    ]
    relations = [
        {
            "relation_id": str(row["relation_id"] or ""),
            "type": str(row["type"]),
            "source_id": str(row["source_id"]),
            "target_id": str(row["target_id"]),
            "properties": _normalize_properties({
                k: v for k, v in dict(row["properties"]).items()
                if k not in LEGAL_EXCLUDED_PROPERTIES and v is not None
            }),
        }
        for row in relation_rows
    ]
    return _sorted_projection(nodes, relations)


def generate_snapshot(session: SessionProtocol, payload: Mapping[str, Any], *, graph_id: str, uri: str) -> dict[str, Any]:
    local = payload_projection(payload)
    scope_node_ids = [node["id"] for node in local["nodes"]]
    written = graph_projection(session, scope_node_ids)
    written_node_ids = [node["id"] for node in written["nodes"]]
    relation_ids = [relation["relation_id"] for relation in written["relations"]]
    node_counts = _count_values(node["labels"][0] for node in written["nodes"])
    relation_counts = _count_values(relation["type"] for relation in written["relations"])
    projection_diagnostics = _projection_diagnostics(local, written)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "git_commit": _git_commit(),
        "neo4j_uri_without_credentials": uri,
        "graph_id": graph_id,
        "snapshot_scope": "pilot_document",
        "scope_ids": [graph_id],
        "scope_membership_rule": "validated payload node IDs and relationships whose endpoints are both in that set",
        "node_id_count": len(written_node_ids),
        "node_id_sha256": _lines_hash(written_node_ids),
        "relation_id_count": len(relation_ids),
        "relation_id_sha256": _lines_hash(relation_ids),
        "payload_projection_sha256": projection_sha256(local),
        "graph_projection_sha256": projection_sha256(written),
        "projection_match": projection_sha256(local) == projection_sha256(written),
        "projection_diagnostics": projection_diagnostics,
        "embedding_state_sha256": _embedding_state_sha256(session, scope_node_ids),
        "node_count_by_label": node_counts,
        "relation_count_by_type": relation_counts,
        "missing_relation_id_count": sum(not value for value in relation_ids),
        "duplicate_node_id_count": len(written_node_ids) - len(set(written_node_ids)),
        "duplicate_relation_id_count": len(relation_ids) - len(set(relation_ids)),
        "legacy_label_count": sum(
            bool({"BaseNode", "Entity", "Concept", "Action"} & set(node["labels"]))
            for node in written["nodes"]
        ),
        "legacy_relation_count": sum(
            relation["type"] in LEGACY_RELATION_ALIASES for relation in written["relations"]
        ),
        "temporal_property_type_breakdown": _temporal_type_breakdown(session, scope_node_ids),
        "embedding_coverage": _embedding_coverage(session, scope_node_ids),
        "article_count": node_counts.get("Article", 0),
        "clause_count": node_counts.get("Clause", 0),
        "point_count": node_counts.get("Point", 0),
    }


def write_snapshot(snapshot: Mapping[str, Any], output_dir: Path, output_name: str) -> Path:
    if not output_name or Path(output_name).name != output_name or not output_name.endswith(".json"):
        raise ValueError("Snapshot output must be a .json file name without path components")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / output_name
    temporary = output_dir / f".{output_name}.tmp"
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def projection_sha256(projection: Mapping[str, Any]) -> str:
    blob = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sorted_projection(nodes: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": sorted(nodes, key=lambda item: item["id"]),
        "relations": sorted(relations, key=lambda item: (item["relation_id"], item["type"], item["source_id"], item["target_id"])),
    }


def _projection_diagnostics(local: Mapping[str, Any], written: Mapping[str, Any]) -> dict[str, Any]:
    local_nodes = {node["id"]: node for node in local["nodes"]}
    written_nodes = {node["id"]: node for node in written["nodes"]}
    local_relations = {relation["relation_id"]: relation for relation in local["relations"]}
    written_relations = {relation["relation_id"]: relation for relation in written["relations"]}
    changed_nodes = sorted(
        node_id for node_id in local_nodes.keys() & written_nodes.keys()
        if local_nodes[node_id] != written_nodes[node_id]
    )
    changed_relations = sorted(
        relation_id for relation_id in local_relations.keys() & written_relations.keys()
        if local_relations[relation_id] != written_relations[relation_id]
    )
    sample_node = changed_nodes[0] if changed_nodes else None
    sample_relation = changed_relations[0] if changed_relations else None
    return {
        "missing_node_ids": sorted(local_nodes.keys() - written_nodes.keys())[:20],
        "extra_node_ids": sorted(written_nodes.keys() - local_nodes.keys())[:20],
        "changed_node_count": len(changed_nodes),
        "changed_node_sample": {
            "id": sample_node,
            "payload": local_nodes.get(sample_node),
            "graph": written_nodes.get(sample_node),
        } if sample_node else None,
        "missing_relation_ids": sorted(local_relations.keys() - written_relations.keys())[:20],
        "extra_relation_ids": sorted(written_relations.keys() - local_relations.keys())[:20],
        "changed_relation_count": len(changed_relations),
        "changed_relation_sample": {
            "relation_id": sample_relation,
            "payload": local_relations.get(sample_relation),
            "graph": written_relations.get(sample_relation),
        } if sample_relation else None,
    }


def _normalize(value: Any) -> Any:
    if hasattr(value, "iso_format") and callable(value.iso_format):
        text = value.iso_format()
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return _canonical_datetime(parsed)
        return text
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Canonical DateTime values must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in sorted(properties.items()):
        if key in DATE_PROPERTIES and isinstance(value, str):
            value = date.fromisoformat(value)
        elif key in DATETIME_PROPERTIES and isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        normalized[key] = _normalize(value)
    return normalized


def _lines_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(values))).encode("utf-8")).hexdigest()


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _embedding_state_sha256(session: SessionProtocol, node_ids: list[str]) -> str:
    rows = list(session.run(
        "MATCH (n) WHERE n.id IN $node_ids AND (n:Article OR n:Clause) "
        "RETURN n.id AS id, n.embedding_model AS model, n.embedding_provider AS provider, "
        "n.embedding_dimension AS dimension, n.embedding_normalized AS normalized, "
        "n.embedding_content_hash AS content_hash, size(n.embedding) AS vector_size",
        node_ids=node_ids,
    ))
    state = sorted((_normalize(dict(row)) for row in rows), key=lambda item: item["id"])
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _embedding_coverage(session: SessionProtocol, node_ids: list[str]) -> dict[str, dict[str, float | int]]:
    rows = list(session.run(
        "MATCH (n) WHERE n.id IN $node_ids AND (n:Article OR n:Clause) "
        "RETURN CASE WHEN n:Article THEN 'Article' ELSE 'Clause' END AS label, "
        "count(n) AS total, count(n.embedding) AS embedded",
        node_ids=node_ids,
    ))
    result: dict[str, dict[str, float | int]] = {}
    for row in rows:
        total = int(row["total"] or 0)
        embedded = int(row["embedded"] or 0)
        result[str(row["label"])] = {
            "total": total,
            "embedded": embedded,
            "coverage": 0.0 if total == 0 else embedded / total,
        }
    for label in ("Article", "Clause"):
        result.setdefault(label, {"total": 0, "embedded": 0, "coverage": 0.0})
    return result


def _temporal_type_breakdown(session: SessionProtocol, node_ids: list[str]) -> dict[str, int]:
    node_rows = list(session.run(
        "MATCH (n) WHERE n.id IN $node_ids "
        "UNWIND ['effective_from','effective_to','issued_date','created_at'] AS property "
        "WITH property, n[property] AS value WHERE value IS NOT NULL "
        "RETURN 'node.' + property + ':' + valueType(value) AS key, count(*) AS count",
        node_ids=node_ids,
    ))
    relation_rows = list(session.run(
        "MATCH (a)-[r]->(b) WHERE a.id IN $node_ids AND b.id IN $node_ids "
        "UNWIND ['effective_from','created_at'] AS property "
        "WITH property, r[property] AS value WHERE value IS NOT NULL "
        "RETURN 'relation.' + property + ':' + valueType(value) AS key, count(*) AS count",
        node_ids=node_ids,
    ))
    return dict(sorted((str(row["key"]), int(row["count"])) for row in [*node_rows, *relation_rows]))


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True)
    return result.stdout.strip() or "unknown"
