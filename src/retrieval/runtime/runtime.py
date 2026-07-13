"""Single canonical retrieval orchestration pipeline."""

from __future__ import annotations

import time
from typing import Any

from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import RetrievalCapabilityError, RetrievalDependencyError
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import (
    CapabilitySnapshot,
    RetrievalCapability,
    GraphExpansion,
    RetrievalChannel,
    RetrievalContext,
    RetrievalRequest,
)
from src.retrieval.ports import (
    CapabilityInspectionPort,
    GraphChannelPort,
    RerankerPort,
)
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.routing.router import IntentRouter


class RetrievalRuntime:
    """Own query analysis, two-stage fusion, one expansion, and context output."""

    def __init__(
        self,
        *,
        router: IntentRouter,
        seed_executor: SeedChannelExecutor,
        graph_retriever: GraphChannelPort | None,
        capability_inspector: CapabilityInspectionPort,
        fusion: ReciprocalRankFusion,
        temporal_filter: TemporalFilter,
        context_builder: ContextBuilder,
        reranker: RerankerPort | None = None,
    ) -> None:
        self._router = router
        self._seed_executor = seed_executor
        self._graph_retriever = graph_retriever
        self._capability_inspector = capability_inspector
        self._fusion = fusion
        self._temporal_filter = temporal_filter
        self._context_builder = context_builder
        self._reranker = reranker

    def retrieve(
        self,
        request: RetrievalRequest | str,
        *,
        top_k: int | None = None,
        final_k: int | None = None,
    ) -> RetrievalContext:
        active_request = (
            request
            if isinstance(request, RetrievalRequest)
            else RetrievalRequest(query=request, top_k=top_k, final_k=final_k)
        )
        started = time.perf_counter()
        routing = self._router.route(active_request)
        decision = routing.decision
        capabilities = CapabilitySnapshot.model_validate(
            self._capability_inspector.inspect_capabilities(routing.filters)
        )
        _validate_legal_capability(decision.required_capability, capabilities)

        seed_started = time.perf_counter()
        seed_results = self._seed_executor.execute(
            active_request.query,
            decision.seed_channels,
            filters=routing.filters,
            candidate_k=decision.candidate_k,
        )
        seed_latency = _elapsed_ms(seed_started)
        seed_ranked = self._fusion.fuse_channels(
            {channel.value: units for channel, units in seed_results.items()},
            top_n=decision.candidate_k,
        )

        graph_started = time.perf_counter()
        expansion = self._expand_once(
            decision=decision,
            entry_ids=[unit.id for unit in seed_ranked[: decision.graph_entry_k]],
            filters=routing.filters,
        )
        graph_latency = _elapsed_ms(graph_started)

        final_channels = {
            channel.value: units for channel, units in seed_results.items()
        }
        if decision.graph_enabled:
            final_channels[RetrievalChannel.GRAPH.value] = expansion.units
        fused = self._fusion.fuse_channels(
            final_channels,
            top_n=decision.candidate_k,
        )
        filtered = self._temporal_filter.filter(
            fused,
            routing.temporal,
            preserve_versions=decision.preserve_versions,
        )

        reranker_started = time.perf_counter()
        reranker_applied = decision.enable_reranker
        if reranker_applied:
            if self._reranker is None:
                raise RetrievalDependencyError(
                    "Reranker was requested but no reranker is configured"
                )
            final_units = self._reranker.rerank(
                active_request.query,
                filtered,
                top_n=decision.final_k,
            )
        else:
            final_units = sorted(
                filtered,
                key=lambda unit: (-(unit.final_score or 0.0), unit.id),
            )[: decision.final_k]

        executed_channels = list(decision.seed_channels)
        if decision.graph_enabled:
            executed_channels.append(RetrievalChannel.GRAPH)
        metrics: dict[str, Any] = {
            "seed_channel_count": len(seed_results),
            "vector_hits": len(seed_results.get(RetrievalChannel.VECTOR, [])),
            "fulltext_hits": len(seed_results.get(RetrievalChannel.FULLTEXT, [])),
            "seed_fused_count": len(seed_ranked),
            "graph_expansion_count": 1 if decision.graph_enabled else 0,
            "graph_paths_count": len(expansion.paths),
            "graph_units_count": len(expansion.units),
            "temporal_filtered_count": len(fused) - len(filtered),
            "seed_latency_ms": seed_latency,
            "graph_latency_ms": graph_latency,
            "reranker_latency_ms": _elapsed_ms(reranker_started),
            "total_pipeline_latency_ms": _elapsed_ms(started),
        }
        return self._context_builder.build_context(
            query=active_request.query,
            intent=decision.intent,
            temporal=routing.temporal,
            units=final_units,
            graph_paths=expansion.paths,
            metrics=metrics,
            decision=decision,
            filters=routing.filters,
            executed_channels=executed_channels,
            reranker_applied=reranker_applied,
        )

    def _expand_once(
        self,
        *,
        decision: Any,
        entry_ids: list[str],
        filters: Any,
    ) -> GraphExpansion:
        if not decision.graph_enabled:
            return GraphExpansion()
        if self._graph_retriever is None or decision.graph_policy_intent is None:
            raise RetrievalDependencyError(
                "Graph expansion is enabled but no graph retriever is configured"
            )
        return self._graph_retriever.expand(
            entry_ids,
            decision.graph_policy_intent,
            filters=filters,
        )


def _validate_legal_capability(
    required: RetrievalCapability | None, capabilities: CapabilitySnapshot
) -> None:
    availability = {
        RetrievalCapability.SCOPED_TEMPORAL_METADATA: capabilities.scoped_temporal_metadata_available,
        RetrievalCapability.CORPUS_COMPLETE_CURRENT_VALIDITY: (
            capabilities.corpus_complete_current_validity_available
        ),
        RetrievalCapability.VERSION_CHAIN_VALIDITY: capabilities.temporal_relations_available,
        RetrievalCapability.STRUCTURAL_HIERARCHY: capabilities.structural_hierarchy_available,
        RetrievalCapability.GUIDES_RELATIONS: capabilities.guides_relations_available,
        RetrievalCapability.MULTIPLE_VERSIONS: capabilities.multiple_versions_available,
        RetrievalCapability.LEXICAL_DEFINITION: capabilities.fulltext_index_available,
        RetrievalCapability.SEMANTIC_MULTI_HOP_GRAPH: capabilities.semantic_multi_hop_graph_available,
    }
    if required is not None and not availability.get(required, False):
        raise RetrievalCapabilityError(
            f"Scoped graph does not provide required capability: {required.value}",
            required_capability=required.value,
            available_capability="none",
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
