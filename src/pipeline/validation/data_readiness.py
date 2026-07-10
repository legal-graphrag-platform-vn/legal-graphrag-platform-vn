"""Canonical metadata readiness checks for curated graph-construction inputs."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from src.shared.ontology.contract import DOCUMENT_LEGAL_STATUSES, DOCUMENT_TYPES, ISSUER_BRANCHES


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "configs" / "corpus" / "curated_v1.json"
GRAPH_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class DataReadinessResult:
    raw_doc_code: str
    normalized_metadata: dict[str, Any]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def load_curated_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    documents = raw.get("documents")
    if not isinstance(documents, list):
        raise ValueError(f"Curated manifest must contain a documents list: {path}")
    entries = {str(item["raw_doc_code"]): dict(item) for item in documents}
    if len(entries) != len(documents):
        raise ValueError(f"Curated manifest contains duplicate raw_doc_code values: {path}")
    return entries


def validate_document_readiness(
    raw_doc_code: str,
    raw_root: Path,
    *,
    manifest_path: Path | None = None,
) -> DataReadinessResult:
    document_dir = raw_root / raw_doc_code
    source_path = document_dir / "source.txt"
    metadata_path = document_dir / "metadata.json"
    errors: list[str] = []

    if not source_path.exists():
        errors.append(f"Missing source.txt: {source_path}")
    if not metadata_path.exists():
        errors.append(f"Missing metadata.json: {metadata_path}")
        return DataReadinessResult(raw_doc_code, {}, tuple(errors))

    manifest = load_curated_manifest(manifest_path or DEFAULT_MANIFEST_PATH)
    manifest_entry = manifest.get(raw_doc_code)
    if manifest_entry is None:
        errors.append(f"raw_doc_code is not in curated manifest: {raw_doc_code}")
        return DataReadinessResult(raw_doc_code, {}, tuple(errors))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    normalized = normalize_metadata(metadata, raw_doc_code=raw_doc_code, manifest_entry=manifest_entry)
    errors.extend(_metadata_errors(normalized, raw_doc_code))
    return DataReadinessResult(raw_doc_code, normalized, tuple(errors))


def normalize_metadata(
    metadata: Mapping[str, Any],
    *,
    raw_doc_code: str,
    manifest_entry: Mapping[str, Any],
) -> dict[str, Any]:
    issuer_name = metadata.get("issuer_name") or metadata.get("issued_by")
    doc_type = metadata.get("doc_type") or metadata.get("type") or manifest_entry.get("doc_type")
    normalized = {
        **dict(metadata),
        "raw_doc_code": raw_doc_code,
        "graph_id": manifest_entry.get("graph_id"),
        "number": metadata.get("number") or manifest_entry.get("number"),
        "doc_type": doc_type,
        "normative": bool(metadata.get("normative", True)),
        "issuer_name": issuer_name,
        "issuer_branch": metadata.get("issuer_branch") or issuer_branch(issuer_name),
        "legal_status": metadata.get("legal_status") or legal_status_from_raw(metadata.get("status")),
    }
    return normalized


def legal_status_from_raw(raw_status: Any) -> str:
    normalized = _ascii(str(raw_status or "active")).lower().strip()
    mapping = {
        "active": "ACTIVE",
        "con hieu luc": "ACTIVE",
        "chua co hieu luc": "NOT_YET_EFFECTIVE",
        "het hieu luc mot phan": "PARTIALLY_EFFECTIVE",
        "het hieu luc toan bo": "EXPIRED",
        "bi thay the": "REPLACED",
        "bi bai bo": "REPEALED",
    }
    return mapping.get(normalized, "ACTIVE")


def issuer_branch(issuer_name: Any) -> str:
    normalized = _ascii(str(issuer_name or "")).lower()
    if "quoc hoi" in normalized or "uy ban thuong vu quoc hoi" in normalized:
        return "LEGISLATIVE"
    if "toa an" in normalized or "vien kiem sat" in normalized:
        return "JUDICIAL"
    if any(token in normalized for token in ("chinh phu", "bo ", "thu tuong", "uy ban nhan dan")):
        return "EXECUTIVE"
    return "OTHER"


def _metadata_errors(metadata: Mapping[str, Any], raw_doc_code: str) -> list[str]:
    errors: list[str] = []
    required = (
        "raw_doc_code",
        "graph_id",
        "title",
        "number",
        "doc_type",
        "normative",
        "legal_status",
        "effective_from",
        "issuer_name",
        "issuer_branch",
        "source_url",
    )
    for field in required:
        if metadata.get(field) in (None, ""):
            errors.append(f"Metadata requires field: {field}")

    if metadata.get("raw_doc_code") != raw_doc_code:
        errors.append("metadata.raw_doc_code must match the filesystem folder")
    graph_id = str(metadata.get("graph_id") or "")
    if not GRAPH_ID_PATTERN.fullmatch(graph_id):
        errors.append(f"graph_id must be canonical snake-case: {graph_id}")
    if metadata.get("doc_type") not in DOCUMENT_TYPES:
        errors.append(f"Unsupported doc_type: {metadata.get('doc_type')}")
    if metadata.get("legal_status") not in DOCUMENT_LEGAL_STATUSES:
        errors.append(f"Unsupported legal_status: {metadata.get('legal_status')}")
    if metadata.get("issuer_branch") not in ISSUER_BRANCHES:
        errors.append(f"Unsupported issuer_branch: {metadata.get('issuer_branch')}")
    for field in ("effective_from", "effective_to", "issued_date"):
        value = metadata.get(field)
        if value not in (None, ""):
            try:
                date.fromisoformat(str(value))
            except ValueError:
                errors.append(f"{field} must use ISO YYYY-MM-DD: {value}")
    return errors


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "D")
