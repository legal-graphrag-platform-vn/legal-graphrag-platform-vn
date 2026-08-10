"""Conservative deterministic relation-goal detection for retrieval v1."""

from __future__ import annotations

import re

from src.retrieval.resolved_reference import RelationGoal


_REFERS_TO = re.compile(
    r"(?:dẫn\s+chiếu|tham\s+chiếu|viện\s+dẫn|quy\s+định\s+tại\s+"
    r"(?:điều|khoản|điểm|văn\s+bản)\s+nào)",
    re.IGNORECASE,
)


def detect_relation_goal(message: str) -> RelationGoal | None:
    """Return only an explicitly stated relation goal; never infer one."""
    if _REFERS_TO.search(message):
        return RelationGoal.REFERS_TO
    return None
