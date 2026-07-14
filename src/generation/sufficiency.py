"""Deterministic evidence sufficiency policy by retrieval intent."""

from __future__ import annotations

from dataclasses import dataclass

from src.retrieval.models import IntentType, RetrievalContext


@dataclass(frozen=True)
class SufficiencyResult:
    sufficient: bool
    reason_code: str | None = None
    reason: str | None = None


class EvidenceSufficiencyPolicy:
    def evaluate(self, context: RetrievalContext) -> SufficiencyResult:
        if context.capability_status == "no_results" or not context.retrieved_units:
            return _insufficient("NO_RESULTS", "Không tìm thấy căn cứ pháp lý phù hợp.")

        if context.intent in {IntentType.FACTUAL, IntentType.DEFINITION}:
            return self._evidence_required(context)
        if context.intent == IntentType.HIERARCHY:
            if not any("CONTAINS" in path.relations for path in context.graph_paths):
                return _insufficient(
                    "MISSING_HIERARCHY_PATH",
                    "Chưa có đường dẫn cấu trúc đã xác minh để trả lời.",
                )
            return self._evidence_required(context)
        if context.intent == IntentType.MULTI_HOP:
            unit_ids = {unit.id for unit in context.retrieved_units}
            valid_path = any(
                path.relations
                and path.nodes
                and path.nodes[0] in unit_ids
                and path.nodes[-1] in unit_ids
                for path in context.graph_paths
            )
            if not valid_path:
                return _insufficient(
                    "MISSING_MULTI_HOP_PATH",
                    "Chưa có đường dẫn graph đủ để trả lời câu hỏi nhiều bước.",
                )
            return self._evidence_required(context)
        if context.intent == IntentType.VALIDITY:
            query_date = context.temporal.resolved_from
            if query_date is None or context.temporal.resolved_to != query_date:
                return _insufficient(
                    "MISSING_TEMPORAL_POINT",
                    "Chưa xác định được thời điểm pháp lý cần kiểm tra.",
                )
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
            version_keys = {
                (unit.version_family_id, unit.document_id)
                for unit in context.retrieved_units
            }
            if len(version_keys) < 2:
                return _insufficient(
                    "MISSING_COMPARISON_VERSIONS",
                    "Chưa có ít nhất hai phiên bản để so sánh.",
                )
            return self._evidence_required(context)
        return _insufficient("UNSUPPORTED_INTENT", "Intent chưa được hỗ trợ.")

    @staticmethod
    def _evidence_required(context: RetrievalContext) -> SufficiencyResult:
        if not any(item.is_sufficient for item in context.evidence):
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
