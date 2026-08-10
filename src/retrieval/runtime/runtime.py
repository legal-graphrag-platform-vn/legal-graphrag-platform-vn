"""Single canonical retrieval orchestration pipeline."""

from __future__ import annotations

import time
from typing import Any

from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import (
    CanonicalReferenceUnavailableError,
    RetrievalCapabilityError,
    RetrievalDependencyError,
    RetrievalOutputError,
    RetrievalRequestError,
)
from src.retrieval.execution_contract import (
    PlanExecutionResult,
    PlanExecutionStatus,
    PlanReasonCode,
)
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import (
    CanonicalAnchorHydration,
    CapabilitySnapshot,
    GraphPath,
    RetrievalCapability,
    GraphExpansion,
    RetrievalChannel,
    RetrievalContext,
    RetrievalRequest,
    IntentType,
    PreparedRetrievalRequest,
    RetrievedUnit,
    RetrievalDecision,
    RetrievalFilters,
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
from src.retrieval.resolved_reference import RelationGoal, RetrievalExecutionContext


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
        execution_context: RetrievalExecutionContext | None = None,
    ) -> RetrievalContext:
        return self.execute(
            self.prepare(
                request,
                top_k=top_k,
                final_k=final_k,
                execution_context=execution_context,
            ),
        )

    def prepare(
        self,
        request: RetrievalRequest | str,
        *,
        top_k: int | None = None,
        final_k: int | None = None,
        execution_context: RetrievalExecutionContext | None = None,
    ) -> PreparedRetrievalRequest:
        started = time.perf_counter()
        active_request = (
            request
            if isinstance(request, RetrievalRequest)
            else RetrievalRequest(query=request, top_k=top_k, final_k=final_k)
        )
        active_execution_context = execution_context or RetrievalExecutionContext()
        return PreparedRetrievalRequest(
            request=active_request,
            routing=self._router.route(
                active_request,
                relation_goal=active_execution_context.relation_goal,
            ),
            execution_context=active_execution_context,
            prepare_latency_ms=_elapsed_ms(started),
        )

    def execute(
        self,
        prepared: PreparedRetrievalRequest,
        *,
        bound_plan: BoundSemanticPlan | None = None,
        binding_reason_code: PlanReasonCode | None = None,
    ) -> RetrievalContext:
        started = time.perf_counter()
        active_request = prepared.request
        routing = prepared.routing
        execution_context = prepared.execution_context
        decision = routing.decision
        if bound_plan is not None and decision.intent is not IntentType.MULTI_HOP:
            raise RetrievalRequestError(
                "A bound semantic plan may only execute for multi-hop retrieval"
            )
        capabilities = CapabilitySnapshot.model_validate(
            self._capability_inspector.inspect_capabilities(routing.filters)
        )
        _validate_legal_capability(decision.required_capability, capabilities)

        anchor_ids = list(execution_context.anchor_node_ids)
        anchor_hydration = self._hydrate_anchors(
            anchor_ids=anchor_ids,
            filters=routing.filters,
        )
        missing_anchors = set(anchor_ids) - set(anchor_hydration.matched_anchor_ids)
        if missing_anchors:
            raise CanonicalReferenceUnavailableError(
                "Resolved canonical reference is unavailable under active filters"
            )

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
            entry_ids=_stable_unique(
                [
                    *anchor_ids,
                    *[unit.id for unit in seed_ranked[: decision.graph_entry_k]],
                ]
            ),
            filters=routing.filters,
            relation_goal=execution_context.relation_goal,
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
            final_channels[RetrievalChannel.GRAPH.value] = _merge_units(
                anchor_hydration.units,
                expansion.units,
            )
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

        required_units = _required_canonical_units(
            anchor_units=anchor_hydration.units,
            expansion_units=expansion.units,
            graph_paths=graph_paths,
            anchor_ids=set(anchor_ids),
            relation_goal=execution_context.relation_goal,
        )
        final_units = _pin_required_units(
            final_units,
            required_units,
            final_k=decision.final_k,
        )

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
            "resolved_reference_count": len(execution_context.resolved_references),
            "canonical_anchor_count": len(anchor_ids),
            "canonical_anchor_hydrated_count": len(
                anchor_hydration.matched_anchor_ids
            ),
            "relation_goal": (
                execution_context.relation_goal.value
                if execution_context.relation_goal is not None
                else None
            ),
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
                else binding_reason_code.value
                if binding_reason_code is not None
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
            resolved_references=execution_context.resolved_references,
            relation_goal=execution_context.relation_goal,
        )

    def _hydrate_anchors(
        self, *, anchor_ids: list[str], filters: RetrievalFilters
    ) -> CanonicalAnchorHydration:
        if not anchor_ids:
            return CanonicalAnchorHydration()
        if self._graph_retriever is None:
            raise RetrievalDependencyError(
                "Canonical references require the graph retrieval channel"
            )
        return self._graph_retriever.hydrate_anchors(anchor_ids, filters=filters)

    def _expand_once(
        self,
        *,
        decision: RetrievalDecision,
        entry_ids: list[str],
        filters: RetrievalFilters,
        relation_goal: RelationGoal | None,
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
            relation_goal=relation_goal,
        )


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _merge_units(*groups: list[RetrievedUnit]) -> list[RetrievedUnit]:
    merged: dict[str, RetrievedUnit] = {}
    for group in groups:
        for unit in group:
            merged.setdefault(unit.id, unit)
    return list(merged.values())


def _required_canonical_units(
    *,
    anchor_units: list[RetrievedUnit],
    expansion_units: list[RetrievedUnit],
    graph_paths: list[GraphPath],
    anchor_ids: set[str],
    relation_goal: RelationGoal | None,
) -> list[RetrievedUnit]:
    required_ids = [unit.id for unit in anchor_units]
    if relation_goal is not None:
        for path in graph_paths:
            if not any(
                edge.relation_type == relation_goal.value
                and edge.source_id in anchor_ids
                for edge in path.edges
            ):
                continue
            required_ids.extend(
                node.citable_unit_id
                for node in path.nodes
                if node.citable_unit_id is not None
            )
    by_id = {
        unit.id: unit for unit in _merge_units(anchor_units, expansion_units)
    }
    return [by_id[unit_id] for unit_id in _stable_unique(required_ids) if unit_id in by_id]


def _pin_required_units(
    ranked_units: list[RetrievedUnit],
    required_units: list[RetrievedUnit],
    *,
    final_k: int,
) -> list[RetrievedUnit]:
    if len(required_units) > final_k:
        raise RetrievalRequestError(
            "final_k cannot retain all canonical relation evidence"
        )
    required_ids = {unit.id for unit in required_units}
    return [
        *required_units,
        *[unit for unit in ranked_units if unit.id not in required_ids],
    ][:final_k]


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
