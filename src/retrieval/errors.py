"""Typed retrieval failures exposed by runtime and CLI boundaries."""


class RetrievalError(RuntimeError):
    """Base class for expected retrieval contract failures."""


class RetrievalRequestError(RetrievalError):
    pass


class CanonicalReferenceUnavailableError(RetrievalRequestError):
    """A server-resolved anchor is absent under the active retrieval scope."""


class IntentAnalysisError(RetrievalError):
    pass


class RetrievalRoutingError(RetrievalError):
    pass


class TemporalRoutingError(RetrievalRoutingError):
    pass


class RetrievalCapabilityError(RetrievalError):
    def __init__(
        self,
        message: str,
        *,
        required_capability: str,
        available_capability: str,
    ) -> None:
        super().__init__(message)
        self.required_capability = required_capability
        self.available_capability = available_capability


class RetrievalDependencyError(RetrievalError):
    pass


class RetrievalExecutionError(RetrievalError):
    pass


class RetrievalOutputError(RetrievalError):
    pass


class QueryProcessingError(RetrievalError):
    """Base class for query-processing failures upstream of retrieval."""


class QueryProcessingParseError(QueryProcessingError):
    """The LLM output could not be recovered into a JSON object.

    The offending payload is preserved on ``raw_output`` for diagnostics; the
    error is raised (never swallowed) so the caller decides how to react.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class QueryProcessingContractError(QueryProcessingError):
    """Parsed JSON violated the five-field query-processing contract."""
