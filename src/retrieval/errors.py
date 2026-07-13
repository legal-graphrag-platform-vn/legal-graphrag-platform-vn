"""Typed retrieval failures exposed by runtime and CLI boundaries."""


class RetrievalError(RuntimeError):
    """Base class for expected retrieval contract failures."""


class RetrievalRequestError(RetrievalError):
    pass


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
