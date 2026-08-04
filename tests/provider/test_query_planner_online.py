from __future__ import annotations

import asyncio
import os

import pytest

from src.application.gemini_query_planner import GeminiQueryPlanner
from src.retrieval.planning.config import QueryPlannerConfig


pytestmark = [pytest.mark.integration, pytest.mark.query_planner_live]


def test_real_gemini_query_planner_smoke() -> None:
    if os.getenv("RUN_QUERY_PLANNER_INTEGRATION") != "1":
        pytest.skip("Set RUN_QUERY_PLANNER_INTEGRATION=1 for live planner smoke")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY is required for live planner smoke")

    async def scenario() -> None:
        planner = GeminiQueryPlanner(
            api_key=api_key,
            model=os.getenv("QUERY_PLANNER_MODEL", "gemini-3.1-flash-lite"),
            config=QueryPlannerConfig(timeout_seconds=60, max_retries=0),
        )
        try:
            plan = await planner.plan(
                "Từ Khoản 3 Điều 145, lần theo hai dẫn chiếu để tới Khoản 1 Điều 145."
            )
            assert plan.anchor.text
            assert plan.target.text
            assert 2 <= len(plan.steps) <= 3
        finally:
            await planner.aclose()

    asyncio.run(scenario())
