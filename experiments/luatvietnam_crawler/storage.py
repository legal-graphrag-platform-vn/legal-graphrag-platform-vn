"""Filesystem output isolated under this experiment by default."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import CrawledDocument, DetailMetadata


def save_document(
    document: CrawledDocument,
    output_root: Path,
    *,
    source_html: str | None = None,
) -> Path:
    if not document.raw_doc_code.startswith("LTV_"):
        raise ValueError("Experimental raw_doc_code must start with LTV_")
    output_root = output_root.resolve()
    document_dir = (output_root / document.raw_doc_code).resolve()
    if output_root not in document_dir.parents:
        raise ValueError("Refusing output path outside the experiment root")
    document_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(document_dir / "source.txt", document.source_text + "\n")
    _save_optional_html(document_dir, source_html)
    metadata_payload = document.metadata()
    content = metadata_payload.get("content")
    if isinstance(content, dict):
        content["raw_html_saved"] = source_html is not None
    metadata = json.dumps(
        metadata_payload, ensure_ascii=False, indent=2, sort_keys=True
    )
    _atomic_write(document_dir / "metadata.json", metadata + "\n")
    return document_dir


def save_metadata_only(
    metadata: DetailMetadata,
    output_root: Path,
    *,
    skip_reason: str | None = None,
    source_html: str | None = None,
) -> Path:
    """Persist a non-ingestible detail record without creating source.txt."""
    if not metadata.external_id.isdigit():
        raise ValueError("Experimental external_id must contain only digits")
    output_root = output_root.resolve()
    document_dir = (output_root / f"LTV_{metadata.external_id}").resolve()
    if output_root not in document_dir.parents:
        raise ValueError("Refusing output path outside the experiment root")
    document_dir.mkdir(parents=True, exist_ok=True)
    _save_optional_html(document_dir, source_html)
    detail_payload = metadata.as_dict()
    content = detail_payload.get("content")
    if isinstance(content, dict):
        content["raw_html_saved"] = source_html is not None
    payload = {
        "raw_doc_code": f"LTV_{metadata.external_id}",
        "source_provider": "luatvietnam.vn",
        "experimental": True,
        "metadata_only": True,
        "skip_reason": skip_reason,
        **detail_payload,
    }
    _atomic_write(
        document_dir / "metadata.json",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return document_dir


def write_report(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write(path, payload + "\n")


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _save_optional_html(document_dir: Path, source_html: str | None) -> None:
    html_path = document_dir / "source.html"
    if source_html is None:
        html_path.unlink(missing_ok=True)
        return
    _atomic_write(html_path, source_html)
