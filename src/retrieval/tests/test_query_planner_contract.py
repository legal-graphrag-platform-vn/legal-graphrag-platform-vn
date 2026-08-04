from __future__ import annotations

import asyncio
import json

import pytest

from src.application.gemini_query_planner import GeminiQueryPlanner
from src.retrieval.planning.config import QueryPlannerConfig
from src.retrieval.planning.errors import (
    QueryPlannerDependencyError,
    QueryPlannerInvalidPlanError,
    QueryPlannerTimeoutError,
)
from src.retrieval.planning.fingerprint import build_unlinked_plan_fingerprint


VALID_PLAN = {
    "anchor": {"text": "Khoản 3 Điều 145", "expected_label": "Clause"},
    "target": {"text": "Khoản 1 Điều 145"},
    "steps": [
        {"relation": "REFERS_TO", "direction": "outgoing", "next_label": "Clause"},
        {"relation": "REFERS_TO", "direction": "outgoing", "next_label": "Clause"},
    ],
}


class FakeResponse:
    def __init__(self, text: str | None, *, parsed=None) -> None:
        self.text = text
        self.parsed = parsed


class FakeModels:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.last_kwargs = None

    async def generate_content(self, **kwargs):
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.last_kwargs = kwargs
        try:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, float):
                await asyncio.sleep(outcome)
                return FakeResponse(json.dumps(VALID_PLAN))
            return outcome
        finally:
            self.active -= 1


class FakeAio:
    def __init__(self, outcomes: list[object]) -> None:
        self.models = FakeModels(outcomes)
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.aio = FakeAio(outcomes)


def test_valid_structured_plan_is_strict_and_fingerprint_is_stable() -> None:
    async def scenario() -> None:
        client = FakeClient(
            [
                FakeResponse(json.dumps(VALID_PLAN)),
                FakeResponse("ignored", parsed=VALID_PLAN),
            ]
        )
        planner = _planner(client)

        first = await planner.plan("  Câu hỏi   nhiều bước ")
        second = await planner.plan("Câu hỏi nhiều bước")

        assert first == second
        assert build_unlinked_plan_fingerprint(
            first
        ) == build_unlinked_plan_fingerprint(second)
        request = client.aio.models.last_kwargs
        assert "node_id" not in request["contents"]
        system_instruction = request["config"]["system_instruction"]
        assert "Cypher" in system_instruction
        assert "cụm tìm kiếm tự đủ nghĩa" in system_instruction
        assert "chủ thể, hành vi, điều kiện và số liệu" in system_instruction
        assert "không dùng target chung chung" in system_instruction.casefold()
        assert "additionalProperties" not in json.dumps(
            request["config"]["response_json_schema"]
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["target"].update(text=""),
        lambda value: value["steps"][0].update(relation="UNKNOWN"),
        lambda value: value.update(node_id="ldn_2020_art145_cl3"),
        lambda value: value.update(cypher="MATCH (n) RETURN n"),
    ],
)
def test_invalid_or_expanded_provider_payload_is_typed(mutation) -> None:
    async def scenario() -> None:
        payload = json.loads(json.dumps(VALID_PLAN))
        mutation(payload)
        planner = _planner(FakeClient([FakeResponse(json.dumps(payload))]))

        with pytest.raises(QueryPlannerInvalidPlanError):
            await planner.plan("Câu hỏi")

    asyncio.run(scenario())


def test_empty_and_malformed_json_are_typed() -> None:
    async def scenario() -> None:
        for text in (None, "not-json"):
            planner = _planner(FakeClient([FakeResponse(text)]))
            with pytest.raises(QueryPlannerInvalidPlanError):
                await planner.plan("Câu hỏi")

    asyncio.run(scenario())


def test_timeout_closed_state_and_cancellation_are_explicit() -> None:
    async def scenario() -> None:
        timeout_planner = _planner(FakeClient([0.2]), timeout_seconds=0.01)
        with pytest.raises(QueryPlannerTimeoutError):
            await timeout_planner.plan("Câu hỏi")

        closed_planner = _planner(FakeClient([]))
        await closed_planner.aclose()
        await closed_planner.aclose()
        with pytest.raises(QueryPlannerDependencyError):
            await closed_planner.plan("Câu hỏi")

        cancelled = _planner(FakeClient([asyncio.CancelledError()]))
        with pytest.raises(asyncio.CancelledError):
            await cancelled.plan("Câu hỏi")

    asyncio.run(scenario())


def test_retry_and_concurrency_are_bounded() -> None:
    async def scenario() -> None:
        retry_client = FakeClient(
            [RuntimeError("429"), FakeResponse(json.dumps(VALID_PLAN))]
        )
        await _planner(retry_client, max_retries=1).plan("Câu hỏi")
        assert retry_client.aio.models.calls == 2

        concurrent_client = FakeClient([0.02, 0.02, 0.02])
        planner = _planner(concurrent_client, max_concurrency=2)
        await asyncio.gather(*(planner.plan("Câu hỏi") for _ in range(3)))
        assert concurrent_client.aio.models.peak == 2

    asyncio.run(scenario())


def _planner(
    client: FakeClient,
    *,
    timeout_seconds: float = 1,
    max_retries: int = 0,
    max_concurrency: int = 1,
) -> GeminiQueryPlanner:
    return GeminiQueryPlanner(
        api_key="test-only",
        model="gemini-test",
        config=QueryPlannerConfig(
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_concurrency=max_concurrency,
        ),
        client_factory=lambda _: client,
        generate_config_factory=lambda **kwargs: kwargs,
    )
