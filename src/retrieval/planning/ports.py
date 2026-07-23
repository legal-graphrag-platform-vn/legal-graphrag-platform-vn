"""Ports owned by query-specific graph planning."""

from typing import Protocol

from src.retrieval.planning.models import UnlinkedSemanticPlan


class QueryPlannerPort(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def plan(self, query: str) -> UnlinkedSemanticPlan: ...

    async def aclose(self) -> None: ...
