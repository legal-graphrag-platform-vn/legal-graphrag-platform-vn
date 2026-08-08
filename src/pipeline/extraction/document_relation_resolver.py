"""Document-level relation resolver — Phase 2 của diagram extraction pipeline.

Nhận DiagramRelationCandidate từ diagram_parser, resolve raw_target thành
canonical Document ID qua DocumentRegistry, rồi build record dict cùng schema
với rule_records trong orchestrator.

Trách nhiệm của module này:
  - Resolve raw_target → canonical Document ID (qua DocumentRegistry).
  - Xác định head/tail dựa trên direction.
  - Build record dict với đầy đủ fields để đi qua _apply_decision_gate().
  - Đánh dấu unresolved target thành review, không rejected ngay.

Trách nhiệm KHÔNG thuộc module này:
  - Parse diagram JSON (→ diagram_parser).
  - Gọi validate_ontology / validate_record_relation (→ orchestrator gate).
  - Ghi bất kỳ artifact nào.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from src.pipeline.extraction.diagram_parser import DiagramRelationCandidate
from src.pipeline.extraction.structural_context import DocumentRegistry

logger = logging.getLogger(__name__)

DIAGRAM_RESOLVER_NAME = "document-diagram-resolver"
DIAGRAM_RESOLVER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ResolvedDiagramRelation:
    """Relation đã resolve canonical ID, sẵn sàng để validate và build record."""

    head_id: str
    relation_type: str
    tail_id: str
    source_category: str
    raw_target: str
    resolved: bool  # False nếu target không resolve được → review


@dataclass(frozen=True)
class UnresolvedDiagramRelation:
    """Target không resolve được qua DocumentRegistry."""

    raw_target: str
    source_category: str
    relation_type: str
    direction: str
    current_document_id: str


def resolve_diagram_relations(
    candidates: list[DiagramRelationCandidate],
    current_document_id: str,
    registry: DocumentRegistry,
) -> tuple[list[ResolvedDiagramRelation], list[UnresolvedDiagramRelation]]:
    """Resolve candidates thành (resolved, unresolved).

    Args:
        candidates: Output của diagram_parser.parse_diagram().
        current_document_id: Canonical ID của văn bản đang xử lý (ví dụ "ldn_2020").
        registry: DocumentRegistry đã load từ curated manifest.

    Returns:
        (resolved_list, unresolved_list)
    """
    resolved: list[ResolvedDiagramRelation] = []
    unresolved: list[UnresolvedDiagramRelation] = []

    for candidate in candidates:
        result = registry.resolve(candidate.raw_target, None)
        if result is None:
            logger.warning(
                "Diagram: không resolve được target '%s' (category='%s') — đưa vào review",
                candidate.raw_target,
                candidate.source_category,
            )
            unresolved.append(
                UnresolvedDiagramRelation(
                    raw_target=candidate.raw_target,
                    source_category=candidate.source_category,
                    relation_type=candidate.relation_type,
                    direction=candidate.direction,
                    current_document_id=current_document_id,
                )
            )
            continue

        canonical_id, _doc_type = result

        if candidate.direction == "CURRENT_TO_TARGET":
            head_id = current_document_id
            tail_id = canonical_id
        else:
            head_id = canonical_id
            tail_id = current_document_id

        # Bỏ qua self-loop (phòng trường hợp manifest trả về chính document)
        if head_id == tail_id:
            logger.warning(
                "Diagram: bỏ qua self-loop relation '%s' → '%s' (category='%s')",
                head_id,
                tail_id,
                candidate.source_category,
            )
            continue

        resolved.append(
            ResolvedDiagramRelation(
                head_id=head_id,
                relation_type=candidate.relation_type,
                tail_id=tail_id,
                source_category=candidate.source_category,
                raw_target=candidate.raw_target,
                resolved=True,
            )
        )

    return resolved, unresolved


def build_diagram_records(
    resolved: list[ResolvedDiagramRelation],
    unresolved: list[UnresolvedDiagramRelation],
    current_document_id: str,
) -> list[dict[str, Any]]:
    """Build record dicts với schema tương thích orchestrator cho diagram relations.

    Records resolved đi qua gate bình thường (schema_valid=True, ontology_valid
    được gate tự kiểm tra).
    Records unresolved được đánh dấu review_reason="unresolved_diagram_target".

    Args:
        resolved: List quan hệ đã resolve thành công.
        unresolved: List quan hệ không resolve được target.
        current_document_id: Canonical ID văn bản đang xử lý.

    Returns:
        List record dict sẵn sàng để append vào all_records trong orchestrator.
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []

    for rel in resolved:
        properties: dict[str, Any] = {
            "extraction_method": "DIAGRAM",
            "source_category": rel.source_category,
            "source_text": rel.raw_target,
            "created_at": now_iso,
            "confidence": 1.0,
            "resolver_name": DIAGRAM_RESOLVER_NAME,
            "resolver_version": DIAGRAM_RESOLVER_VERSION,
        }
        relation = {
            "head": rel.head_id,
            "relation": rel.relation_type,
            "tail": rel.tail_id,
            "evidence": f"{rel.source_category}: {rel.raw_target}",
            "properties": properties,
        }
        records.append(
            {
                "document_id": current_document_id,
                "article_number": None,  # document-level relation, không thuộc Article
                "extraction_method": "DIAGRAM",
                "raw_relation": relation,
                "relation": relation,
                "endpoint_resolution": {
                    "head": {
                        "status": "resolved",
                        "method": "diagram",
                        "canonical_id": rel.head_id,
                    },
                    "tail": {
                        "status": "resolved",
                        "method": "diagram",
                        "canonical_id": rel.tail_id,
                    },
                },
                "schema_valid": True,
                "schema_error": None,
                "ontology_valid": True,   # sẽ được gate verify lại
                "ontology_error": None,
                "consistency_valid": True,
                "consistency_error": None,
                "confidence": 1.0,
                "review_reason": None,
                "blocking": False,
            }
        )

    for unres in unresolved:
        # Không thể build head/tail chưa biết — placeholder head=current, tail=None
        # Gate sẽ reject vì ontology_valid=False
        properties = {
            "extraction_method": "DIAGRAM",
            "source_category": unres.source_category,
            "source_text": unres.raw_target,
            "created_at": now_iso,
            "confidence": 0.0,
            "resolver_name": DIAGRAM_RESOLVER_NAME,
            "resolver_version": DIAGRAM_RESOLVER_VERSION,
        }
        relation = {
            "head": current_document_id
            if unres.direction == "CURRENT_TO_TARGET"
            else f"UNRESOLVED:{unres.raw_target}",
            "relation": unres.relation_type,
            "tail": f"UNRESOLVED:{unres.raw_target}"
            if unres.direction == "CURRENT_TO_TARGET"
            else current_document_id,
            "evidence": f"{unres.source_category}: {unres.raw_target}",
            "properties": properties,
        }
        records.append(
            {
                "document_id": current_document_id,
                "article_number": None,
                "extraction_method": "DIAGRAM",
                "raw_relation": relation,
                "relation": relation,
                "endpoint_resolution": {
                    "head": {"status": "unresolved", "method": "diagram"},
                    "tail": {"status": "unresolved", "method": "diagram"},
                },
                "schema_valid": True,
                "schema_error": None,
                "ontology_valid": False,
                "ontology_error": f"Cannot resolve diagram target: {unres.raw_target!r}",
                "consistency_valid": False,
                "consistency_error": "Unresolved diagram target",
                "confidence": 0.0,
                "review_reason": "unresolved_diagram_target",
                "blocking": False,
            }
        )

    return records
