"""Hermetic tests for the async query-processor adapter (no DB, no network)."""

from __future__ import annotations

import asyncio

from query_processing.adapter import QueryProcessorAdapter


class FakeRunner:
    """Runs the submitted callable inline (stand-in for the bounded executor)."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, call):
        self.runs += 1
        return call()


class FakeProcessor:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[tuple[str, tuple]] = []

    def process(self, current_query, conversation_history):
        self.calls.append((current_query, tuple(conversation_history)))
        return self._result


def test_adapter_runs_processor_on_runner_and_returns_result() -> None:
    processor = FakeProcessor(result="RESULT")
    runner = FakeRunner()
    adapter = QueryProcessorAdapter(processor, runner)

    out = asyncio.run(
        adapter.process("Điều 1 quy định gì?", [{"role": "user", "content": "xin chào"}])
    )

    assert out == "RESULT"
    assert runner.runs == 1
    assert processor.calls == [
        ("Điều 1 quy định gì?", ({"role": "user", "content": "xin chào"},))
    ]


def test_adapter_defaults_to_empty_history() -> None:
    processor = FakeProcessor(result=object())
    adapter = QueryProcessorAdapter(processor, FakeRunner())

    asyncio.run(adapter.process("câu hỏi"))

    assert processor.calls == [("câu hỏi", ())]
