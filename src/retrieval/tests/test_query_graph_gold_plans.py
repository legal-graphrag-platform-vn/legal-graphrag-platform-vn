from __future__ import annotations

from pathlib import Path

import pytest
from neo4j import GraphDatabase

from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.eval.query_graph_qg0 import (
    QG0Report,
    gold_plan_config_sha256,
    load_gold_plan_config,
    run_qg0,
)
from src.retrieval.planning.executor import PlannedPathExecutor
from src.retrieval.planning.linker import StructuralEndpointResolver


CONFIG_PATH = Path("configs/evaluation/query_graph_gold_plans.json")
RESULT_PATH = Path("results/retrieval/query_graph_qg0.json")


def test_gold_plan_config_has_exactly_the_reviewed_linear_cases() -> None:
    config = load_gold_plan_config(CONFIG_PATH)

    assert [case.query_id for case in config.cases] == [
        "multi_hop_01",
        "multi_hop_02",
        "multi_hop_04",
    ]
    assert config.excluded_cases == {
        "multi_hop_03": "direct atomic one-hop reference, outside exact-linear V1",
        "multi_hop_05": "branching one-hop case, outside exact-linear V1",
    }
    assert all(len(case.steps) == 2 for case in config.cases)
    assert all(case.expected_node_ids[0] == case.anchor_id for case in config.cases)
    assert all(case.expected_node_ids[-1] == case.target_id for case in config.cases)


def test_gold_plan_config_rejects_legacy_relation_alias(tmp_path: Path) -> None:
    payload = CONFIG_PATH.read_text(encoding="utf-8").replace(
        '"REFERS_TO"', '"REFERENCES"', 1
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_gold_plan_config(invalid)


def test_qg0_result_is_pinned_to_current_gold_config_and_passes_exact_gate() -> None:
    config = load_gold_plan_config(CONFIG_PATH)
    report = QG0Report.model_validate_json(RESULT_PATH.read_text(encoding="utf-8"))

    assert report.config_sha256 == gold_plan_config_sha256(config)
    assert report.status == "passed"
    assert report.summary.anchor_resolved_count == len(config.cases)
    assert report.summary.exact_denotation_count == len(config.cases)
    assert report.summary.false_positive_path_count == 0
    assert all(case.exact_denotation for case in report.cases)


@pytest.mark.integration
@pytest.mark.retrieval_readonly
def test_qg0_live_gold_plans_are_exact_and_negative_cases_fail_closed() -> None:
    uri = "bolt://127.0.0.1:7688"
    password = _infra_password()
    driver = GraphDatabase.driver(uri, auth=("neo4j", password))
    try:
        driver.verify_connectivity()
        repo = Neo4jRetrieverRepo(driver)
        report = run_qg0(
            load_gold_plan_config(CONFIG_PATH),
            resolver=StructuralEndpointResolver(repo),
            executor=PlannedPathExecutor(repo),
            graph_identity={"uri_without_credentials": uri, "database_name": "neo4j"},
        )
    finally:
        driver.close()

    assert report.status == "passed"
    assert report.summary.linear_case_count == 3
    assert report.summary.anchor_resolved_count == 3
    assert report.summary.exact_denotation_count == 3
    assert report.summary.false_positive_path_count == 0
    assert report.negative_checks.reversed_direction_reason == "NO_PATH"
    assert report.negative_checks.missing_edge_reason == "NO_PATH"
    assert report.negative_checks.answer_provider_call_count == 0
    assert all(case.reason_code == "SATISFIED" for case in report.cases)


def _infra_password() -> str:
    for line in Path("infra/.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("NEO4J_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("infra/.env does not define NEO4J_PASSWORD")
