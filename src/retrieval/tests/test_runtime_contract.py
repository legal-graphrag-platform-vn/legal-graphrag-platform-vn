import pytest
from datetime import date

from src.retrieval.config import RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import GraphExpansion, IntentType, RetrievalRequest
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.runtime import RetrievalRuntime


class EmptyChannel:
    def retrieve(self, query, *, filters, top_k):
        return []


class EmptyGraph:
    def __init__(self) -> None:
        self.calls = 0

    def expand(self, entry_ids, intent, *, filters):
        self.calls += 1
        return GraphExpansion()


class CapabilityInspector:
    def __init__(self, **overrides) -> None:
        self._values = overrides

    def inspect_capabilities(self, filters):
        return self._values

    def inspect_dependencies(self):
        return {}


class FixedClock:
    def today(self):
        return date(2026, 7, 13)


def _runtime(capabilities: CapabilityInspector, graph: EmptyGraph) -> RetrievalRuntime:
    channel = EmptyChannel()
    return RetrievalRuntime(
        router=IntentRouter(RetrievalConfig(), clock=FixedClock()),
        seed_executor=SeedChannelExecutor(vector=channel, fulltext=channel),
        graph_retriever=graph,
        capability_inspector=capabilities,
        fusion=ReciprocalRankFusion(),
        temporal_filter=TemporalFilter(),
        context_builder=ContextBuilder(EvidenceVerifier()),
    )


def test_empty_supported_result_is_not_capability_failure() -> None:
    graph = EmptyGraph()
    context = _runtime(CapabilityInspector(), graph).retrieve("quy định")
    assert context.capability_status == "no_results"
    assert context.retrieval_mode == "no_results"
    assert graph.calls == 1


def test_unsupported_hierarchy_raises_typed_capability_error() -> None:
    runtime = _runtime(
        CapabilityInspector(guides_relations_available=False), EmptyGraph()
    )
    with pytest.raises(RetrievalCapabilityError) as raised:
        runtime.retrieve(
            RetrievalRequest(
                query="Văn bản hướng dẫn",
                force_intent=IntentType.HIERARCHY,
            )
        )
    assert raised.value.required_capability == "guides_relations"
