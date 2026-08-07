"""Persisted lifecycle enums for the conversation context store (Plan 19)."""

from __future__ import annotations

from enum import Enum


class OwnerKind(str, Enum):
    ANONYMOUS = "ANONYMOUS"
    USER = "USER"


class TurnStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    CANNOT_ANSWER = "CANNOT_ANSWER"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAILED = "FAILED"


# Terminal statuses whose persisted snapshot can be replayed verbatim.
REPLAYABLE_TURN_STATUSES = frozenset(
    {
        TurnStatus.COMPLETED,
        TurnStatus.CANNOT_ANSWER,
        TurnStatus.NEEDS_CLARIFICATION,
    }
)


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageKind(str, Enum):
    USER_QUERY = "USER_QUERY"
    ANSWER = "ANSWER"
    CANNOT_ANSWER = "CANNOT_ANSWER"
    CLARIFICATION = "CLARIFICATION"
    SMALL_TALK = "SMALL_TALK"


class ClarificationMode(str, Enum):
    SELECT = "SELECT"
    RESTATE = "RESTATE"
