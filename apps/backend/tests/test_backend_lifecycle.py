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


class FakeDocumentBrowser:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_count = 0
        self.events = events

    async def aclose(self) -> None:
        self.close_count += 1
        if self.events is not None:
            self.events.append("browser")


class FakeQueryPlanner:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        events: list[str] | None = None,
        *,
        close_error: Exception | None = None,
    ) -> None:
        self.close_count = 0
        self.events = events
        self.close_error = close_error

    async def plan(self, query: str):
        raise AssertionError("not used in lifecycle test")

    async def aclose(self) -> None:
        self.close_count += 1
        if self.events is not None:
            self.events.append("planner")
        if self.close_error is not None:
            raise self.close_error


def fake_browser_factory(
    settings: object,
    runner: object,
) -> FakeDocumentBrowser:
    return FakeDocumentBrowser()


def test_mock_mode_constructs_no_runtime_or_runner() -> None:
    def forbidden_factory(*args: object, **kwargs: object) -> None:
        raise AssertionError("mock mode must not create retrieval resources")

    container = asyncio.run(
        build_container(
            Settings(app_mode="mock", _env_file=None),
            runtime_factory=forbidden_factory,
            runner_factory=forbidden_factory,  # type: ignore[arg-type]
            browser_factory=forbidden_factory,  # type: ignore[arg-type]
        )
    )

    assert container.query_service is container.rag_service
    assert container.chat_service is container.rag_service
    asyncio.run(container.close())


def test_graphrag_mode_constructs_runtime_once_with_canonical_settings() -> None:
    calls: list[tuple[object, object]] = []
    runtime = FakeRuntime()
    runners: list[FakeRunner] = []

    def runtime_factory(
        config: object, settings: object, **kwargs: object
    ) -> FakeRuntime:
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
            browser_factory=fake_browser_factory,  # type: ignore[arg-type]
        )
    )

    assert len(calls) == 1
    assert len(runners) == 1
    assert container.rag_service is not None
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
                runtime_factory=lambda *_, **__: runtime,
                runner_factory=fail_runner,
                browser_factory=fake_browser_factory,  # type: ignore[arg-type]
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
            document_service=FakeDocumentBrowser(events),
            rag_service=None,
            retrieval_runtime=runtime,
            retrieval_runner=runner,  # type: ignore[arg-type]
        )
        await container.close()
        await container.close()
        assert events == ["browser", "runner", "runtime"]
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
            document_service=FakeDocumentBrowser(),
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
            runtime_factory=lambda *_, **__: runtime,
            runner_factory=lambda **_: runner,
            answer_factory=answer_factory,
            browser_factory=lambda *_: FakeDocumentBrowser(events),
        )
        assert answer_calls == 1
        assert container.chat_service is not None
        await container.close()
        assert events == ["answer", "browser", "runner", "runtime"]

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
                runtime_factory=lambda *_, **__: runtime,
                runner_factory=lambda **_: runner,
                answer_factory=fail_answer,  # type: ignore[arg-type]
                browser_factory=lambda *_: FakeDocumentBrowser(),
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
                runtime_factory=lambda *_, **__: runtime,
                runner_factory=lambda **_: runner,
                answer_factory=fail_answer,  # type: ignore[arg-type]
                browser_factory=lambda *_: FakeDocumentBrowser(),
            )
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_planning_profile_constructs_planner_and_closes_before_document() -> None:
    async def scenario() -> None:
        events: list[str] = []
        runtime = FakeRuntime(events)
        runner = FakeRunner(events=events)
        planner = FakeQueryPlanner(events)
        planner_calls = 0

        def planner_factory(settings: object) -> FakeQueryPlanner:
            nonlocal planner_calls
            planner_calls += 1
            return planner

        container = await build_container(
            _graphrag_settings(query_planning_enabled=True),
            runtime_factory=lambda *_, **__: runtime,
            runner_factory=lambda **_: runner,
            planner_factory=planner_factory,
            browser_factory=lambda *_: FakeDocumentBrowser(events),
        )
        assert planner_calls == 1
        await container.close()
        await container.close()
        assert events == ["planner", "browser", "runner", "runtime"]
        assert planner.close_count == 1

    asyncio.run(scenario())


def test_planner_startup_failure_closes_retrieval_resources() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = FakeRunner()

        def fail_planner(settings: object) -> None:
            raise RuntimeError("planner startup failed")

        with pytest.raises(RuntimeError, match="planner startup failed"):
            await build_container(
                _graphrag_settings(query_planning_enabled=True),
                runtime_factory=lambda *_, **__: runtime,
                runner_factory=lambda **_: runner,
                planner_factory=fail_planner,  # type: ignore[arg-type]
                browser_factory=lambda *_: FakeDocumentBrowser(),
            )
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_browser_startup_failure_closes_planner_runner_and_runtime() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = FakeRunner()
        planner = FakeQueryPlanner()

        def fail_browser(*args: object) -> None:
            raise RuntimeError("browser startup failed")

        with pytest.raises(RuntimeError, match="browser startup failed"):
            await build_container(
                _graphrag_settings(query_planning_enabled=True),
                runtime_factory=lambda *_, **__: runtime,
                runner_factory=lambda **_: runner,
                planner_factory=lambda _: planner,
                browser_factory=fail_browser,  # type: ignore[arg-type]
            )

        assert planner.close_count == 1
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_planner_close_failure_does_not_skip_remaining_cleanup() -> None:
    async def scenario() -> None:
        events: list[str] = []
        runtime = FakeRuntime(events)
        runner = FakeRunner(events=events)
        planner = FakeQueryPlanner(
            events,
            close_error=RuntimeError("planner cleanup failed"),
        )
        container = Container(
            query_service=object(),  # type: ignore[arg-type]
            chat_service=None,
            document_service=FakeDocumentBrowser(events),
            rag_service=None,
            query_planner=planner,
            retrieval_runtime=runtime,
            retrieval_runner=runner,  # type: ignore[arg-type]
        )

        with pytest.raises(RuntimeError, match="planner cleanup failed"):
            await container.close()

        assert events == ["planner", "browser", "runner", "runtime"]
        assert planner.close_count == 1
        assert runner.close_count == 1
        assert runtime.close_count == 1

    asyncio.run(scenario())


def _graphrag_settings(
    *,
    answer_generation_enabled: bool = False,
    query_planning_enabled: bool = False,
) -> Settings:
    needs_gemini = answer_generation_enabled or query_planning_enabled
    return Settings(
        app_mode="graphrag",
        neo4j_uri="bolt://localhost:7688",
        neo4j_user="neo4j",
        neo4j_password="test-only",
        backend_retrieval_timeout_seconds=2,
        backend_retrieval_max_concurrency=2,
        backend_retrieval_shutdown_grace_seconds=1,
        answer_generation_enabled=answer_generation_enabled,
        query_planning_enabled=query_planning_enabled,
        gemini_api_key="test-only" if needs_gemini else None,
        database_url="postgresql+asyncpg://u:p@localhost:5432/test",
        anonymous_principal_signing_key="x" * 32,
        _env_file=None,
    )
