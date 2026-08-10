from datetime import date

import pytest

from src.retrieval.config import RetrievalConfig
from src.retrieval.errors import (
    IntentAnalysisError,
    RetrievalRequestError,
    TemporalRoutingError,
)
from src.retrieval.models import (
    IntentType,
    RetrievalDecisionReasonCode,
    RetrievalFilters,
    RetrievalRequest,
    TemporalSource,
)
from src.retrieval.routing.router import IntentRouter
from src.retrieval.resolved_reference import RelationGoal


class FixedClock:
    def today(self) -> date:
        return date(2026, 7, 13)


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Điều kiện thành lập doanh nghiệp", IntentType.FACTUAL),
        ("Vốn điều lệ là gì?", IntentType.DEFINITION),
        ("Văn bản nào hướng dẫn luật này?", IntentType.HIERARCHY),
        ("Quy định này còn hiệu lực không?", IntentType.VALIDITY),
        ("So sánh quy định trong năm 2020", IntentType.COMPARISON),
        ("Thủ tục qua nhiều văn bản ra sao?", IntentType.MULTI_HOP),
    ],
)
def test_six_intents_route_explicitly(query: str, intent: IntentType) -> None:
    decision = (
        IntentRouter(RetrievalConfig(), clock=FixedClock())
        .route(RetrievalRequest(query=query))
        .decision
    )
    assert decision.intent is intent


class FakeClassifier:
    def __init__(self, intent=None, error=None):
        self._intent = intent
        self._error = error
        self.calls: list[str] = []

    def classify(self, query: str) -> IntentType:
        self.calls.append(query)
        if self._error is not None:
            raise self._error
        assert self._intent is not None
        return self._intent


def test_high_confidence_rule_bypasses_classifier() -> None:
    classifier = FakeClassifier(IntentType.FACTUAL)
    result = IntentRouter(
        RetrievalConfig(), classifier=classifier, clock=FixedClock()
    ).route(RetrievalRequest(query="Vốn điều lệ là gì?"))

    assert result.decision.intent is IntentType.DEFINITION
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.DEFINITION_EXPLICIT
    )
    assert classifier.calls == []


def test_low_confidence_rule_defers_to_classifier() -> None:
    classifier = FakeClassifier(IntentType.FACTUAL)
    result = IntentRouter(
        RetrievalConfig(), classifier=classifier, clock=FixedClock()
    ).route(RetrievalRequest(query="Thủ tục qua nhiều văn bản ra sao?"))

    assert result.decision.intent is IntentType.FACTUAL
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.INTENT_CLASSIFIER_LLM
    )
    assert classifier.calls == ["Thủ tục qua nhiều văn bản ra sao?"]


def test_low_confidence_rule_used_without_classifier() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Thủ tục qua nhiều văn bản ra sao?")
    )
    assert result.decision.intent is IntentType.MULTI_HOP
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.MULTI_HOP_EXPLICIT
    )


def test_typed_reference_goal_is_factual_not_graph_topology_intent() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Khoản 11 Điều 4 dẫn chiếu đến điều nào?"),
        relation_goal=RelationGoal.REFERS_TO,
    )

    assert result.decision.intent is IntentType.FACTUAL
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.EXPLICIT_REFERENCE_LOOKUP
    )

def test_classifier_resolves_intent_when_no_rule_matches() -> None:
    classifier = FakeClassifier(IntentType.DEFINITION)
    result = IntentRouter(
        RetrievalConfig(), classifier=classifier, clock=FixedClock()
    ).route(RetrievalRequest(query="Điều kiện thành lập doanh nghiệp"))

    assert result.decision.intent is IntentType.DEFINITION
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.INTENT_CLASSIFIER_LLM
    )
    assert classifier.calls == ["Điều kiện thành lập doanh nghiệp"]


def test_force_intent_bypasses_rule_and_classifier() -> None:
    classifier = FakeClassifier(IntentType.FACTUAL)
    result = IntentRouter(
        RetrievalConfig(), classifier=classifier, clock=FixedClock()
    ).route(
        RetrievalRequest(
            query="Vốn điều lệ là gì?", force_intent=IntentType.HIERARCHY
        )
    )

    assert result.decision.intent is IntentType.HIERARCHY
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.FORCED_INTENT
    )
    assert classifier.calls == []


def test_classifier_failure_propagates_not_factual() -> None:
    classifier = FakeClassifier(error=IntentAnalysisError("boom"))
    with pytest.raises(IntentAnalysisError):
        IntentRouter(
            RetrievalConfig(), classifier=classifier, clock=FixedClock()
        ).route(RetrievalRequest(query="Điều kiện thành lập doanh nghiệp"))


def test_current_validity_uses_injected_clock() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Quy định này còn hiệu lực không?")
    )
    assert result.temporal.resolved_from == date(2026, 7, 13)
    assert result.decision.temporal_source is TemporalSource.INJECTED_CURRENT_DATE
    assert (
        result.decision.decision_reason_code
        is RetrievalDecisionReasonCode.VALIDITY_CURRENT_DATE
    )
    assert result.decision.required_capability == "corpus_complete_current_validity"


def test_explicit_date_validity_uses_scoped_temporal_metadata() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Ngày 01 tháng 07 năm 2022, Điều 30 còn hiệu lực không?")
    )

    assert result.decision.required_capability == "scoped_temporal_metadata"


def test_explicit_date_with_natural_validity_wording_routes_to_validity() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(
            query=(
                "Ngày 01 tháng 07 năm 2022, Điều 30 Luật Doanh nghiệp 2020 "
                "có hiệu lực không?"
            )
        )
    )

    assert result.decision.intent is IntentType.VALIDITY
    assert result.decision.required_capability == "scoped_temporal_metadata"


def test_structural_hierarchy_does_not_require_guides() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Khoản 2 thuộc Điều nào?")
    )

    assert result.decision.intent is IntentType.HIERARCHY
    assert result.decision.required_capability == "structural_hierarchy"


def test_regulation_of_obligations_is_not_misread_as_definition() -> None:
    result = IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
        RetrievalRequest(query="Các khoản quy định nghĩa vụ thuộc Điều nào?")
    )

    assert result.decision.intent is IntentType.HIERARCHY


def test_request_date_conflict_with_query_date_fails() -> None:
    request = RetrievalRequest(
        query="Quy định vào ngày 1 tháng 1 năm 2020",
        filters=RetrievalFilters(query_date=date(2021, 1, 1)),
    )
    with pytest.raises(TemporalRoutingError, match="conflicts"):
        IntentRouter(RetrievalConfig(), clock=FixedClock()).route(request)


def test_force_validity_does_not_bypass_temporal_requirement() -> None:
    with pytest.raises(TemporalRoutingError, match="resolved temporal point"):
        IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
            RetrievalRequest(query="Quy định", force_intent=IntentType.VALIDITY)
        )


def test_invalid_limit_override_is_not_clamped() -> None:
    with pytest.raises(RetrievalRequestError):
        IntentRouter(RetrievalConfig(), clock=FixedClock()).route(
            RetrievalRequest(query="Quy định", top_k=5, final_k=6)
        )
