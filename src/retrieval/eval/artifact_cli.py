"""Generate read-only artifact evidence for a retrieval evaluation dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from src.application.retrieval_factory import inspect_retrieval_artifact_runtime
from src.retrieval.eval.artifact_verification import build_artifact_verification
from src.retrieval.eval.development import load_development_dataset
from src.shared.retrieval_contract import RetrievalFilters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.retrieval.eval.artifact_cli")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--graph-snapshot", type=Path, required=True)
    parser.add_argument("--document-id", action="append", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--working-tree-state", choices=("clean", "dirty"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset = load_development_dataset(args.dataset)
    if sorted(dataset.document_ids) != sorted(args.document_id):
        raise ValueError("Dataset document IDs must match --document-id filters")
    temporal_unit_ids = sorted(
        {
            case.gold_temporal.subject_unit_id
            for case in dataset.cases
            if case.gold_temporal is not None
        }
    )
    runtime_evidence = inspect_retrieval_artifact_runtime(
        RetrievalFilters(document_ids=args.document_id), temporal_unit_ids
    )
    report = build_artifact_verification(
        dataset=dataset,
        dataset_path=args.dataset,
        hierarchy_path=args.hierarchy,
        accepted_path=args.accepted,
        graph_snapshot_path=args.graph_snapshot,
        capabilities=dict(runtime_evidence["capabilities"]),
        temporal_units=list(runtime_evidence["temporal_units"]),
        runtime_identity=dict(runtime_evidence["runtime_identity"]),
        source_commit=args.source_commit,
        working_tree_state=args.working_tree_state,
        verification_command_hash=_command_hash(args),
    )
    _write_atomic(args.output, report)
    return 0 if report["verification"]["status"] == "PASS" else 1


def _write_atomic(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _command_hash(args: argparse.Namespace) -> str:
    contract = {
        "module": "src.retrieval.eval.artifact_cli",
        "dataset": str(args.dataset),
        "hierarchy": str(args.hierarchy),
        "accepted": str(args.accepted),
        "graph_snapshot": str(args.graph_snapshot),
        "document_ids": sorted(args.document_id),
    }
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
