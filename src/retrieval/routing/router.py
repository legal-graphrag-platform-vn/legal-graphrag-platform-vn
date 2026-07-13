"""Deterministic six-intent routing with explicit temporal precedence."""

from __future__ import annotations

import re
from src.retrieval.config import RetrievalConfig
from src.retrieval.errors import (
    RetrievalRequestError,
    RetrievalRoutingError,
    TemporalRoutingError,
)
from src.retrieval.models import (
    IntentType,
    RetrievalChannel,
    RetrievalCapability,
    RetrievalDecision,
    RetrievalDecisionReasonCode,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalStrategyType,
    RoutingResult,
    TemporalQuery,
    TemporalSource,
)
from src.retrieval.ports import Clock, IntentClassifierPort
from src.retrieval.query.temporal_parser import TemporalParser


_RULES: tuple[tuple[re.Pattern[str], IntentType, RetrievalDecisionReasonCode], ...] = (
    (
        re.compile(
            r"(nhiều bước|qua nhiều|liên hệ.*(?:điều|văn bản)|dẫn chiếu|"
            r"thủ tục.*hướng dẫn)",
            re.I,
        ),
        IntentType.MULTI_HOP,
        RetrievalDecisionReasonCode.MULTI_HOP_EXPLICIT,
    ),
    (
        re.compile(
            r"(thuộc chương|thuộc điều|thuộc khoản|nằm ở chương|"
            r"văn bản nào hướng dẫn|quan hệ thứ bậc)",
            re.I,
        ),
        IntentType.HIERARCHY,
        RetrievalDecisionReasonCode.HIERARCHY_EXPLICIT,
    ),
    (
        re.compile(
            r"(là gì|\bđịnh nghĩa\b|được hiểu thế nào|thế nào là|\bkhái niệm\b)",
            re.I,
        ),
        IntentType.DEFINITION,
        RetrievalDecisionReasonCode.DEFINITION_EXPLICIT,
    ),
    (
        re.compile(r"(khác nhau|giống nhau|so sánh|trước và sau)", re.I),
        IntentType.COMPARISON,
        RetrievalDecisionReasonCode.COMPARISON_EXPLICIT,
    ),
    (
        re.compile(
            r"(sửa đổi|bãi bỏ|thay thế|hết hiệu lực|"
            r"(?:có|đang có|còn) hiệu lực)",
            re.I,
        ),
        IntentType.VALIDITY,
        RetrievalDecisionReasonCode.VALIDITY_EXPLICIT_DATE,
    ),
)


class IntentRouter:
    def __init__(
        self,
        config: RetrievalConfig,
        *,
        temporal_parser: TemporalParser | None = None,
        classifier: IntentClassifierPort | None = None,
        clock: Clock,
    ) -> None:
        self._config = config
        self._temporal_parser = temporal_parser or TemporalParser()
        self._classifier = classifier
        self._clock = clock

    def route(self, request: RetrievalRequest) -> RoutingResult:
        if len(request.query) > self._config.query_max_length:
            raise RetrievalRequestError(
                f"Query exceeds configured maximum of {self._config.query_max_length}"
            )

        temporal = self._temporal_parser.parse(request.query)
        if temporal.parse_error:
            raise TemporalRoutingError(temporal.parse_error)

        temporal, temporal_source, filters = self._resolve_temporal(
            request.filters, temporal
        )
        intent, reason_code, reason = self._resolve_intent(request)
        if intent is IntentType.VALIDITY and temporal.resolved_from is None:
            raise TemporalRoutingError(
                "Validity retrieval requires a resolved temporal point"
            )
        if intent is IntentType.COMPARISON and not temporal.has_temporal:
            raise TemporalRoutingError(
                "Comparison retrieval requires a temporal expression"
            )

        candidate_k = request.top_k or self._config.candidate_k
        final_k = request.final_k or self._config.final_k
        if not 1 <= final_k <= candidate_k <= 200:
            raise RetrievalRequestError("Require 1 <= final_k <= candidate_k <= 200")
        graph_entry_k = min(self._config.graph_entry_k, candidate_k)

        strategy = _strategy_for(intent)
        channels = self._seed_channels(intent)
        if not channels:
            raise RetrievalRoutingError("Intent has no enabled seed retrieval channel")
        enable_reranker = (
            request.enable_reranker
            if request.enable_reranker is not None
            else self._config.reranker_enabled
        )
        if intent is IntentType.HIERARCHY and request.enable_reranker is None:
            enable_reranker = False

        return RoutingResult(
            decision=RetrievalDecision(
                contract_version=self._config.contract_version,
                intent=intent,
                strategy=strategy,
                seed_channels=channels,
                graph_enabled=self._config.graph_enabled,
                graph_policy_intent=intent if self._config.graph_enabled else None,
                candidate_k=candidate_k,
                graph_entry_k=graph_entry_k,
                final_k=final_k,
                apply_temporal_filter=temporal.resolved_from is not None,
                preserve_versions=intent is IntentType.COMPARISON,
                require_temporal_point=intent is IntentType.VALIDITY,
                enable_reranker=enable_reranker,
                force_intent_used=request.force_intent is not None,
                temporal_source=temporal_source,
                decision_reason_code=reason_code,
                decision_reason=reason,
                required_capability=_required_capability(
                    intent, request.query, temporal_source
                ),
            ),
            temporal=temporal,
            filters=filters,
        )

    def _resolve_intent(
        self, request: RetrievalRequest
    ) -> tuple[IntentType, RetrievalDecisionReasonCode, str]:
        if request.force_intent is not None:
            return (
                request.force_intent,
                RetrievalDecisionReasonCode.FORCED_INTENT,
                f"Intent explicitly forced to {request.force_intent.value}",
            )
        intent, reason_code = classify_intent_by_rule(request.query)
        if intent is not None and reason_code is not None:
            return intent, reason_code, f"Matched deterministic {intent.value} rule"
        if self._classifier is not None:
            classified = self._classifier.classify(request.query)
            return (
                classified,
                _reason_for(classified),
                f"Intent classifier selected {classified.value}",
            )
        return (
            IntentType.FACTUAL,
            RetrievalDecisionReasonCode.FACTUAL_DEFAULT,
            "No explicit non-factual intent marker was found",
        )

    def _resolve_temporal(
        self, request_filters: RetrievalFilters, temporal: TemporalQuery
    ) -> tuple[TemporalQuery, TemporalSource, RetrievalFilters]:
        request_date = request_filters.query_date
        parsed_date = temporal.resolved_from
        if request_date and parsed_date and request_date != parsed_date:
            raise TemporalRoutingError(
                "Request query_date conflicts with the temporal expression in query"
            )
        if request_date is not None:
            resolved = temporal.model_copy(
                update={
                    "has_temporal": True,
                    "resolved_from": request_date,
                    "resolved_to": request_date,
                    "granularity": "day",
                }
            )
            return resolved, TemporalSource.REQUEST, request_filters
        if parsed_date is not None:
            return (
                temporal,
                TemporalSource.QUERY_EXPRESSION,
                request_filters.model_copy(update={"query_date": parsed_date}),
            )
        if temporal.requests_current_validity:
            current = self._clock.today()
            resolved = temporal.model_copy(
                update={
                    "has_temporal": True,
                    "resolved_from": current,
                    "resolved_to": current,
                    "granularity": "day",
                }
            )
            return (
                resolved,
                TemporalSource.INJECTED_CURRENT_DATE,
                request_filters.model_copy(update={"query_date": current}),
            )
        return temporal, TemporalSource.NONE, request_filters

    def _seed_channels(self, intent: IntentType) -> tuple[RetrievalChannel, ...]:
        channels: list[RetrievalChannel] = []
        fulltext_first = intent in {
            IntentType.DEFINITION,
            IntentType.VALIDITY,
            IntentType.HIERARCHY,
        }
        order = (
            (RetrievalChannel.FULLTEXT, RetrievalChannel.VECTOR)
            if fulltext_first
            else (RetrievalChannel.VECTOR, RetrievalChannel.FULLTEXT)
        )
        for channel in order:
            if channel is RetrievalChannel.VECTOR:
                if not self._config.vector_enabled:
                    continue
                if (
                    intent is IntentType.HIERARCHY
                    and not self._config.hierarchy_vector_enabled
                ):
                    continue
            if (
                channel is RetrievalChannel.FULLTEXT
                and not self._config.fulltext_enabled
            ):
                continue
            channels.append(channel)
        return tuple(channels)


def classify_intent_by_rule(
    query: str,
) -> tuple[IntentType | None, RetrievalDecisionReasonCode | None]:
    for pattern, intent, reason in _RULES:
        if pattern.search(query):
            if intent is IntentType.VALIDITY and re.search(
                r"(hiện hành|hiện nay|đang có hiệu lực|còn hiệu lực)", query, re.I
            ):
                return intent, RetrievalDecisionReasonCode.VALIDITY_CURRENT_DATE
            return intent, reason
    return None, None


def _strategy_for(intent: IntentType) -> RetrievalStrategyType:
    return {
        IntentType.FACTUAL: RetrievalStrategyType.FACTUAL_HYBRID,
        IntentType.DEFINITION: RetrievalStrategyType.DEFINITION_GRAPH,
        IntentType.VALIDITY: RetrievalStrategyType.VALIDITY_TEMPORAL,
        IntentType.HIERARCHY: RetrievalStrategyType.HIERARCHY_GRAPH,
        IntentType.COMPARISON: RetrievalStrategyType.COMPARISON_TEMPORAL,
        IntentType.MULTI_HOP: RetrievalStrategyType.MULTI_HOP_HYBRID,
    }[intent]


def _reason_for(intent: IntentType) -> RetrievalDecisionReasonCode:
    return {
        IntentType.FACTUAL: RetrievalDecisionReasonCode.FACTUAL_DEFAULT,
        IntentType.DEFINITION: RetrievalDecisionReasonCode.DEFINITION_EXPLICIT,
        IntentType.VALIDITY: RetrievalDecisionReasonCode.VALIDITY_EXPLICIT_DATE,
        IntentType.HIERARCHY: RetrievalDecisionReasonCode.HIERARCHY_EXPLICIT,
        IntentType.COMPARISON: RetrievalDecisionReasonCode.COMPARISON_EXPLICIT,
        IntentType.MULTI_HOP: RetrievalDecisionReasonCode.MULTI_HOP_EXPLICIT,
    }[intent]


def _required_capability(
    intent: IntentType, query: str, temporal_source: TemporalSource
) -> RetrievalCapability | None:
    if intent is IntentType.VALIDITY:
        if re.search(r"(sửa đổi|bãi bỏ|thay thế)", query, re.I):
            return RetrievalCapability.VERSION_CHAIN_VALIDITY
        if temporal_source is TemporalSource.INJECTED_CURRENT_DATE:
            return RetrievalCapability.CORPUS_COMPLETE_CURRENT_VALIDITY
        return RetrievalCapability.SCOPED_TEMPORAL_METADATA
    if intent is IntentType.HIERARCHY:
        return (
            RetrievalCapability.GUIDES_RELATIONS
            if re.search(r"văn bản.*hướng dẫn", query, re.I)
            else RetrievalCapability.STRUCTURAL_HIERARCHY
        )
    if intent is IntentType.COMPARISON:
        return RetrievalCapability.MULTIPLE_VERSIONS
    if intent is IntentType.DEFINITION:
        return RetrievalCapability.LEXICAL_DEFINITION
    if intent is IntentType.MULTI_HOP:
        return RetrievalCapability.SEMANTIC_MULTI_HOP_GRAPH
    return None
