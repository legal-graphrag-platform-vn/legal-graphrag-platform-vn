"""Atomic publication for extraction decision artifact sets."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


ACTIVE_ARTIFACT_NAMES = (
    "extract.jsonl",
    "prettier_extract.json",
    "accepted.jsonl",
    "review.jsonl",
    "rejected.jsonl",
    "entity_index.json",
    "extraction_run.json",
)


def create_staging_artifact_dir(processed_doc_dir: Path) -> tuple[str, Path]:
    artifact_set_id = uuid.uuid4().hex
    root = processed_doc_dir / "artifact_sets"
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{artifact_set_id}.tmp"
    staging.mkdir(parents=False, exist_ok=False)
    return artifact_set_id, staging


def publish_staged_artifacts(processed_doc_dir: Path, artifact_set_id: str, staging: Path) -> Path:
    missing = [name for name in ACTIVE_ARTIFACT_NAMES if not (staging / name).exists()]
    if missing:
        raise ValueError(f"Cannot publish incomplete extraction artifact set: {missing}")

    artifact_root = processed_doc_dir / "artifact_sets"
    final_dir = artifact_root / artifact_set_id
    staging.replace(final_dir)

    # Stable aliases all follow one pointer. Install aliases first, then switch
    # the pointer once so readers can observe either the old set or the new set,
    # never a mixture of both.
    for name in ACTIVE_ARTIFACT_NAMES:
        alias = processed_doc_dir / name
        alias_tmp = processed_doc_dir / f".{name}.{artifact_set_id}.tmp"
        alias_tmp.symlink_to(Path("current_extraction") / name)
        alias_tmp.replace(alias)

    pointer = processed_doc_dir / "current_extraction"
    pointer_tmp = processed_doc_dir / f".current_extraction.{artifact_set_id}.tmp"
    pointer_tmp.symlink_to(Path("artifact_sets") / artifact_set_id, target_is_directory=True)
    pointer_tmp.replace(pointer)

    return final_dir


def discard_staging_artifacts(staging: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)


def active_artifact_dir(processed_doc_dir: Path) -> Path:
    pointer = processed_doc_dir / "current_extraction"
    return pointer.resolve(strict=True) if pointer.exists() else processed_doc_dir


def replace_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
