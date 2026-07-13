"""Canonical graph traversal policies keyed by the six retrieval intents."""

from dataclasses import dataclass
from typing import Literal

from src.retrieval.models import IntentType


@dataclass(frozen=True, slots=True)
class TraversalPolicy:
    relations: tuple[str, ...]
    max_depth: int
    direction: Literal["outgoing", "incoming", "both"] = "outgoing"


TRAVERSAL_POLICIES: dict[IntentType, TraversalPolicy] = {
    IntentType.FACTUAL: TraversalPolicy(
        ("REGULATES", "DEFINES", "REQUIRES", "REFERS_TO"), 2, "outgoing"
    ),
    IntentType.VALIDITY: TraversalPolicy(("AMENDS", "REPLACES", "REPEALS"), 3, "both"),
    IntentType.HIERARCHY: TraversalPolicy(("GUIDES", "CONTAINS"), 3, "both"),
    IntentType.COMPARISON: TraversalPolicy(("AMENDS", "REPLACES"), 5, "both"),
    IntentType.DEFINITION: TraversalPolicy(("DEFINES",), 1, "outgoing"),
    IntentType.MULTI_HOP: TraversalPolicy(
        (
            "ISSUED_BY",
            "CONTAINS",
            "GUIDES",
            "REFERS_TO",
            "AMENDS",
            "REPEALS",
            "REPLACES",
            "DEFINES",
            "REGULATES",
            "REQUIRES",
        ),
        3,
        "both",
    ),
}


def policy_for(intent: IntentType) -> TraversalPolicy:
    return TRAVERSAL_POLICIES[intent]
