"""Fixed Milestone A vector sanity queries and evidence output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


SMOKE_QUERIES = {
    "q1": "quyền thành lập và quản lý doanh nghiệp",
    "q2": "vốn điều lệ của công ty trách nhiệm hữu hạn",
    "q3": "đăng ký thay đổi nội dung đăng ký doanh nghiệp",
}
VECTOR_INDEXES = ("article_embedding", "clause_embedding")


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


def run_vector_smoke(session: SessionProtocol, vectors: list[list[float]], *, k: int = 5) -> dict[str, Any]:
    if len(vectors) != len(SMOKE_QUERIES):
        raise ValueError("Vector smoke requires exactly one vector per fixed query")
    results: list[dict[str, Any]] = []
    for (query_id, query), vector in zip(SMOKE_QUERIES.items(), vectors, strict=True):
        for index_name in VECTOR_INDEXES:
            rows = list(session.run(
                "CALL db.index.vector.queryNodes($index_name, $k, $embedding) "
                "YIELD node, score RETURN node.id AS node_id, labels(node)[0] AS label, "
                "node.number AS number, node.title AS title, node.content_raw AS content_raw, score",
                index_name=index_name,
                k=k,
                embedding=vector,
            ))
            results.append({
                "query_id": query_id,
                "query": query,
                "index_name": index_name,
                "results": [
                    {
                        "rank": rank,
                        "node_id": str(row["node_id"]),
                        "label": str(row["label"]),
                        "number": row["number"],
                        "title": row["title"],
                        "content_raw": row["content_raw"],
                        "score": float(row["score"]),
                    }
                    for rank, row in enumerate(rows, start=1)
                ],
            })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "k": k,
        "runs": results,
    }


def write_vector_smoke_evidence(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "vector_smoke_results.json"
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    judgements_path = output_dir / "vector_smoke_judgements.json"
    if not judgements_path.exists():
        judgements = [
            {
                "query_id": run["query_id"],
                "index_name": run["index_name"],
                "node_id": result["node_id"],
                "rank": result["rank"],
                "judgement": None,
                "reason": None,
                "reviewer": None,
                "reviewed_at": None,
            }
            for run in report["runs"]
            for result in run["results"]
        ]
        judgements_path.write_text(json.dumps(judgements, ensure_ascii=False, indent=2), encoding="utf-8")
    return results_path, judgements_path
