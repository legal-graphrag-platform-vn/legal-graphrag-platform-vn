"""Deterministic evidence sufficiency policy by retrieval intent."""

from __future__ import annotations

from dataclasses import dataclass

from src.retrieval.execution_contract import PlanExecutionStatus
from src.retrieval.models import IntentType, RetrievalContext
from src.retrieval.path_identity import build_topology_path_fingerprint


@dataclass(frozen=True)
class SufficiencyResult:
    sufficient: bool
    reason_code: str | None = None
    reason: str | None = None


class EvidenceSufficiencyPolicy:
    def evaluate(self, context: RetrievalContext) -> SufficiencyResult:
        if context.capability_status == "no_results" or not context.retrieved_units:
            return _insufficient("NO_RESULTS", "Không tìm thấy căn cứ pháp lý phù hợp.")

        if context.relation_goal is not None and not _has_relation_goal_path(context):
            return _insufficient(
                "NO_REFERENCE_EDGE",
                "Không tìm thấy quan hệ pháp lý được yêu cầu từ tham chiếu đã xác định.",
            )

        if context.intent in {IntentType.FACTUAL, IntentType.DEFINITION}:
            return self._evidence_required(context)
        if context.intent == IntentType.HIERARCHY:
            if not any(
                any(edge.relation_type == "CONTAINS" for edge in path.edges)
                for path in context.graph_paths
            ):
                return _insufficient(
                    "MISSING_HIERARCHY_PATH",
                    "Chưa có đường dẫn cấu trúc đã xác minh để trả lời.",
                )
            return self._evidence_required(context)
        if context.intent == IntentType.MULTI_HOP:
            execution = context.plan_execution
            if execution is None:
                return _insufficient(
                    "MULTI_HOP_REQUIREMENT_UNRESOLVED",
                    "Chưa xác định được yêu cầu đường dẫn nhiều bước đáng tin cậy.",
                )
            if execution.execution_status is not PlanExecutionStatus.SATISFIED:
                return _insufficient(
                    execution.reason_code.value,
                    execution.message
                    or "Query plan không tìm được đường dẫn graph đáng tin cậy.",
                )
            requirement = execution.derived_reasoning_requirement
            if requirement is None:
                return _insufficient(
                    "MULTI_HOP_REQUIREMENT_UNRESOLVED",
                    "Chưa xác định được yêu cầu đường dẫn nhiều bước đáng tin cậy.",
                )
            satisfied_fingerprints = set(execution.satisfied_path_fingerprints)
            unit_ids = {unit.id for unit in context.retrieved_units}
            for path in context.graph_paths:
                if build_topology_path_fingerprint(path) not in satisfied_fingerprints:
                    continue
                relation_types = tuple(edge.relation_type for edge in path.edges)
                if len(path.edges) < requirement.minimum_edges:
                    continue
                if any(
                    required not in relation_types
                    for required in requirement.required_relation_types
                ):
                    continue
                citable_ids = {
                    node.citable_unit_id
                    for node in path.nodes
                    if node.citable_unit_id is not None
                }
                if (
                    requirement.require_all_citable_intermediates
                    and not citable_ids.issubset(unit_ids)
                ):
                    continue
                return self._evidence_required(context)
            return _insufficient(
                "MISSING_MULTI_HOP_PATH",
                "Chưa có đường dẫn graph đủ để trả lời câu hỏi nhiều bước.",
            )
        if context.intent == IntentType.VALIDITY:
            query_date = context.temporal.resolved_from
            if query_date is None or context.temporal.resolved_to != query_date:
                return _insufficient(
                    "MISSING_TEMPORAL_POINT",
                    "Chưa xác định được thời điểm pháp lý cần kiểm tra.",
                )
            resolved_subject_ids = {
                reference.node_id for reference in context.resolved_references
            }
            if resolved_subject_ids:
                units_by_id = {unit.id: unit for unit in context.retrieved_units}
                if any(
                    subject_id not in units_by_id
                    or units_by_id[subject_id].effective_from is None
                    for subject_id in resolved_subject_ids
                ):
                    return _insufficient(
                        "MISSING_TEMPORAL_EVIDENCE",
                        "Tham chiếu đã xác định chưa có metadata thời gian đầy đủ.",
                    )
                return self._evidence_required(context)
            if not any(
                _is_valid_on(unit.effective_from, unit.effective_to, query_date)
                for unit in context.retrieved_units
            ):
                return _insufficient(
                    "MISSING_TEMPORAL_EVIDENCE",
                    "Chưa có metadata thời gian phù hợp cho thời điểm được hỏi.",
                )
            return self._evidence_required(context)
        if context.intent == IntentType.COMPARISON:
            families: dict[str, set[str]] = {}
            for unit in context.retrieved_units:
                if unit.version_family_id is not None:
                    families.setdefault(unit.version_family_id, set()).add(
                        unit.document_id
                    )
            family_verified = any(
                len(documents) >= 2 for documents in families.values()
            )
            path_verified = any(
                any(edge.relation_type in {"AMENDS", "REPLACES"} for edge in path.edges)
                for path in context.graph_paths
            )
            if not family_verified and not path_verified:
                return _insufficient(
                    "COMPARISON_RELATION_UNVERIFIED",
                    "Chưa xác minh được quan hệ giữa các phiên bản cần so sánh.",
                )
            return self._evidence_required(context)
        return _insufficient("UNSUPPORTED_INTENT", "Intent chưa được hỗ trợ.")

    @staticmethod
    def _evidence_required(context: RetrievalContext) -> SufficiencyResult:
        if not any(item.is_eligible for item in context.evidence):
            return _insufficient(
                "NO_SUFFICIENT_EVIDENCE",
                "Các kết quả truy xuất chưa đủ để tạo câu trả lời có căn cứ.",
            )
        return SufficiencyResult(sufficient=True)


def _is_valid_on(effective_from, effective_to, query_date) -> bool:
    return (
        effective_from is not None
        and effective_from <= query_date
        and (effective_to is None or query_date < effective_to)
    )


def _insufficient(code: str, reason: str) -> SufficiencyResult:
    return SufficiencyResult(sufficient=False, reason_code=code, reason=reason)


def _has_relation_goal_path(context: RetrievalContext) -> bool:
    assert context.relation_goal is not None
    anchor_ids = {reference.node_id for reference in context.resolved_references}
    return any(
        any(
            edge.relation_type == context.relation_goal.value
            and edge.source_id in anchor_ids
            for edge in path.edges
        )
        for path in context.graph_paths
    )
