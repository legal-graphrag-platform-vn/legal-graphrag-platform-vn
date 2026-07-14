from __future__ import annotations

import asyncio
from typing import Any

import pytest

from container import Container, build_container
from settings import Settings


class FakeRuntime:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_count = 0
        self.events = events

    def close(self) -> None:
        self.close_count += 1
        if self.events is not None:
            self.events.append("runtime")


class FakeRunner:
    def __init__(
        self,
        *,
        events: list[str] | None = None,
        error: Exception | None = None,
        **_: object,
    ) -> None:
        self.close_count = 0
        self.events = events
        self.error = error

    async def aclose(self) -> int:
        self.close_count += 1
        if self.events is not None:
            self.events.append("runner")
        if self.error is not None:
            raise self.error
        return 0


class FakeAnswerGenerator:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_count = 0
        self.events = events

    async def generate(self, request):
        raise AssertionError("not used in lifecycle test")

    async def aclose(self) -> None:
        self.close_count += 1
        if self.events is not None:
            self.events.append("answer")


def test_mock_mode_constructs_no_runtime_or_runner() -> None:
    def forbidden_factory(*args: object, **kwargs: object) -> None:
        raise AssertionError("mock mode must not create retrieval resources")

    container = asyncio.run(
        build_container(
            Settings(app_mode="mock", _env_file=None),
            runtime_factory=forbidden_factory,
            runner_factory=forbidden_factory,  # type: ignore[arg-type]
        )
    )

    assert container.query_service is container.rag_service
    assert container.chat_service is container.rag_service
    asyncio.run(container.close())


def test_graphrag_mode_constructs_runtime_once_with_canonical_settings() -> None:
    calls: list[tuple[object, object]] = []
    runtime = FakeRuntime()
    runners: list[FakeRunner] = []

    def runtime_factory(config: object, settings: object) -> FakeRuntime:
        calls.append((config, settings))
        return runtime

    def runner_factory(**kwargs: object) -> FakeRunner:
        runner = FakeRunner(**kwargs)
        runners.append(runner)
        return runner

    container = asyncio.run(
        build_container(
            _graphrag_settings(),
            runtime_factory=runtime_factory,
            runner_factory=runner_factory,  # type: ignore[arg-type]
        )
    )

    assert len(calls) == 1
    assert len(runners) == 1
    assert container.rag_service is None
    assert container.chat_service is None
    asyncio.run(container.close())
    assert runtime.close_count == 1
    assert runners[0].close_count == 1


def test_partial_runner_startup_failure_closes_runtime() -> None:
    runtime = FakeRuntime()

    def fail_runner(**kwargs: object) -> Any:
        raise RuntimeError("runner startup failed")

    with pytest.raises(RuntimeError, match="runner startup failed"):
        asyncio.run(
            build_container(
                _graphrag_settings(),
                runtime_factory=lambda *_: runtime,
                runner_factory=fail_runner,
            )
        )
    assert runtime.close_count == 1


def test_container_closes_runner_before_runtime_exactly_once() -> None:
    async def scenario() -> None:
        events: list[str] = []
        runtime = FakeRuntime(events)
        runner = FakeRunner(events=events)
        container = Container(
            query_service=object(),  # type: ignore[arg-type]
            chat_service=None,
            rag_service=None,
            retrieval_runtime=runtime,
            retrieval_runner=runner,  # type: ignore[arg-type]
        )
        await container.close()
        await container.close()
        assert events == ["runner", "runtime"]
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_runtime_still_closes_when_runner_cleanup_fails() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = FakeRunner(error=RuntimeError("runner cleanup failed"))
        container = Container(
            query_service=object(),  # type: ignore[arg-type]
            chat_service=None,
            rag_service=None,
            retrieval_runtime=runtime,
            retrieval_runner=runner,  # type: ignore[arg-type]
        )
        with pytest.raises(RuntimeError, match="runner cleanup failed"):
            await container.close()
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_answer_profile_constructs_once_and_closes_before_retrieval() -> None:
    async def scenario() -> None:
        events: list[str] = []
        runtime = FakeRuntime(events)
        runner = FakeRunner(events=events)
        answer = FakeAnswerGenerator(events)
        answer_calls = 0

        def answer_factory(*args: object) -> FakeAnswerGenerator:
            nonlocal answer_calls
            answer_calls += 1
            return answer

        container = await build_container(
            _graphrag_settings(answer_generation_enabled=True),
            runtime_factory=lambda *_: runtime,
            runner_factory=lambda **_: runner,
            answer_factory=answer_factory,
        )
        assert answer_calls == 1
        assert container.chat_service is not None
        await container.close()
        assert events == ["answer", "runner", "runtime"]

    asyncio.run(scenario())


def test_answer_startup_failure_closes_retrieval_resources() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = FakeRunner()

        def fail_answer(*args: object) -> None:
            raise RuntimeError("answer startup failed")

        with pytest.raises(RuntimeError, match="answer startup failed"):
            await build_container(
                _graphrag_settings(answer_generation_enabled=True),
                runtime_factory=lambda *_: runtime,
                runner_factory=lambda **_: runner,
                answer_factory=fail_answer,  # type: ignore[arg-type]
            )
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_answer_startup_failure_still_closes_runtime_when_runner_cleanup_fails() -> (
    None
):
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = FakeRunner(error=RuntimeError("runner cleanup failed"))

        def fail_answer(*args: object) -> None:
            raise RuntimeError("answer startup failed")

        with pytest.raises(RuntimeError, match="answer startup failed"):
            await build_container(
                _graphrag_settings(answer_generation_enabled=True),
                runtime_factory=lambda *_: runtime,
                runner_factory=lambda **_: runner,
                answer_factory=fail_answer,  # type: ignore[arg-type]
            )
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def _graphrag_settings(*, answer_generation_enabled: bool = False) -> Settings:
    return Settings(
        app_mode="graphrag",
        neo4j_uri="bolt://localhost:7688",
        neo4j_user="neo4j",
        neo4j_password="test-only",
        backend_retrieval_timeout_seconds=2,
        backend_retrieval_max_concurrency=2,
        backend_retrieval_shutdown_grace_seconds=1,
        answer_generation_enabled=answer_generation_enabled,
        gemini_api_key="test-only" if answer_generation_enabled else None,
        _env_file=None,
    )
