"""Central FastAPI error mapping for retrieval and request contracts."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.models import APIErrorResponse, ValidationIssue
from services.errors import (
    BackendFeatureUnavailableError,
    BackendRetrievalClosedError,
    BackendRetrievalTimeoutError,
)
from src.generation.errors import (
    AnswerGenerationError,
    AnswerProviderDependencyError,
    AnswerProviderOutputError,
    AnswerProviderTimeoutError,
    AnswerRequestError,
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)
from src.retrieval.errors import (
    IntentAnalysisError,
    RetrievalCapabilityError,
    RetrievalDependencyError,
    RetrievalError,
    RetrievalExecutionError,
    RetrievalOutputError,
    RetrievalRequestError,
    RetrievalRoutingError,
    TemporalRoutingError,
)


logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(RetrievalError, retrieval_error_handler)
    app.add_exception_handler(AnswerGenerationError, answer_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)


async def request_validation_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    validation_error = _require_validation_error(exc)
    details = [
        ValidationIssue(
            location=list(error.get("loc", ())),
            message=str(error.get("msg", "Invalid request")),
            error_type=str(error.get("type", "value_error")),
        )
        for error in validation_error.errors()
    ]
    return _response(
        status_code=422,
        code="REQUEST_VALIDATION_ERROR",
        message="Request validation failed",
        request=request,
        details=details,
    )


async def retrieval_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    error = _require_retrieval_error(exc)
    status_code, code = _retrieval_error_contract(error)
    details: dict[str, object] = {}
    if isinstance(error, RetrievalCapabilityError):
        details = {
            "required_capability": error.required_capability,
            "available_capability": error.available_capability,
        }
    logger.warning(
        "Backend retrieval request failed: code=%s error_type=%s",
        code,
        type(error).__name__,
    )
    return _response(
        status_code=status_code,
        code=code,
        message=str(error),
        request=request,
        details=details,
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unexpected backend failure: error_type=%s",
        type(exc).__name__,
        exc_info=True,
    )
    return _response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected internal error occurred",
        request=request,
        details={},
    )


async def answer_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AnswerGenerationError):
        raise TypeError("Expected AnswerGenerationError")
    status_code, code = _answer_error_contract(exc)
    logger.warning(
        "Backend answer request failed: code=%s error_type=%s",
        code,
        type(exc).__name__,
    )
    return _response(
        status_code=status_code,
        code=code,
        message="Answer generation failed validation or dependency checks",
        request=request,
        details={},
    )


def _retrieval_error_contract(error: RetrievalError) -> tuple[int, str]:
    if isinstance(error, BackendRetrievalTimeoutError):
        return 504, "RETRIEVAL_TIMEOUT"
    if isinstance(error, BackendFeatureUnavailableError):
        return 501, "FEATURE_NOT_IMPLEMENTED"
    if isinstance(error, BackendRetrievalClosedError):
        return 503, "RETRIEVAL_SERVICE_UNAVAILABLE"
    if isinstance(error, RetrievalCapabilityError):
        return 409, "RETRIEVAL_CAPABILITY_UNSUPPORTED"
    if isinstance(error, RetrievalDependencyError):
        return 503, "RETRIEVAL_DEPENDENCY_UNAVAILABLE"
    if isinstance(error, RetrievalExecutionError):
        return 502, "RETRIEVAL_EXECUTION_FAILED"
    if isinstance(error, RetrievalOutputError):
        return 500, "RETRIEVAL_OUTPUT_INVALID"
    if isinstance(error, TemporalRoutingError):
        return 422, "TEMPORAL_ROUTING_INVALID"
    if isinstance(error, IntentAnalysisError):
        return 422, "INTENT_ANALYSIS_INVALID"
    if isinstance(error, (RetrievalRequestError, RetrievalRoutingError)):
        return 422, "RETRIEVAL_REQUEST_INVALID"
    return 500, "RETRIEVAL_ERROR"


def _answer_error_contract(error: AnswerGenerationError) -> tuple[int, str]:
    if isinstance(error, AnswerProviderTimeoutError):
        return 504, "ANSWER_PROVIDER_TIMEOUT"
    if isinstance(error, AnswerProviderDependencyError):
        return 503, "ANSWER_PROVIDER_UNAVAILABLE"
    if isinstance(error, AnswerRequestError):
        return 422, "ANSWER_REQUEST_INVALID"
    if isinstance(error, AnswerProviderOutputError):
        return 502, "ANSWER_PROVIDER_OUTPUT_INVALID"
    if isinstance(error, CitationValidationError):
        return 502, "ANSWER_CITATION_INVALID"
    if isinstance(error, ReasoningPathValidationError):
        return 502, "ANSWER_PATH_INVALID"
    if isinstance(error, TemporalAnswerValidationError):
        return 502, "ANSWER_TEMPORAL_INVALID"
    if isinstance(error, GroundingValidationError):
        return 502, "ANSWER_GROUNDING_INVALID"
    return 500, "ANSWER_GENERATION_ERROR"


def stream_error_contract(error: Exception) -> tuple[str, str]:
    if isinstance(error, AnswerGenerationError):
        _, code = _answer_error_contract(error)
        return code, "Không thể tạo câu trả lời có căn cứ."
    if isinstance(error, RetrievalError):
        _, code = _retrieval_error_contract(error)
        return code, "Không thể truy xuất căn cứ pháp lý."
    return "STREAM_ERROR", "Đã xảy ra lỗi nội bộ."


def _response(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: list[ValidationIssue] | dict[str, object],
) -> JSONResponse:
    request_id = request.headers.get("x-request-id")
    payload = APIErrorResponse(
        code=code,
        message=message,
        request_id=request_id,
        details=details,
    )
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json")
    )


def _require_validation_error(exc: Exception) -> RequestValidationError:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("Expected RequestValidationError")
    return exc


def _require_retrieval_error(exc: Exception) -> RetrievalError:
    if not isinstance(exc, RetrievalError):
        raise TypeError("Expected RetrievalError")
    return exc
