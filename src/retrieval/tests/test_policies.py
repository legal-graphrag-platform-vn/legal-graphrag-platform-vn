import pytest

from src.retrieval.models import IntentType
from src.retrieval.retriever.policies import TRAVERSAL_POLICIES, policy_for
from src.shared.ontology.contract import RELATION_ENUM


def test_policy_registry_covers_six_canonical_intents() -> None:
    assert set(TRAVERSAL_POLICIES) == set(IntentType)


@pytest.mark.parametrize("intent", list(IntentType))
def test_traversal_policies_only_use_canonical_relations(intent: IntentType) -> None:
    assert set(policy_for(intent).relations) <= set(RELATION_ENUM)


def test_factual_and_hierarchy_policies_match_retrieval_contract() -> None:
    assert policy_for(IntentType.FACTUAL).relations == (
        "REGULATES",
        "DEFINES",
        "REQUIRES",
        "REFERS_TO",
    )
    assert policy_for(IntentType.HIERARCHY).relations == ("GUIDES", "CONTAINS")
