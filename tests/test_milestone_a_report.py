from __future__ import annotations

import json

from src.pipeline.reports.milestone_a import generate_milestone_a_report


def _write(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_milestone_report_requires_complete_human_review_and_reconciled_edges(tmp_path) -> None:
    root = tmp_path / "DOC"
    runs = []
    judgements = []
    for query_id in ("q1", "q2", "q3"):
        for index_name in ("article_embedding", "clause_embedding"):
            results = [{"node_id": f"{query_id}_{index_name}_{rank}", "rank": rank} for rank in range(1, 6)]
            runs.append({"query_id": query_id, "index_name": index_name, "results": results})
            for result in results:
                judgements.append({
                    "query_id": query_id,
                    "index_name": index_name,
                    **result,
                    "judgement": "relevant" if result["rank"] == 1 else "not_relevant",
                    "reason": "manual",
                    "reviewer": "lamdx4",
                    "reviewed_at": "2026-07-12T23:03:32Z",
                })
    _write(root / "vector_smoke/vector_smoke_results.json", {"runs": runs})
    _write(root / "vector_smoke/vector_smoke_judgements.json", judgements)
    snapshot = {
        "projection_match": True,
        "node_id_sha256": "n",
        "relation_id_sha256": "r",
        "graph_projection_sha256": "g",
        "payload_projection_sha256": "g",
        "embedding_state_sha256": "e",
        "embedding_coverage": {"Article": {"coverage": 1.0}, "Clause": {"coverage": 1.0}},
    }
    for name in ("write_1", "write_2", "post_embedding", "post_integration"):
        _write(root / f"snapshots/{name}.json", snapshot)
    _write(root / "graph_quality.json", {
        "ontology_violation_count": 0,
        "duplicate_node_id_count": 0,
        "duplicate_relation_identity_count": 0,
        "dangling_endpoint_count": 0,
        "semantic_graph": {
            "semantic_relation_total": 775,
            "edge_count": 746,
            "excluded_edge_count_by_type": {"REFERS_TO": 29},
            "edge_accounting_reconciles": True,
        },
    })

    report = generate_milestone_a_report("DOC", tmp_path)

    assert report["judgement_summary"]["complete_count"] == 30
    assert report["pilot_evidence_pass"] is True
    assert report["milestone_a_pass"] is False
