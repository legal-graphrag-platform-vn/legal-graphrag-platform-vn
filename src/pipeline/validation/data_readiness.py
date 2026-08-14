"""Canonical metadata readiness checks for curated graph-construction inputs."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.config import settings
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

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest = load_curated_manifest(manifest_path or DEFAULT_MANIFEST_PATH)
    manifest_entry = manifest.get(raw_doc_code)
    if manifest_entry is None:
        manifest_entry = {
            "raw_doc_code": raw_doc_code,
            "graph_id": metadata.get("candidate_graph_id") or metadata.get("graph_id") or raw_doc_code.lower(),
            "number": metadata.get("number"),
            "doc_type": metadata.get("doc_type") or "Law",
            "required": False,
            "gold_annotation": False,
        }
    errors.extend(_manifest_identity_errors(metadata, raw_doc_code, manifest_entry))
    try:
        normalized = normalize_metadata(
            metadata,
            raw_doc_code=raw_doc_code,
            manifest_entry=manifest_entry,
            raw_root=raw_root,
        )
    except ValueError as exc:
        errors.append(str(exc))
        return DataReadinessResult(raw_doc_code, {}, tuple(errors))
    errors.extend(_metadata_errors(normalized, raw_doc_code))
    return DataReadinessResult(raw_doc_code, normalized, tuple(errors))


def normalize_metadata(
    metadata: Mapping[str, Any],
    *,
    raw_doc_code: str,
    manifest_entry: Mapping[str, Any],
    raw_root: Path | None = None,
) -> dict[str, Any]:
    metadata_dict = dict(metadata)
    base_root = raw_root or settings.data_raw_dir
    props_path = (base_root / raw_doc_code) / "properties.json"
    if props_path.exists():
        try:
            props = json.loads(props_path.read_text(encoding="utf-8"))
            if isinstance(props, dict):
                props_mapping = {
                    "sector": props.get("sector"),
                    "field": props.get("field"),
                    "signer_title": props.get("signer_title"),
                    "signer_name": props.get("signer_name"),
                    "issuer_name": props.get("issuing_authority"),
                    "status": props.get("status"),
                }
                eff = _parse_iso_date(props.get("effective_date"))
                if eff:
                    props_mapping["effective_from"] = eff
                iss = _parse_iso_date(props.get("issued_date"))
                if iss:
                    props_mapping["issued_date"] = iss
                exp = _parse_iso_date(props.get("expiry_date"))
                if exp:
                    props_mapping["effective_to"] = exp
                for k, v in props_mapping.items():
                    if v not in (None, "", "Chưa phân loại") or k not in metadata_dict:
                        metadata_dict.setdefault(k, v)
        except Exception:
            pass

    # 1. Trích xuất và fallback tên cơ quan ban hành
    issuer_name = metadata_dict.get("issuer_name") or metadata_dict.get("issued_by") or "Cơ quan nhà nước"

    # 2. Trích xuất doc_type và ngày hiệu lực (fallback ngày ban hành hoặc 1970-01-01)
    doc_type = metadata_dict.get("doc_type") or metadata_dict.get("type") or manifest_entry.get("doc_type")
    raw_issued = metadata_dict.get("issued_date")
    issued_date = _parse_iso_date(raw_issued) or "1970-01-01"
    raw_effective = metadata_dict.get("effective_from")
    effective_from = _parse_iso_date(raw_effective) or issued_date
    raw_effective_to = metadata_dict.get("effective_to")
    effective_to = _parse_iso_date(raw_effective_to)
    source_url = metadata_dict.get("source_url") or f"https://luatvietnam.vn/{raw_doc_code}"

    # 3. Gom metadata đã được chuẩn hóa
    normalized = {
        **metadata_dict,
        "raw_doc_code": raw_doc_code,
        "graph_id": manifest_entry.get("graph_id"),
        "number": metadata_dict.get("number") or manifest_entry.get("number"),
        "doc_type": doc_type,
        "normative": bool(metadata_dict.get("normative", True)),
        "issuer_name": issuer_name,
        "legal_status": metadata_dict.get("legal_status") or legal_status_from_raw(metadata_dict.get("status")),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "issued_date": issued_date,
        "source_url": source_url,
    }
    return normalized


def legal_status_from_raw(raw_status: Any) -> str:
    # 1. Chuẩn hóa chuỗi trạng thái không dấu
    normalized = _ascii(str(raw_status or "")).lower().strip()
    mapping = {
        "active": "ACTIVE",
        "con hieu luc": "ACTIVE",
        "chua co hieu luc": "NOT_YET_EFFECTIVE",
        "het hieu luc mot phan": "PARTIALLY_EFFECTIVE",
        "het hieu luc toan bo": "EXPIRED",
        "bi thay the": "REPLACED",
        "bi bai bo": "REPEALED",
        "da biet": "ACTIVE",
        "": "ACTIVE",
    }
    # 2. Khớp với mapping enum hợp lệ hoặc raise ValueError nếu trạng thái không xác định
    if normalized not in mapping:
        raise ValueError(f"Unknown legal status: {raw_status!r}; refusing to default to ACTIVE")
    return mapping[normalized]


def _manifest_identity_errors(
    metadata: Mapping[str, Any], raw_doc_code: str, manifest_entry: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    actual_raw_code = metadata.get("raw_doc_code") or metadata.get("doc_id")
    comparisons = {
        "raw_doc_code": (actual_raw_code, raw_doc_code),
        "graph_id": (metadata.get("graph_id"), manifest_entry.get("graph_id")),
        "number": (metadata.get("number"), manifest_entry.get("number")),
        "doc_type": (metadata.get("doc_type") or metadata.get("type"), manifest_entry.get("doc_type")),
    }
    for field, (actual, expected) in comparisons.items():
        if actual not in (None, "") and expected not in (None, "") and actual != expected:
            errors.append(f"Metadata mismatch for {field}: metadata={actual!r}, manifest={expected!r}")
    return errors


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
        "legal_status",
        "effective_from",
        "issuer_name",
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
    for field in ("effective_from", "effective_to", "issued_date"):
        value = metadata.get(field)
        if value not in (None, ""):
            try:
                date.fromisoformat(str(value))
            except ValueError:
                errors.append(f"{field} must use ISO YYYY-MM-DD: {value}")
    return errors


def _parse_iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    val_str = str(value).split("T")[0].strip()
    try:
        return date.fromisoformat(val_str).isoformat()
    except ValueError:
        pass
    parts = val_str.split("/")
    if len(parts) == 3:
        try:
            return date(int(parts[2]), int(parts[1]), int(parts[0])).isoformat()
        except ValueError:
            pass
    return str(value)


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "D")




