"""Validated LuatVietnam provider-reference sidecars."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.pipeline.config import settings


PROVIDER_REFERENCE_CONTRACT_VERSION = "provider-reference-mention-v1"


class ProviderReferenceSidecarError(ValueError):
    """Raised when provider evidence cannot be aligned to canonical source."""


class ProviderReferenceMentionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["provider-reference-mention-v1"]
    provider: Literal["luatvietnam"]
    provider_source_document_id: str = Field(pattern=r"^\d+$")
    provider_source_item_id: str | None = Field(default=None, pattern=r"^\d+$")
    provider_target_document_id: str | None = Field(default=None, pattern=r"^\d+$")
    provider_target_item_ids: tuple[str, ...] = ()
    provider_relation_id: str | None = Field(default=None, pattern=r"^\d+$")
    provider_link_type: Literal["CHANGE_CONTENT", "REFERENCE", "UNKNOWN"]
    citation_text: str = Field(min_length=1)
    source_char_start: int = Field(ge=0)
    source_char_end: int = Field(ge=1)
    provider_href: str | None = None


def load_provider_references(
    raw_dir: Path, source_text: str | None = None
) -> tuple[ProviderReferenceMentionV1, ...]:
    processed_path = settings.data_processed_dir / raw_dir.name / "references.jsonl"
    path = processed_path if processed_path.is_file() else raw_dir / "references.jsonl"
    if not path.is_file():
        return ()
    rows: list[ProviderReferenceMentionV1] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            reference = ProviderReferenceMentionV1.model_validate_json(line)
        except Exception as exc:
            raise ProviderReferenceSidecarError(
                f"Malformed provider reference at {path}:{line_number}"
            ) from exc
        if any(not item.isdigit() for item in reference.provider_target_item_ids):
            raise ProviderReferenceSidecarError(
                f"Invalid provider target item at {path}:{line_number}"
            )
        if reference.source_char_end <= reference.source_char_start:
            raise ProviderReferenceSidecarError(
                f"Invalid provider reference span at {path}:{line_number}"
            )
        if source_text is not None:
            marker = source_text[
                reference.source_char_start : reference.source_char_end
            ]
            if marker != f"[{reference.citation_text}]":
                raise ProviderReferenceSidecarError(
                    f"Provider reference span mismatch at {path}:{line_number}"
                )
        rows.append(reference)
    return tuple(rows)


def ensure_luatvietnam_reference_sidecar(
    raw_dir: Path,
) -> tuple[ProviderReferenceMentionV1, ...]:
    """Backfill sidecar from saved HTML, refusing source-coordinate drift."""

    metadata_path = raw_dir / "metadata.json"
    source_path = raw_dir / "source.txt"
    html_path = raw_dir / "source.html"
    if not metadata_path.is_file() or not source_path.is_file():
        raise ProviderReferenceSidecarError(
            f"Missing metadata/source in raw bundle: {raw_dir}"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("source_provider") != "luatvietnam.vn":
        return load_provider_references(
            raw_dir, source_path.read_text(encoding="utf-8").rstrip("\n")
        )
    if not html_path.is_file():
        raise ProviderReferenceSidecarError(
            f"Missing source.html for LuatVietnam bundle: {raw_dir}"
        )
    source_url = str(metadata.get("source_url") or "")
    if not source_url:
        raise ProviderReferenceSidecarError(
            "LuatVietnam metadata is missing source_url"
        )

    from experiments.luatvietnam_crawler.parser import parse_document

    document = parse_document(html_path.read_text(encoding="utf-8"), source_url)
    expected_external_id = str(metadata.get("external_id") or "")
    if document.external_id != expected_external_id:
        raise ProviderReferenceSidecarError(
            "HTML document identity does not match metadata external_id"
        )
    canonical_source = source_path.read_text(encoding="utf-8").rstrip("\n")
    if document.source_text != canonical_source:
        raise ProviderReferenceSidecarError(
            "HTML serialization does not match canonical source.txt"
        )

    processed_dir = settings.data_processed_dir / raw_dir.name
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / "references.jsonl"
    content = "".join(
        json.dumps(reference.as_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for reference in document.provider_references
    )
    for target_path in (path, raw_dir / "references.jsonl"):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, target_path)
        finally:
            temporary.unlink(missing_ok=True)
    return load_provider_references(raw_dir, canonical_source)
