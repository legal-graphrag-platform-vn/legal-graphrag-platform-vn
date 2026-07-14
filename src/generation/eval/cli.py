"""Run pilot answer evaluation with explicit evidence metadata."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Sequence

from src.application.answer_factory import (
    AnswerApplicationSettings,
    create_answer_generator,
)
from src.application.retrieval_factory import create_retrieval_runtime
from src.generation.config import GenerationConfig
from src.generation.context_projection import SYSTEM_INSTRUCTION
from src.generation.eval.models import AnswerEvaluationDataset
from src.generation.eval.runner import AnswerEvaluationRunner, EvaluationMetadata
from src.generation.models import ANSWER_CONTRACT_VERSION
from src.shared.retrieval_contract import RETRIEVAL_CONTRACT_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.generation.eval.cli")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--working-tree-state", choices=("clean", "dirty"), required=True
    )
    parser.add_argument("--graph-snapshot-hash", required=True)
    parser.add_argument("--allow-pending-review", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset_bytes = args.dataset.read_bytes()
    dataset = AnswerEvaluationDataset.model_validate_json(dataset_bytes)
    if dataset.review.status != "approved" and not args.allow_pending_review:
        raise ValueError("Answer evaluation dataset requires approved human review")
    config = GenerationConfig()
    settings = AnswerApplicationSettings()
    metadata = EvaluationMetadata(
        source_commit=args.source_commit,
        working_tree_state=args.working_tree_state,
        dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        graph_snapshot_hash=args.graph_snapshot_hash,
        retrieval_contract_version=RETRIEVAL_CONTRACT_VERSION,
        answer_contract_version=ANSWER_CONTRACT_VERSION,
        prompt_sha256=_sha256(SYSTEM_INSTRUCTION),
        generation_config_sha256=_sha256(
            json.dumps(config.model_dump(mode="json"), sort_keys=True)
        ),
        provider=settings.answer_provider,
        model=settings.answer_model,
    )
    report = asyncio.run(_run(dataset, metadata, config, settings))
    _write_atomic(args.output, report)
    return 0


async def _run(
    dataset: AnswerEvaluationDataset,
    metadata: EvaluationMetadata,
    config: GenerationConfig,
    settings: AnswerApplicationSettings,
) -> dict[str, object]:
    with create_retrieval_runtime() as retrieval:
        generator = create_answer_generator(config, settings)
        try:
            return await AnswerEvaluationRunner(retrieval, generator).run(
                dataset, metadata
            )
        finally:
            await generator.aclose()


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
