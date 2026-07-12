"""Build ontology-ready graph payloads from parsed hierarchy and accepted records."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.parser.models import ParsedDocument
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)


SEMANTIC_LABEL_MAP = {
    "Entity": "LegalSubject",
    "Concept": "LegalConcept",
    "Action": "LegalAction",
}
SEMANTIC_TYPES = {"LegalConcept", "LegalSubject", "LegalAction"}
CONTENT_STATUS_FALLBACK = {
    "ACTIVE": "ACTIVE",
    "NOT_YET_EFFECTIVE": "ACTIVE",
    "PARTIALLY_EFFECTIVE": "ACTIVE",
    "REPLACED": "REPEALED",
    "REPEALED": "REPEALED",
    "EXPIRED": "REPEALED",
}
KNOWN_SEMANTIC_IDS = {
    "vốn điều lệ": "von_dieu_le",
    "von dieu le": "von_dieu_le",
    "doanh nghiệp": "doanh_nghiep",
    "doanh nghiep": "doanh_nghiep",
    "công ty": "cong_ty",
    "cong ty": "cong_ty",
}


class PayloadBuildError(ValueError):
    """Raised when accepted extraction cannot be converted to graph payload."""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise PayloadBuildError(f"Missing required JSONL file: {path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if record.get("decision") != "accepted":
                raise PayloadBuildError(f"{path}:{line_no} is not an accepted decision record")
            records.append(record)
    return records


def load_entity_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise PayloadBuildError(f"Missing required entity index: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PayloadBuildError("entity_index.json must be an object keyed by extraction entity id")
    return {str(key): dict(value) for key, value in raw.items()}


def build_payload_from_paths(processed_doc_dir: Path) -> dict[str, Any]:
    hierarchy_path = processed_doc_dir / "hierarchy.json"
    if not hierarchy_path.exists():
        raise PayloadBuildError(f"Missing hierarchy.json: {hierarchy_path}")

    parsed = ParsedDocument.model_validate_json(hierarchy_path.read_text(encoding="utf-8"))
    accepted_records = load_jsonl(processed_doc_dir / "accepted.jsonl")
    entity_index = load_entity_index(processed_doc_dir / "entity_index.json")
    return build_graph_payload(parsed, accepted_records, entity_index, raw_doc_code=processed_doc_dir.name)


def build_graph_payload(
    parsed: ParsedDocument,
    accepted_records: list[Mapping[str, Any]],
    entity_index: Mapping[str, Mapping[str, Any]],
    *,
    raw_doc_code: str,
) -> dict[str, Any]:
    if not raw_doc_code:
        raise PayloadBuildError("raw_doc_code is required")

    nodes: dict[str, dict[str, Any]] = {}
    relations: dict[str, dict[str, Any]] = {}

    document_node = _document_node(parsed)
    _add_node(nodes, document_node)

    issuer_node = _issuer_node(parsed.document.issuer_name)
    _add_node(nodes, issuer_node)
    _add_relation(relations, document_node["id"], "ISSUED_BY", issuer_node["id"], {})

    structural_ids: dict[str, str] = {document_node["id"]: document_node["id"]}
    chapter_ids: dict[str, str] = {}
    content_status = CONTENT_STATUS_FALLBACK.get(parsed.document.legal_status, "ACTIVE")
    effective_from = str(parsed.document.effective_from)

    for article in parsed.articles:
        parent_id = document_node["id"]
        if article.chapter:
            chapter_id = f"{document_node['id']}_ch{_normalize_chapter_number(article.chapter)}"
            chapter_ids[article.chapter] = chapter_id
            if chapter_id not in nodes:
                _add_node(
                    nodes,
                    {
                        "type": "Chapter",
                        "id": chapter_id,
                        "number": str(article.chapter),
                        "title": article.chapter_title or f"Chương {article.chapter}",
                    },
                )
                _add_relation(relations, document_node["id"], "CONTAINS", chapter_id, {})
            parent_id = chapter_id

        article_id = f"{document_node['id']}_art{article.number}"
        structural_ids[article_id] = article_id
        _add_node(
            nodes,
            {
                "type": "Article",
                "id": article_id,
                "number": str(article.number),
                "title": article.title,
                "content_raw": article.content_raw,
                "effective_from": effective_from,
                "effective_to": _optional_str(parsed.document.effective_to),
                "legal_status": content_status,
            },
        )
        _add_relation(relations, parent_id, "CONTAINS", article_id, {})

        for clause in article.clauses:
            clause_id = f"{article_id}_cl{clause.number}"
            structural_ids[clause_id] = clause_id
            _add_node(
                nodes,
                {
                    "type": "Clause",
                    "id": clause_id,
                    "number": str(clause.number),
                    "content_raw": clause.content,
                    "effective_from": effective_from,
                    "effective_to": _optional_str(parsed.document.effective_to),
                    "legal_status": content_status,
                },
            )
            _add_relation(relations, article_id, "CONTAINS", clause_id, {})

            for point in clause.points:
                point_label = _normalize_point_label(point.label)
                point_id = f"{clause_id}_p{point_label}"
                structural_ids[point_id] = point_id
                _add_node(
                    nodes,
                    {
                        "type": "Point",
                        "id": point_id,
                        "label": point.label,
                        "content_raw": point.content,
                    },
                )
                _add_relation(relations, clause_id, "CONTAINS", point_id, {})

    for record in accepted_records:
        relation = record.get("relation") or {}
        head_id = _resolve_endpoint_id(relation.get("head"), structural_ids, entity_index)
        tail_id = _resolve_endpoint_id(relation.get("tail"), structural_ids, entity_index)

        _ensure_semantic_node(nodes, relation.get("head"), entity_index)
        _ensure_semantic_node(nodes, relation.get("tail"), entity_index)

        relation_type = relation.get("relation")
        properties = dict(relation.get("properties") or {})
        discriminator = relation_identity_discriminator(relation_type, properties)
        _add_relation(relations, head_id, relation_type, tail_id, properties, discriminator)

    return {
        "metadata": {
            "raw_doc_code": raw_doc_code,
            "graph_id": parsed.document.id,
        },
        "nodes": list(nodes.values()),
        "relations": list(relations.values()),
    }


def _document_node(parsed: ParsedDocument) -> dict[str, Any]:
    document = parsed.document
    required = {
        "id": document.id,
        "doc_type": document.doc_type,
        "number": document.number,
        "normative": document.normative,
        "legal_status": document.legal_status,
        "effective_from": document.effective_from,
        "issuer_name": document.issuer_name,
    }
    missing = [key for key, value in required.items() if value in (None, "")]
    if missing:
        raise PayloadBuildError(f"Document missing required field(s): {missing}")

    return {
        "type": "Document",
        "id": document.id,
        "title": document.title,
        "number": document.number,
        "doc_type": document.doc_type,
        "normative": document.normative,
        "legal_status": document.legal_status,
        "effective_from": str(document.effective_from),
        "effective_to": _optional_str(document.effective_to),
        "issuer_name": document.issuer_name,
        "issued_by": document.issued_by,
        "issued_date": _optional_str(document.issued_date),
    }


def _issuer_node(issuer_name: str | None) -> dict[str, Any]:
    if not issuer_name:
        raise PayloadBuildError("Document.issuer_name is required to build Issuer node")
    return {
        "type": "Issuer",
        "id": _slug(issuer_name),
        "name": issuer_name,
        "branch": _issuer_branch(issuer_name),
    }


def _issuer_branch(issuer_name: str) -> str:
    normalized = _strip_accents(issuer_name).lower()
    if "quoc hoi" in normalized or "uy ban thuong vu quoc hoi" in normalized:
        return "LEGISLATIVE"
    if "toa an" in normalized or "vien kiem sat" in normalized:
        return "JUDICIAL"
    if any(token in normalized for token in ("chinh phu", "bo ", "thu tuong", "uy ban nhan dan")):
        return "EXECUTIVE"
    return "OTHER"


def _ensure_semantic_node(
    nodes: dict[str, dict[str, Any]],
    extraction_id: Any,
    entity_index: Mapping[str, Mapping[str, Any]],
) -> None:
    extraction_key = str(extraction_id)
    if extraction_key not in entity_index:
        return
    source = dict(entity_index[extraction_key])
    node_type = SEMANTIC_LABEL_MAP.get(str(source.get("type")), str(source.get("type")))
    if node_type not in SEMANTIC_TYPES:
        return

    name = source.get("name") or source.get("label")
    node_id = source.get("id") or _semantic_id(name)
    node = {
        "type": node_type,
        "id": node_id,
        "name": name,
        "aliases": source.get("aliases") or [],
        "description": source.get("description"),
    }
    _add_node(nodes, node)


def _resolve_endpoint_id(
    raw_id: Any,
    article_ids: Mapping[str, str],
    entity_index: Mapping[str, Mapping[str, Any]],
) -> str:
    raw = str(raw_id)
    if raw in article_ids:
        return article_ids[raw]
    if raw in entity_index:
        source = entity_index[raw]
        name = source.get("name") or source.get("label") or raw
        return str(source.get("id") or _semantic_id(name))
    raise PayloadBuildError(f"Accepted relation references missing entity: {raw}")


def _add_node(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    node_id = str(node["id"])
    normalized_node = {key: value for key, value in node.items() if value is not None}
    existing = nodes.get(node_id)
    if existing is not None:
        if existing != normalized_node:
            raise PayloadBuildError(f"Duplicate node id with different payload: {node_id}")
        return
    nodes[node_id] = normalized_node


def _add_relation(
    relations: dict[str, dict[str, Any]],
    head_id: str,
    relation_type: str,
    tail_id: str,
    properties: dict[str, Any] | None,
    discriminator: str | None = None,
) -> None:
    props = dict(properties or {})
    relation_id = deterministic_relation_id(head_id, relation_type, tail_id, discriminator)
    props.setdefault("relation_id", relation_id)
    relation = {
        "id": relation_id,
        "head_id": head_id,
        "type": relation_type,
        "tail_id": tail_id,
        "properties": props,
    }
    identity = "|".join([head_id, relation_type, tail_id, discriminator or ""])
    relations[identity] = relation


def _semantic_id(label: Any) -> str:
    text = str(label or "")
    normalized = _strip_accents(text).lower().strip()
    return KNOWN_SEMANTIC_IDS.get(text.lower().strip()) or KNOWN_SEMANTIC_IDS.get(normalized) or _slug(text)


def _normalize_chapter_number(value: str) -> str:
    text = value.strip().upper()
    roman = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    if re.fullmatch(r"[IVXLC]+", text):
        total = 0
        prev = 0
        for char in reversed(text):
            current = roman[char]
            if current < prev:
                total -= current
            else:
                total += current
                prev = current
        return str(total)
    return _slug(value)


def _normalize_point_label(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "đ":
        return "dd"
    return _slug(normalized)


def _slug(value: Any) -> str:
    normalized = _strip_accents(str(value)).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_") or "unknown"


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "D")


def _optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
