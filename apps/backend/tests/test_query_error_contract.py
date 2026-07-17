from __future__ import annotations

import asyncio

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError

from api.error_handlers import (
    answer_error_handler,
    internal_error_handler,
    request_validation_handler,
    retrieval_error_handler,
    stream_error_contract,
)
from src.generation.errors import (
    AnswerProviderDependencyError,
    AnswerProviderOutputError,
    AnswerProviderTimeoutError,
    CitationValidationError,
    ContextBudgetConfigurationError,
    EvidenceContractError,
)
from api.models import QueryRequest
from api.routes.query import query
from services.errors import BackendRetrievalTimeoutError
from src.retrieval.errors import (
    IntentAnalysisError,
    RetrievalCapabilityError,
    RetrievalDependencyError,
    RetrievalExecutionError,
    TemporalRoutingError,
)
from tests.factories import retrieval_context
from services.retrieval_mapping import to_retrieval_response


class FakeQueryService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[QueryRequest] = []

    async def retrieve(self, request: QueryRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return to_retrieval_response(
            retrieval_context(no_results=request.query == "none")
        )


def test_query_route_delegates_once_and_returns_no_results() -> None:
    async def scenario() -> None:
        service = FakeQueryService()
        request = QueryRequest(query="none")
        response = await query(request=request, service=service)
        assert response.capability_status == "no_results"
        assert len(service.requests) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (BackendRetrievalTimeoutError("slow"), 504, "RETRIEVAL_TIMEOUT"),
        (
            RetrievalCapabilityError(
                "unsupported",
                required_capability="multiple_versions",
                available_capability="single_version",
            ),
            409,
            "RETRIEVAL_CAPABILITY_UNSUPPORTED",
        ),
        (
            RetrievalDependencyError("database unavailable"),
            503,
            "RETRIEVAL_DEPENDENCY_UNAVAILABLE",
        ),
        (
            RetrievalExecutionError("query failed"),
            502,
            "RETRIEVAL_EXECUTION_FAILED",
        ),
        (
            TemporalRoutingError("conflicting dates"),
            422,
            "TEMPORAL_ROUTING_INVALID",
        ),
        (
            IntentAnalysisError("invalid intent"),
            422,
            "INTENT_ANALYSIS_INVALID",
        ),
    ],
)
def test_typed_error_mapping(error: Exception, status: int, code: str) -> None:
    response = asyncio.run(retrieval_error_handler(_request(), error))
    assert response.status_code == status
    assert f'"code":"{code}"' in response.body.decode()
    assert "Traceback" not in response.body.decode()


def test_capability_error_exposes_safe_capability_details() -> None:
    error = RetrievalCapabilityError(
        "unsupported",
        required_capability="multiple_versions",
        available_capability="single_version",
    )
    response = asyncio.run(retrieval_error_handler(_request(), error))
    body = response.body.decode()
    assert '"required_capability":"multiple_versions"' in body
    assert '"available_capability":"single_version"' in body


def test_request_validation_uses_stable_error_envelope() -> None:
    try:
        QueryRequest.model_validate({"query": "x", "document_ids": ["doc", "doc"]})
    except ValueError as exc:
        validation_error = RequestValidationError(exc.errors())
    else:
        raise AssertionError("Expected request validation failure")

    response = asyncio.run(request_validation_handler(_request(), validation_error))
    body = response.body.decode()
    assert response.status_code == 422
    assert '"code":"REQUEST_VALIDATION_ERROR"' in body
    assert '"details":[' in body


def test_unexpected_error_does_not_leak_internal_details() -> None:
    response = asyncio.run(
        internal_error_handler(_request(), RuntimeError("secret-password"))
    )
    body = response.body.decode()
    assert response.status_code == 500
    assert '"code":"INTERNAL_ERROR"' in body
    assert "secret-password" not in body


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AnswerProviderTimeoutError("slow"), 504, "ANSWER_PROVIDER_TIMEOUT"),
        (
            AnswerProviderOutputError("malformed-secret"),
            502,
            "ANSWER_PROVIDER_OUTPUT_INVALID",
        ),
        (
            CitationValidationError("hallucinated-id"),
            502,
            "ANSWER_CITATION_INVALID",
        ),
        (
            EvidenceContractError("malformed-evidence"),
            500,
            "ANSWER_EVIDENCE_CONTRACT_INVALID",
        ),
        (
            ContextBudgetConfigurationError("invalid-budget"),
            500,
            "ANSWER_CONTEXT_BUDGET_INVALID",
        ),
    ],
)
def test_answer_error_mapping_is_typed_and_safe(
    error: Exception,
    status: int,
    code: str,
) -> None:
    response = asyncio.run(answer_error_handler(_request(), error))
    body = response.body.decode()
    assert response.status_code == status
    assert f'"code":"{code}"' in body
    assert str(error) not in body


def test_stream_error_contract_uses_stable_code() -> None:
    code, message = stream_error_contract(CitationValidationError("hallucinated-id"))
    assert code == "ANSWER_CITATION_INVALID"
    assert "hallucinated-id" not in message


def test_stream_error_contract_reports_provider_unavailability() -> None:
    code, message = stream_error_contract(
        AnswerProviderDependencyError("provider-secret")
    )
    assert code == "ANSWER_PROVIDER_UNAVAILABLE"
    assert "đang quá tải" in message
    assert "provider-secret" not in message


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/query",
            "headers": [(b"x-request-id", b"request-1")],
        }
    )
