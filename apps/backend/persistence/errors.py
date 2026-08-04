"""Typed errors for the conversation context store (Plan 19)."""

from __future__ import annotations


class ConversationStoreError(Exception):
    """Base class for conversation persistence errors."""


class ConversationNotFoundError(ConversationStoreError):
    """Conversation is missing or owned by a different principal.

    The message never reveals whether the id exists for another owner.
    """

    error_code = "CONVERSATION_NOT_FOUND"


class ConversationBusyError(ConversationStoreError):
    """Advisory lock could not be acquired before the deadline."""

    error_code = "CONVERSATION_BUSY"


class InvalidClarificationCandidatesError(ConversationStoreError):
    """Persisted clarification candidates failed schema validation."""

    error_code = "INVALID_CLARIFICATION_CANDIDATES"


class TurnSnapshotError(ConversationStoreError):
    """A persisted turn is missing the snapshot required to replay it."""

    error_code = "TURN_SNAPSHOT_MISSING"
