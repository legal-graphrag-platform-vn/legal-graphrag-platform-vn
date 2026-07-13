from datetime import date

from src.retrieval.config import RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import GraphExpansion, GraphPath, RetrievedUnit
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.runtime import RetrievalRuntime


def _unit(unit_id: str, source: str, score: float) -> RetrievedUnit:
    fields = (
        {f"{source}_score": score} if source != "fulltext" else {"bm25_score": score}
    )
    return RetrievedUnit(
        id=unit_id,
        label="Article",
        content_raw="Nội dung",
        document_id="doc",
        article_number="1",
        effective_from=date(2021, 1, 1),
        citation_label="Điều 1",
        retrieval_sources=[source],
        **fields,
    )


class Channel:
    def __init__(self, units):
        self.units = units
        self.calls = 0

    def retrieve(self, query, *, filters, top_k):
        self.calls += 1
        return self.units[:top_k]


class GraphChannel:
    def __init__(self) -> None:
        self.calls = 0

    def expand(self, entry_ids, intent, *, filters):
        self.calls += 1
        return GraphExpansion(
            paths=[
                GraphPath(
                    nodes=[entry_ids[0], "graph_only"],
                    relations=["REFERS_TO"],
                    relation_ids=["relation-1"],
                    path_description="entry -[REFERS_TO]-> graph_only",
                    is_temporal_valid=True,
                )
            ],
            units=[_unit("graph_only", "graph", 1.0)],
        )


class Capabilities:
    def inspect_capabilities(self, filters):
        return {
            "vector_article_index_available": True,
            "vector_clause_index_available": True,
            "fulltext_index_available": True,
            "canonical_relation_types_available": ["REFERS_TO"],
        }

    def inspect_dependencies(self):
        return {}


class FixedClock:
    def today(self):
        return date(2026, 7, 13)


def test_graph_expanded_unit_enters_final_candidate_pool_once() -> None:
    vector = Channel([_unit("vector", "vector", 0.8)])
    fulltext = Channel([_unit("fulltext", "fulltext", 2.0)])
    graph = GraphChannel()
    runtime = RetrievalRuntime(
        router=IntentRouter(RetrievalConfig(), clock=FixedClock()),
        seed_executor=SeedChannelExecutor(vector=vector, fulltext=fulltext),
        graph_retriever=graph,
        capability_inspector=Capabilities(),
        fusion=ReciprocalRankFusion(),
        temporal_filter=TemporalFilter(),
        context_builder=ContextBuilder(EvidenceVerifier()),
    )

    context = runtime.retrieve("quy định", top_k=5, final_k=3)

    assert graph.calls == 1
    assert "graph_only" in [unit.id for unit in context.retrieved_units]
    assert context.retrieval_mode == "hybrid"
    assert any(item.evidence_type == "graph" for item in context.evidence)
    assert context.metrics["graph_expansion_count"] == 1
