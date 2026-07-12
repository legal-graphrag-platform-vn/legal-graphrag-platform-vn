"""Validate extraction artifacts before any post-extraction M3 command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ExtractionReadinessError(RuntimeError):
    """Raised when extraction artifacts cannot support a Milestone A run."""


@dataclass(frozen=True, slots=True)
class ExtractionReadiness:
    extracted_count: int
    accepted_count: int
    review_count: int
    rejected_count: int


def validate_extraction_readiness(processed_dir: Path) -> ExtractionReadiness:
    blocked_path = processed_dir / "extraction_blocked.json"
    if blocked_path.exists():
        blocked = json.loads(blocked_path.read_text(encoding="utf-8"))
        raise ExtractionReadinessError(f"Extraction is blocked: {blocked.get('reason', 'unknown provider failure')}")

    run_path = processed_dir / "extraction_run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if not run.get("complete_document"):
            raise ExtractionReadinessError(
                "Extraction artifacts are from a smoke subset; complete the full document before Gate 2"
            )

    required = ("extract.jsonl", "accepted.jsonl", "review.jsonl", "rejected.jsonl", "entity_index.json")
    for name in required:
        path = processed_dir / name
        if not path.exists():
            raise ExtractionReadinessError(f"Missing extraction artifact: {path}")

    counts = {name: _count_jsonl(processed_dir / f"{name}.jsonl") for name in ("extract", "accepted", "review", "rejected")}
    entity_index = json.loads((processed_dir / "entity_index.json").read_text(encoding="utf-8"))
    if not isinstance(entity_index, dict):
        raise ExtractionReadinessError("entity_index.json must contain a JSON object")
    if counts["extract"] != counts["accepted"] + counts["review"] + counts["rejected"]:
        raise ExtractionReadinessError("Extraction decision counts do not reconcile")
    if counts["accepted"] == 0:
        raise ExtractionReadinessError("accepted.jsonl is empty; Gate 2 has not passed")
    if not entity_index:
        raise ExtractionReadinessError("Gate 2 failed: entity_index.json is empty")
    return ExtractionReadiness(counts["extract"], counts["accepted"], counts["review"], counts["rejected"])


def _count_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExtractionReadinessError(f"Invalid JSONL at {path}:{line_no}") from exc
            count += 1
    return count
