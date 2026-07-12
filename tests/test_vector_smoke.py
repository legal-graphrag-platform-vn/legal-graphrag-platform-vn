from __future__ import annotations

import json

from src.infrastructure.neo4j.vector_smoke import SMOKE_QUERIES, run_vector_smoke, write_vector_smoke_evidence


class FakeSession:
    def run(self, cypher: str, **parameters):
        return [
            {
                "node_id": f"node_{parameters['index_name']}",
                "label": "Article",
                "number": "1",
                "title": "Title",
                "content_raw": "Content",
                "score": 0.9,
            }
        ]


def test_vector_smoke_runs_every_query_on_both_indexes(tmp_path) -> None:
    report = run_vector_smoke(FakeSession(), [[0.0] * 1024 for _ in SMOKE_QUERIES])
    assert len(report["runs"]) == 6
    assert all(len(run["results"]) == 1 for run in report["runs"])

    results_path, judgements_path = write_vector_smoke_evidence(report, tmp_path)
    assert len(json.loads(results_path.read_text())) == 3
    judgements = json.loads(judgements_path.read_text())
    assert len(judgements) == 6
    assert all(item["judgement"] is None for item in judgements)


def test_vector_smoke_does_not_overwrite_manual_judgements(tmp_path) -> None:
    report = run_vector_smoke(FakeSession(), [[0.0] * 1024 for _ in SMOKE_QUERIES])
    _, judgements_path = write_vector_smoke_evidence(report, tmp_path)
    judgements_path.write_text('[{"judgement":"relevant"}]', encoding="utf-8")

    write_vector_smoke_evidence(report, tmp_path)

    assert json.loads(judgements_path.read_text())[0]["judgement"] == "relevant"
