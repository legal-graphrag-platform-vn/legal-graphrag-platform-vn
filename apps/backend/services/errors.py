"""Backend retrieval boundary errors with stable API semantics."""

from src.retrieval.errors import RetrievalError


class BackendRetrievalTimeoutError(RetrievalError):
    pass


class BackendRetrievalClosedError(RetrievalError):
    pass


class BackendFeatureUnavailableError(RetrievalError):
    pass
