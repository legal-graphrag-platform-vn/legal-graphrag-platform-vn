"""Typed answer-generation failures."""


class AnswerGenerationError(RuntimeError):
    pass


class AnswerRequestError(AnswerGenerationError):
    pass


class EvidenceContractError(AnswerGenerationError):
    """Trusted retrieval output violates the generation input contract."""


class ContextBudgetConfigurationError(AnswerGenerationError):
    """The configured context budget cannot contain fixed prompt overhead."""


class InsufficientEvidenceError(AnswerGenerationError):
    pass


class AnswerProviderDependencyError(AnswerGenerationError):
    pass


class AnswerProviderTimeoutError(AnswerGenerationError):
    pass


class AnswerProviderOutputError(AnswerGenerationError):
    pass


class CitationValidationError(AnswerGenerationError):
    pass


class GroundingValidationError(AnswerGenerationError):
    pass


class ReasoningPathValidationError(AnswerGenerationError):
    pass


class TemporalAnswerValidationError(AnswerGenerationError):
    pass
