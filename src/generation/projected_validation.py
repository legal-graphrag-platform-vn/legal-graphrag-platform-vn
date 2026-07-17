"""Post-projection evidence sufficiency checks."""

from __future__ import annotations

from src.generation.evidence_compaction import CompactionPlan
from src.generation.models import ProjectedAnswerContext
from src.generation.sufficiency import SufficiencyResult
from src.retrieval.models import IntentType


class ProjectedContextValidator:
    def evaluate(
        self,
        projected: ProjectedAnswerContext,
        plan: CompactionPlan,
    ) -> SufficiencyResult:
        selected_ids = set(projected.selected_unit_ids)
        selected_path_ids = {path.path_id for path in projected.paths}
        admitted = {
            bundle.bundle_id: bundle
            for bundle_set in plan.required_bundle_sets
            for bundle in bundle_set
            if bundle.bundle_id in projected.admitted_bundle_ids
        }
        if set(projected.admitted_bundle_ids) != set(admitted):
            return _insufficient("Projected context contains an unknown bundle")
        for bundle in admitted.values():
            if not set(bundle.unit_ids).issubset(selected_ids):
                return _insufficient("Projected context lost required legal evidence")
            if not set(bundle.path_ids).issubset(selected_path_ids):
                return _insufficient("Projected context lost a required graph path")

        intent = IntentType(projected.intent)
        if intent in {IntentType.FACTUAL, IntentType.DEFINITION}:
            if not selected_ids:
                return _insufficient("Projected context has no direct evidence")
        elif intent == IntentType.HIERARCHY:
            if not any(
                any(edge.relation_type == "CONTAINS" for edge in path.edges)
                for path in projected.paths
            ):
                return _insufficient("Projected hierarchy path is incomplete")
        elif intent == IntentType.MULTI_HOP:
            if not projected.paths or not plan.required_bundle_sets:
                return _insufficient("Projected graph path is incomplete")
        elif intent == IntentType.VALIDITY:
            if projected.resolved_from is None:
                return _insufficient("Projected context has no temporal point")
            evidence_by_id = {item.unit_id: item for item in projected.evidence}
            temporal_subjects = {
                subject_id
                for bundle in admitted.values()
                for subject_id in bundle.temporal_subject_ids
            }
            if not temporal_subjects or any(
                subject_id not in evidence_by_id
                or evidence_by_id[subject_id].effective_from is None
                for subject_id in temporal_subjects
            ):
                return _insufficient("Projected temporal evidence is incomplete")
        elif intent == IntentType.COMPARISON:
            version_keys = {
                key for bundle in admitted.values() for key in bundle.version_keys
            }
            if len(version_keys) < 2:
                return _insufficient("Projected comparison versions are incomplete")
        return SufficiencyResult(sufficient=True)


def _insufficient(reason: str) -> SufficiencyResult:
    return SufficiencyResult(
        sufficient=False,
        reason_code="PROJECTED_EVIDENCE_INSUFFICIENT",
        reason=reason,
    )
