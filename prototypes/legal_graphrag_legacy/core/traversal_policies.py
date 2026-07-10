TRAVERSAL_POLICIES = {
    "factual": {
        "relations": ["REGULATES", "DEFINES", "REQUIRES", "REFERS_TO"],
        "max_depth": 2,
        "follow_temporal": False,
    },
    "validity": {
        "relations": ["AMENDS", "REPLACES", "REPEALS"],
        "max_depth": 10,
        "follow_temporal": True,
        "priority": "latest",
        "stop_condition": "no_outgoing_temporal_edge",
    },
    "hierarchy": {
        "relations": ["GUIDES"],
        "max_depth": 3,
        "direction": "both",
        "priority": "legal_rank",
    },
    "comparison": {
        "relations": ["AMENDS", "REPLACES"],
        "max_depth": 10,
        "follow_temporal": True,
        "return_all_versions": True,
        "stop_condition": "no_outgoing_temporal_edge",
    },
    "definition": {
        "relations": ["DEFINES"],
        "max_depth": 1,
        "follow_temporal": False,
    },
}

STRUCTURAL_CONTEXT_POLICY = {
    "relations": ["CONTAINS"],
    "max_depth": 1,
    "direction": "up",
}

MANDATORY_RELATIONS = ["AMENDS", "REPLACES", "REPEALS"]

CONFIDENCE_THRESHOLD = 0.6

def resolve_policy(intents_with_scores: list[tuple[str, float]]) -> dict:
    valid = [i for i, score in intents_with_scores if score >= CONFIDENCE_THRESHOLD]

    if not valid:
        return {
            "relations": "ALL",
            "max_depth": 3,
            "follow_temporal": True,
            "mode": "fallback_low_confidence",
        }

    if len(valid) == 1:
        return {**TRAVERSAL_POLICIES[valid[0]], "mode": "single_intent"}

    merged_relations = set()
    for i in valid:
        merged_relations |= set(TRAVERSAL_POLICIES[i]["relations"])

    return {
        "relations": list(merged_relations),
        "max_depth": max(TRAVERSAL_POLICIES[i]["max_depth"] for i in valid),
        "follow_temporal": any(TRAVERSAL_POLICIES[i].get("follow_temporal") for i in valid),
        "mode": "sequential_multi_intent",
        "sub_intents": valid,
    }
