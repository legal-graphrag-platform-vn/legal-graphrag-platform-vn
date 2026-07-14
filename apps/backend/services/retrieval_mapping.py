"""Pure mapping between backend DTOs and public retrieval contracts."""

from pydantic import ValidationError

from api.models import (
    EvidenceDTO,
    GraphPathDTO,
    QueryRequest,
    RetrievalResponse,
    RetrievedUnitDTO,
)
from src.retrieval.models import RetrievalContext
from src.retrieval.errors import RetrievalOutputError
from src.shared.retrieval_contract import RetrievalFilters, RetrievalRequest


def to_retrieval_request(request: QueryRequest) -> RetrievalRequest:
    return RetrievalRequest(
        query=request.query,
        filters=RetrievalFilters(
            document_ids=request.document_ids,
            query_date=request.query_date,
        ),
        top_k=request.candidate_k,
        final_k=request.top_k,
        force_intent=request.force_intent,
        enable_reranker=request.enable_reranker,
    )


def to_retrieval_response(context: RetrievalContext) -> RetrievalResponse:
    try:
        units = [_map_unit(unit.model_dump()) for unit in context.retrieved_units]
        return RetrievalResponse(
            contract_version=context.contract_version,
            query=context.query,
            intent=context.intent.value,
            strategy=context.strategy.value,
            retrieval_mode=context.retrieval_mode,
            executed_channels=[channel.value for channel in context.executed_channels],
            force_intent_used=context.force_intent_used,
            temporal_source=context.temporal_source.value,
            decision_reason_code=context.decision_reason_code.value,
            decision_reason=context.decision_reason,
            capability_status=context.capability_status,
            filters=context.filters_applied.model_dump(mode="json"),
            reranker_applied=context.reranker_applied,
            retrieved_units=units,
            graph_paths=[
                GraphPathDTO.model_validate(path.model_dump())
                for path in context.graph_paths
            ],
            evidence=[
                EvidenceDTO.model_validate(item.model_dump())
                for item in context.evidence
            ],
            metrics=dict(context.metrics),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise RetrievalOutputError(
            "Retrieval context cannot satisfy the backend response contract"
        ) from exc


def _map_unit(data: dict[str, object]) -> RetrievedUnitDTO:
    label = data.get("label")
    if label in {"Article", "Clause"} and not data.get("article_id"):
        raise RetrievalOutputError(f"{label} retrieval unit requires article_id")
    if label == "Clause" and not data.get("clause_id"):
        raise RetrievalOutputError("Clause retrieval unit requires clause_id")
    if not data.get("deep_link"):
        raise RetrievalOutputError(f"{label} retrieval unit requires deep_link")
    return RetrievedUnitDTO.model_validate(data)
