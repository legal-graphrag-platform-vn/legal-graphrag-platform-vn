"""Run a versioned pilot development evaluation against one runtime profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from src.application.retrieval_factory import (
    RetrievalApplicationSettings,
    create_retrieval_runtime,
)
from src.retrieval.config import RetrievalConfig
from src.retrieval.eval.development import (
    DevelopmentEvaluationDataset,
    DevelopmentEvaluationMetadata,
    DevelopmentEvaluationRunner,
    assert_development_dataset_approved,
    load_development_dataset,
    write_development_report,
)
from src.shared.retrieval_contract import RetrievalFilters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.retrieval.eval.cli")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-id", action="append", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--working-tree-state", choices=("clean", "dirty"), required=True
    )
    parser.add_argument("--graph-snapshot-hash", required=True)
    parser.add_argument("--profile-name", default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--allow-pending-review", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_development_dataset(args.dataset)
    if not args.allow_pending_review:
        assert_development_dataset_approved(dataset)
    validate_dataset_document_scope(dataset, args.document_id)
    config = RetrievalConfig()
    application_settings = RetrievalApplicationSettings()
    config_payload = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    metadata = DevelopmentEvaluationMetadata(
        source_commit=args.source_commit,
        working_tree_state=args.working_tree_state,
        router_config_hash=hashlib.sha256(config_payload.encode("utf-8")).hexdigest(),
        embedding_contract=(
            f"{application_settings.embedding_provider}:"
            f"{application_settings.embedding_model}:"
            f"{application_settings.embedding_dimension}"
        ),
        reranker_contract=(
            config.reranker_model if config.reranker_enabled else "disabled"
        ),
        neo4j_graph_snapshot_hash=args.graph_snapshot_hash,
    )
    with create_retrieval_runtime(config, application_settings) as runtime:
        report = DevelopmentEvaluationRunner({args.profile_name: runtime}).run(
            args.dataset,
            metadata=metadata,
            filters=RetrievalFilters(document_ids=args.document_id),
            top_k=args.top_k,
            require_approved_dataset=not args.allow_pending_review,
        )
    write_development_report(report, args.output)
    return 0


def validate_dataset_document_scope(
    dataset: DevelopmentEvaluationDataset,
    requested_document_ids: list[str],
) -> None:
    if sorted(dataset.document_ids) != sorted(requested_document_ids):
        raise ValueError(
            "Evaluation document filters must exactly match dataset document_ids"
        )


if __name__ == "__main__":
    raise SystemExit(main())
