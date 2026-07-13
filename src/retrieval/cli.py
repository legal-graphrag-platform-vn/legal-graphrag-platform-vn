"""Synchronous developer CLI for the canonical retrieval runtime."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from src.application.retrieval_factory import create_retrieval_runtime
from src.retrieval.errors import RetrievalError, RetrievalOutputError
from src.retrieval.models import IntentType, RetrievalFilters, RetrievalRequest


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.retrieval.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    retrieve = subparsers.add_parser("retrieve")
    retrieve.add_argument("--query", required=True)
    retrieve.add_argument("--document-id", action="append", default=[])
    retrieve.add_argument("--doc-type", action="append", default=[])
    retrieve.add_argument("--legal-status", action="append", default=[])
    retrieve.add_argument("--query-date", type=date.fromisoformat)
    retrieve.add_argument("--top-k", type=int)
    retrieve.add_argument("--final-k", type=int)
    retrieve.add_argument(
        "--force-intent", choices=[value.value for value in IntentType]
    )
    retrieve.add_argument("--no-reranker", action="store_true")
    retrieve.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = build_parser().parse_args(argv)
    try:
        request = RetrievalRequest(
            query=args.query,
            filters=RetrievalFilters(
                document_ids=args.document_id,
                doc_types=args.doc_type,
                legal_statuses=args.legal_status,
                query_date=args.query_date,
            ),
            top_k=args.top_k,
            final_k=args.final_k,
            force_intent=IntentType(args.force_intent) if args.force_intent else None,
            enable_reranker=False if args.no_reranker else None,
        )
        with create_retrieval_runtime() as runtime:
            context = runtime.retrieve(request)
        payload = context.model_dump_json(indent=2)
        if args.output is not None:
            atomic_write_text(args.output, payload)
        else:
            sys.stdout.write(payload)
            sys.stdout.write("\n")
        return 0
    except (RetrievalError, RetrievalOutputError, ValidationError, ValueError) as exc:
        logger.error(
            "Retrieval command failed: error_type=%s reason=%s",
            type(exc).__name__,
            str(exc),
        )
        return 2


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise RetrievalOutputError(f"Could not write retrieval output: {path}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
