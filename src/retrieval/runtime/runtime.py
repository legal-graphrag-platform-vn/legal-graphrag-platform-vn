"""Single canonical retrieval orchestration pipeline."""

from __future__ import annotations

import time
from typing import Any

from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import (
    RetrievalCapabilityError,
    RetrievalDependencyError,
    RetrievalOutputError,
    RetrievalRequestError,
)
from src.retrieval.execution_contract import PlanExecutionResult, PlanExecutionStatus
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import (
    CapabilitySnapshot,
    GraphPath,
    RetrievalCapability,
    GraphExpansion,
    RetrievalChannel,
    RetrievalContext,
    RetrievalRequest,
    IntentType,
    PreparedRetrievalRequest,
)
from src.retrieval.ports import (
    CapabilityInspectionPort,
    GraphChannelPort,
    PlannedPathExecutionPort,
    RerankerPort,
)
from src.retrieval.planning.models import BoundSemanticPlan
from src.retrieval.path_identity import build_topology_path_fingerprint
from src.retrieval.retriever.graph import (
    deduplicate_topology_paths,
    graph_path_rank_key,
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
        planned_executor: PlannedPathExecutionPort | None = None,
    ) -> None:
        self._router = router
        self._seed_executor = seed_executor
        self._graph_retriever = graph_retriever
        self._capability_inspector = capability_inspector
        self._fusion = fusion
        self._temporal_filter = temporal_filter
        self._context_builder = context_builder
        self._reranker = reranker
        self._planned_executor = planned_executor

    def retrieve(
        self,
        request: RetrievalRequest | str,
        *,
        top_k: int | None = None,
        final_k: int | None = None,
    ) -> RetrievalContext:
        return self.execute(
            self.prepare(request, top_k=top_k, final_k=final_k),
        )

    def prepare(
        self,
        request: RetrievalRequest | str,
        *,
        top_k: int | None = None,
        final_k: int | None = None,
    ) -> PreparedRetrievalRequest:
        started = time.perf_counter()
        active_request = (
            request
            if isinstance(request, RetrievalRequest)
            else RetrievalRequest(query=request, top_k=top_k, final_k=final_k)
        )
        return PreparedRetrievalRequest(
            request=active_request,
            routing=self._router.route(active_request),
            prepare_latency_ms=_elapsed_ms(started),
        )

    def execute(
        self,
        prepared: PreparedRetrievalRequest,
        *,
        bound_plan: BoundSemanticPlan | None = None,
    ) -> RetrievalContext:
        started = time.perf_counter()
        active_request = prepared.request
        routing = prepared.routing
        decision = routing.decision
        if bound_plan is not None and decision.intent is not IntentType.MULTI_HOP:
            raise RetrievalRequestError(
                "A bound semantic plan may only execute for multi-hop retrieval"
            )
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

        planned_execution = None
        planned_paths = []
        planned_started = time.perf_counter()
        if bound_plan is not None:
            if self._planned_executor is None:
                raise RetrievalDependencyError(
                    "A bound semantic plan was provided but no planned executor is configured"
                )
            planned = self._planned_executor.execute(
                bound_plan, filters=routing.filters
            )
            planned_execution = planned.result
            planned_paths = list(planned.paths)
        planned_latency = _elapsed_ms(planned_started)
        graph_paths = deduplicate_topology_paths([*expansion.paths, *planned_paths])
        graph_paths.sort(key=graph_path_rank_key)
        _validate_planned_path_membership(planned_execution, graph_paths)

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
            "graph_paths_count": len(graph_paths),
            "generic_graph_paths_count": len(expansion.paths),
            "graph_units_count": len(expansion.units),
            "graph_temporal_rejected_path_count": (
                expansion.diagnostics.temporal_rejected_path_count
            ),
            "graph_malformed_path_count": expansion.diagnostics.malformed_path_count,
            "temporal_filtered_count": len(fused) - len(filtered),
            "seed_latency_ms": seed_latency,
            "graph_latency_ms": graph_latency,
            "prepare_latency_ms": prepared.prepare_latency_ms,
            "planned_execution_count": 1 if bound_plan is not None else 0,
            "planned_execution_latency_ms": planned_latency,
            "planned_execution_reason_code": (
                planned_execution.reason_code.value
                if planned_execution is not None
                else "NOT_PROVIDED"
            ),
            "reranker_latency_ms": _elapsed_ms(reranker_started),
            "total_pipeline_latency_ms": prepared.prepare_latency_ms
            + _elapsed_ms(started),
        }
        return self._context_builder.build_context(
            query=active_request.query,
            intent=decision.intent,
            temporal=routing.temporal,
            units=final_units,
            graph_paths=graph_paths,
            metrics=metrics,
            decision=decision,
            filters=routing.filters,
            executed_channels=executed_channels,
            reranker_applied=reranker_applied,
            plan_execution=planned_execution,
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


def _validate_planned_path_membership(
    plan_execution: PlanExecutionResult | None,
    graph_paths: list[GraphPath],
) -> None:
    if (
        plan_execution is None
        or plan_execution.execution_status is not PlanExecutionStatus.SATISFIED
    ):
        return
    available = {build_topology_path_fingerprint(path) for path in graph_paths}
    missing = set(plan_execution.satisfied_path_fingerprints) - available
    if missing:
        raise RetrievalOutputError(
            "Satisfied plan fingerprints are absent from retrieval graph paths"
        )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
