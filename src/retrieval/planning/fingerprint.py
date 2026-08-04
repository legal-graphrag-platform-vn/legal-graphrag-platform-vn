"""Deterministic identity for validated unlinked semantic plans."""

import hashlib

from src.retrieval.planning.models import UnlinkedSemanticPlan


def build_unlinked_plan_fingerprint(plan: UnlinkedSemanticPlan) -> str:
    canonical = plan.model_dump_json(exclude_none=True)
    return "unlinked_plan_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
