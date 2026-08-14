"""Build ontology-ready graph payloads from parsed hierarchy and accepted records."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from src.pipeline.parser.models import ParsedDocument
from src.shared.ontology.contract import NODE_OPTIONAL_FIELDS
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)
from src.shared.ontology.hierarchy import (
    chapter_id,
    normalize_chapter_number,
    normalize_part_number,
    normalize_section_number,
    normalize_subsection_number,
    part_id,
    section_id,
    subsection_id,
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
CORPUS_RELATION_MATERIALIZATION_ROUTE = "CORPUS_RELATION_RECONCILIATION"


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
                raise PayloadBuildError(
                    f"{path}:{line_no} is not an accepted decision record"
                )
            records.append(record)
    return records


def load_entity_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise PayloadBuildError(f"Missing required entity index: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PayloadBuildError(
            "entity_index.json must be an object keyed by extraction entity id"
        )
    return {str(key): dict(value) for key, value in raw.items()}


def build_payload_from_paths(processed_doc_dir: Path) -> dict[str, Any]:
    hierarchy_path = processed_doc_dir / "hierarchy.json"
    if not hierarchy_path.exists():
        raise PayloadBuildError(f"Missing hierarchy.json: {hierarchy_path}")

    parsed = ParsedDocument.model_validate_json(
        hierarchy_path.read_text(encoding="utf-8")
    )
    accepted_records = load_jsonl(processed_doc_dir / "accepted.jsonl")
    entity_index = load_entity_index(processed_doc_dir / "entity_index.json")
    return build_graph_payload(
        parsed, accepted_records, entity_index, raw_doc_code=processed_doc_dir.name
    )


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
    deferred_relation_count = sum(
        1
        for record in accepted_records
        if record.get("materialization_route") == CORPUS_RELATION_MATERIALIZATION_ROUTE
    )

    document_node = _document_node(parsed)
    _add_node(nodes, document_node)

    issuer_node = _issuer_node(parsed.document.issuer_name)
    _add_node(nodes, issuer_node)
    _add_relation(relations, document_node["id"], "ISSUED_BY", issuer_node["id"], {})

    structural_ids: dict[str, str] = {document_node["id"]: document_node["id"]}
    parts_by_key = {normalize_part_number(part.number): part for part in parsed.parts}
    sections_by_key = {
        (
            normalize_part_number(section.part) if section.part else None,
            normalize_chapter_number(section.chapter),
            normalize_section_number(section.number),
        ): section
        for section in parsed.sections
    }
    subsections_by_key = {
        (
            normalize_part_number(subsection.part) if subsection.part else None,
            normalize_chapter_number(subsection.chapter),
            normalize_section_number(subsection.section),
            normalize_subsection_number(subsection.number),
        ): subsection
        for subsection in parsed.subsections
    }
    content_status = CONTENT_STATUS_FALLBACK.get(parsed.document.legal_status, "ACTIVE")
    effective_from = str(parsed.document.effective_from)

    for article in parsed.articles:
        parent_id = document_node["id"]
        normalized_part = None
        if article.part:
            normalized_part = normalize_part_number(article.part)
            part = parts_by_key.get(normalized_part)
            if part is None:
                raise PayloadBuildError(
                    f"Article {article.number} references missing Part {article.part}"
                )
            part_node_id = part_id(document_node["id"], article.part)
            structural_ids[part_node_id] = part_node_id
            if part_node_id not in nodes:
                _add_node(
                    nodes,
                    {
                        "type": "Part",
                        "id": part_node_id,
                        "number": str(part.number),
                        "title": part.title,
                    },
                )
                _add_relation(
                    relations, document_node["id"], "CONTAINS", part_node_id, {}
                )
            parent_id = part_node_id

        if article.chapter:
            chapter_node_id = chapter_id(document_node["id"], article.chapter)
            structural_ids[chapter_node_id] = chapter_node_id
            if chapter_node_id not in nodes:
                _add_node(
                    nodes,
                    {
                        "type": "Chapter",
                        "id": chapter_node_id,
                        "number": str(article.chapter),
                        "title": article.chapter_title or f"Chương {article.chapter}",
                    },
                )
                _add_relation(relations, parent_id, "CONTAINS", chapter_node_id, {})
            parent_id = chapter_node_id
            if article.section:
                section_key = (
                    normalized_part,
                    normalize_chapter_number(article.chapter),
                    normalize_section_number(article.section),
                )
                section = sections_by_key.get(section_key)
                if section is None:
                    raise PayloadBuildError(
                        f"Article {article.number} references missing Section "
                        f"{article.section} in Chapter {article.chapter}"
                    )
                section_node_id = section_id(
                    document_node["id"], article.chapter, article.section
                )
                structural_ids[section_node_id] = section_node_id
                if section_node_id not in nodes:
                    _add_node(
                        nodes,
                        {
                            "type": "Section",
                            "id": section_node_id,
                            "number": str(section.number),
                            "title": section.title,
                        },
                    )
                    _add_relation(
                        relations, chapter_node_id, "CONTAINS", section_node_id, {}
                    )
                parent_id = section_node_id
                if article.subsection:
                    subsection_key = (
                        *section_key,
                        normalize_subsection_number(article.subsection),
                    )
                    subsection = subsections_by_key.get(subsection_key)
                    if subsection is None:
                        raise PayloadBuildError(
                            f"Article {article.number} references missing Subsection "
                            f"{article.subsection} in Section {article.section}"
                        )
                    subsection_node_id = subsection_id(
                        document_node["id"],
                        article.chapter,
                        article.section,
                        article.subsection,
                    )
                    structural_ids[subsection_node_id] = subsection_node_id
                    if subsection_node_id not in nodes:
                        _add_node(
                            nodes,
                            {
                                "type": "Subsection",
                                "id": subsection_node_id,
                                "number": str(subsection.number),
                                "title": subsection.title,
                            },
                        )
                        _add_relation(
                            relations,
                            section_node_id,
                            "CONTAINS",
                            subsection_node_id,
                            {},
                        )
                    parent_id = subsection_node_id

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
                        "effective_from": effective_from,
                        "effective_to": _optional_str(parsed.document.effective_to),
                        "legal_status": content_status,
                    },
                )
                _add_relation(relations, clause_id, "CONTAINS", point_id, {})

    for record in accepted_records:
        if record.get("materialization_route") == CORPUS_RELATION_MATERIALIZATION_ROUTE:
            continue
        relation = record.get("relation") or {}
        head_id = _resolve_endpoint_id(
            relation.get("head"), structural_ids, entity_index
        )
        tail_id = _resolve_endpoint_id(
            relation.get("tail"), structural_ids, entity_index
        )

        _ensure_semantic_node(nodes, relation.get("head"), entity_index)
        _ensure_semantic_node(nodes, relation.get("tail"), entity_index)

        relation_type = relation.get("relation")
        properties = dict(relation.get("properties") or {})
        discriminator = relation_identity_discriminator(relation_type, properties)
        _add_relation(
            relations, head_id, relation_type, tail_id, properties, discriminator
        )

    return {
        "metadata": {
            "raw_doc_code": raw_doc_code,
            "graph_id": parsed.document.id,
            "deferred_relation_count": deferred_relation_count,
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
        "legal_status": document.legal_status,
        "effective_from": str(document.effective_from),
        "effective_to": _optional_str(document.effective_to),
        "issuer_name": document.issuer_name,
        "issued_date": _optional_str(document.issued_date),
        "source_url": _optional_str(document.source_url),
        "sector": _optional_str(document.sector),
        "field": _optional_str(document.field),
        "signer_title": _optional_str(document.signer_title),
        "signer_name": _optional_str(document.signer_name),
    }


def _issuer_node(issuer_name: str | None) -> dict[str, Any]:
    if not issuer_name:
        raise PayloadBuildError("Document.issuer_name is required to build Issuer node")
    return {
        "type": "Issuer",
        "id": _slug(issuer_name),
        "name": issuer_name,
    }


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
    node_type = str(node.get("type"))
    optional_fields = NODE_OPTIONAL_FIELDS.get(node_type, [])
    normalized_node = dict(node)
    for field in optional_fields:
        if field not in normalized_node:
            normalized_node[field] = None
    existing = nodes.get(node_id)
    if existing is not None:
        if existing != normalized_node:
            if (
                existing.get("type") == "Issuer"
                or normalized_node.get("type") == "Issuer"
            ):
                return
            raise PayloadBuildError(
                f"Duplicate node id with different payload: {node_id}"
            )
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
    relation_id = deterministic_relation_id(
        head_id, relation_type, tail_id, discriminator
    )
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
    return (
        KNOWN_SEMANTIC_IDS.get(text.lower().strip())
        or KNOWN_SEMANTIC_IDS.get(normalized)
        or _slug(text)
    )


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
    return (
        "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
        .replace("đ", "d")
        .replace("Đ", "D")
    )


def _optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
