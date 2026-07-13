import json
from pathlib import Path

import pytest

from src.retrieval.eval import cli
from src.retrieval.eval.cli import validate_dataset_document_scope
from src.retrieval.eval.development import DevelopmentEvaluationDataset


def test_evaluation_document_scope_must_match_dataset() -> None:
    dataset = DevelopmentEvaluationDataset.model_validate(
        {
            "schema_version": "retrieval-evaluation-dataset-v1",
            "evaluation_scope": "pilot_development",
            "name": "scope test",
            "document_ids": ["ldn_2020"],
            "target_query_count": 1,
            "review": {
                "reviewer": "reviewer",
                "status": "pending_human_sign_off",
                "reviewed_at": None,
            },
            "cases": [
                {
                    "query_id": "q1",
                    "query": "query",
                    "intent": "factual",
                    "expected_status": "supported",
                    "capability_requirement": {
                        "name": "hybrid_seed_and_semantic_graph",
                        "expected_available": True,
                        "reason": "available",
                    },
                    "gold_relevance": [
                        {
                            "unit_id": "ldn_2020_art1",
                            "relevance": 3,
                            "reason": "direct",
                        }
                    ],
                    "review": {
                        "reviewer": "reviewer",
                        "status": "pending_human_sign_off",
                        "reviewed_at": None,
                    },
                }
            ],
        }
    )

    validate_dataset_document_scope(dataset, ["ldn_2020"])
    with pytest.raises(ValueError, match="exactly match"):
        validate_dataset_document_scope(dataset, ["another_document"])


def test_pending_dataset_fails_before_runtime_initialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("runtime must not be initialized")

    monkeypatch.setattr(cli, "create_retrieval_runtime", fail_if_called)
    dataset = tmp_path / "pending.json"
    dataset.write_text(json.dumps(_pending_dataset_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="requires approved dataset"):
        cli.main(
            [
                "--dataset",
                str(dataset),
                "--output",
                "/tmp/should-not-exist.json",
                "--document-id",
                "ldn_2020",
                "--source-commit",
                "abc",
                "--working-tree-state",
                "clean",
                "--graph-snapshot-hash",
                "snapshot",
            ]
        )


def _pending_dataset_payload() -> dict:
    return {
        "schema_version": "retrieval-evaluation-dataset-v1",
        "evaluation_scope": "pilot_development",
        "name": "pending test dataset",
        "document_ids": ["ldn_2020"],
        "target_query_count": 1,
        "review": {
            "reviewer": "test reviewer",
            "status": "pending_human_sign_off",
            "reviewed_at": None,
        },
        "cases": [
            {
                "query_id": "q1",
                "query": "Điều kiện thành lập doanh nghiệp",
                "intent": "factual",
                "expected_status": "supported",
                "capability_requirement": {
                    "name": "hybrid_seed_and_semantic_graph",
                    "expected_available": True,
                    "reason": "test capability",
                },
                "gold_relevance": [
                    {
                        "unit_id": "ldn_2020_art1",
                        "relevance": 3,
                        "reason": "test gold",
                    }
                ],
                "review": {
                    "reviewer": "test reviewer",
                    "status": "pending_human_sign_off",
                    "reviewed_at": None,
                },
            }
        ],
    }
