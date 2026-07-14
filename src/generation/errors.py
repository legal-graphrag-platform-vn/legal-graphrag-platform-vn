"""Typed answer-generation failures."""


class AnswerGenerationError(RuntimeError):
    pass


class AnswerRequestError(AnswerGenerationError):
    pass


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
