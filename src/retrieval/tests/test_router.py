from datetime import date

import pytest

from src.retrieval.config import RetrievalConfig
from src.retrieval.errors import RetrievalRequestError, TemporalRoutingError
from src.retrieval.models import (
    IntentType,
    RetrievalDecisionReasonCode,
    RetrievalFilters,
    RetrievalRequest,
    TemporalSource,
)
from src.retrieval.routing.router import IntentRouter


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
