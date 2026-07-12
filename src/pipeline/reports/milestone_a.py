"""Milestone A pilot evidence validation and report generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.infrastructure.neo4j.vector_smoke import SMOKE_QUERIES, VECTOR_INDEXES


class MilestoneAReportError(RuntimeError):
    pass


def generate_milestone_a_report(raw_doc_code: str, reports_dir: Path) -> dict[str, Any]:
    document_dir = reports_dir / raw_doc_code
    vector_dir = document_dir / "vector_smoke"
    results = _read_json(vector_dir / "vector_smoke_results.json")
    judgements = _read_json(vector_dir / "vector_smoke_judgements.json")
    graph_quality = _read_json(document_dir / "graph_quality.json")
    write_1 = _read_json(document_dir / "snapshots" / "write_1.json")
    write_2 = _read_json(document_dir / "snapshots" / "write_2.json")
    post_embedding = _read_json(document_dir / "snapshots" / "post_embedding.json")
    post_integration = _read_json(document_dir / "snapshots" / "post_integration.json")

    vector = _validate_vector_evidence(results, judgements)
    idempotency_keys = (
        "node_id_sha256", "relation_id_sha256", "graph_projection_sha256",
        "payload_projection_sha256",
    )
    write_idempotent = all(write_1.get(key) == write_2.get(key) for key in idempotency_keys)
    projection_match = all(
        snapshot.get("projection_match")
        and snapshot.get("payload_projection_sha256") == snapshot.get("graph_projection_sha256")
        for snapshot in (write_1, write_2, post_embedding, post_integration)
    )
    integration_preserved_pilot = all(
        post_embedding.get(key) == post_integration.get(key)
        for key in (*idempotency_keys, "embedding_state_sha256")
    )
    coverage = post_embedding.get("embedding_coverage", {})
    embedding_pass = all(coverage.get(label, {}).get("coverage") == 1.0 for label in ("Article", "Clause"))
    semantic_graph = graph_quality.get("semantic_graph", {})
    graph_quality_pass = all(
        graph_quality.get(key) == 0
        for key in (
            "ontology_violation_count", "duplicate_node_id_count",
            "duplicate_relation_identity_count", "dangling_endpoint_count",
        )
    ) and semantic_graph.get("edge_accounting_reconciles") is True

    gates = {
        "gate_4_write_idempotency": write_idempotent and projection_match,
        "gate_5_embedding": embedding_pass,
        "gate_5_vector_review": vector["pass"],
        "gate_6_graph_quality": graph_quality_pass,
        "integration_preserved_pilot": integration_preserved_pilot,
    }
    report = {
        "raw_doc_code": raw_doc_code,
        "judgement_summary": vector,
        "semantic_edge_accounting": {
            "semantic_relation_total": semantic_graph.get("semantic_relation_total"),
            "topology_edge_count": semantic_graph.get("edge_count"),
            "excluded_edge_count_by_type": semantic_graph.get("excluded_edge_count_by_type", {}),
            "reconciles": semantic_graph.get("edge_accounting_reconciles", False),
        },
        "gates": gates,
        "pilot_evidence_pass": all(gates.values()),
        "corpus_gate_pass": False,
        "milestone_a_pass": False,
        "remaining": ["four_document_corpus", "external_reference_reconciliation"],
    }
    return report


def write_milestone_a_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "milestone_a_report.json"
    md_path = output_dir / "milestone_a_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    vector = report["judgement_summary"]
    accounting = report["semantic_edge_accounting"]
    lines = [
        f"# Milestone A Pilot Report — {report['raw_doc_code']}", "",
        f"- judgements_complete: {vector['complete_count']}/{vector['expected_count']}",
        *[f"- {query_id} relevant@5: {'PASS' if passed else 'FAIL'}" for query_id, passed in vector["query_relevant_at_5"].items()],
        *[f"- {index_name} relevant@5: {'PASS' if passed else 'FAIL'}" for index_name, passed in vector["index_relevant_at_5"].items()],
        f"- semantic_relation_total: {accounting['semantic_relation_total']}",
        f"- semantic_topology_edge_count: {accounting['topology_edge_count']}",
        f"- semantic_excluded_edge_count_by_type: {accounting['excluded_edge_count_by_type']}",
        f"- semantic_edge_accounting_reconciles: {accounting['reconciles']}", "",
        "## Gates", "",
        *[f"- {gate}: {'PASS' if passed else 'FAIL'}" for gate, passed in report["gates"].items()],
        f"- pilot_evidence_pass: {report['pilot_evidence_pass']}",
        f"- milestone_a_pass: {report['milestone_a_pass']} (corpus remains required)",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _validate_vector_evidence(results: dict[str, Any], judgements: list[dict[str, Any]]) -> dict[str, Any]:
    expected_keys = {
        (run["query_id"], run["index_name"], result["node_id"], result["rank"])
        for run in results.get("runs", [])
        for result in run.get("results", [])
    }
    judgement_keys = {
        (item.get("query_id"), item.get("index_name"), item.get("node_id"), item.get("rank"))
        for item in judgements
    }
    valid_values = {"relevant", "not_relevant"}
    complete = [
        item for item in judgements
        if item.get("judgement") in valid_values
        and item.get("reason")
        and item.get("reviewer") == "lamdx4"
        and _valid_reviewed_at(item.get("reviewed_at"))
    ]
    query_pass = {
        query_id: any(item.get("query_id") == query_id and item.get("judgement") == "relevant" for item in complete)
        for query_id in SMOKE_QUERIES
    }
    index_pass = {
        index_name: any(item.get("index_name") == index_name and item.get("judgement") == "relevant" for item in complete)
        for index_name in VECTOR_INDEXES
    }
    keys_match = expected_keys == judgement_keys
    return {
        "expected_count": len(expected_keys),
        "complete_count": len(complete),
        "keys_match_results": keys_match,
        "query_relevant_at_5": query_pass,
        "index_relevant_at_5": index_pass,
        "pass": keys_match and len(complete) == len(expected_keys) == 30 and all(query_pass.values()) and all(index_pass.values()),
    }


def _valid_reviewed_at(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _read_json(path: Path):
    if not path.exists():
        raise MilestoneAReportError(f"Missing Milestone A evidence: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
