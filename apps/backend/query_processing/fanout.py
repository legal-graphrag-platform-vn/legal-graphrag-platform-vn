"""Pure helpers for Stage 2 subquery fan-out and context merging.

These functions are deterministic and side-effect free so they can be unit
tested without a live retrieval runtime.
"""

from __future__ import annotations

from datetime import date

from src.retrieval.models import RetrievalContext
from src.shared.retrieval_contract import (
    IntentType,
    QueryProcessingResult,
    RetrievalFilters,
    RetrievalRequest,
)


def build_subquery_requests(
    result: QueryProcessingResult,
    *,
    document_ids: list[str],
    query_date: date | None,
    enable_reranker: bool | None,
) -> list[RetrievalRequest]:
    """One retrieval request per subquery, each routed by its own intent.

    Subquery intents are the four temporal-safe intents
    (factual/definition/validity/hierarchy), so fanning out avoids the
    comparison/multi_hop temporal requirement that a plan-level intent imposes.
    """
    filters = RetrievalFilters(document_ids=document_ids, query_date=query_date)
    return [
        RetrievalRequest(
            query=subquery.query,
            filters=filters,
            force_intent=IntentType(subquery.intent.value),
            enable_reranker=enable_reranker,
        )
        for subquery in result.subqueries
    ]


def merge_contexts(
    contexts: list[RetrievalContext],
    *,
    query: str,
) -> RetrievalContext:
    """Merge per-subquery contexts into one, deduplicating evidence and units.

    The first context is the structural base; only the aggregate fields the
    generator consumes are replaced, so every merged evidence unit_id still
    resolves to a retrieved unit.
    """
    if not contexts:
        raise ValueError("merge_contexts requires at least one context")

    base = contexts[0]
    if len(contexts) == 1:
        return base.model_copy(update={"query": query})

    units = _dedupe_by_key(
        (unit for context in contexts for unit in context.retrieved_units),
        key=lambda unit: unit.id,
    )
    evidence = _dedupe_by_key(
        (item for context in contexts for item in context.evidence),
        key=lambda item: item.unit_id,
    )
    graph_paths = [path for context in contexts for path in context.graph_paths]
    channels = _dedupe_by_key(
        (channel for context in contexts for channel in context.executed_channels),
        key=lambda channel: channel.value,
    )
    modes = {context.retrieval_mode for context in contexts}
    retrieval_mode = base.retrieval_mode if len(modes) == 1 else "hybrid"
    metrics = dict(base.metrics)
    metrics["subquery_count"] = len(contexts)

    return base.model_copy(
        update={
            "query": query,
            "retrieved_units": units,
            "evidence": evidence,
            "graph_paths": graph_paths,
            "executed_channels": channels,
            "retrieval_mode": retrieval_mode,
            "metrics": metrics,
        }
    )


def _dedupe_by_key(items, *, key):
    seen: set = set()
    result: list = []
    for item in items:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result
