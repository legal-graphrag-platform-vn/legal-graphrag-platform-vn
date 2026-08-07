"""SQLAlchemy ORM models for the conversation context store (Plan 19 §3).

PostgreSQL is the source of truth for transcript and context. Six tables:
conversations, conversation_turns, conversation_messages, message_citations,
grounded_focuses and pending_clarifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.types import Uuid

from persistence.enums import (
    ClarificationMode,
    MessageKind,
    MessageRole,
    OwnerKind,
    ResolutionStatus,
    TurnStatus,
)


def _enum(python_enum: type, name: str) -> SAEnum:
    """Portable VARCHAR + CHECK enum stored by value, not by member name."""
    return SAEnum(
        python_enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
        index=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account: Mapped["Account"] = relationship(
        back_populates="user", uselist=False
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="account")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_kind: Mapped[OwnerKind] = mapped_column(
        _enum(OwnerKind, "owner_kind"),
        nullable=False,
    )
    owner_principal_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Cuộc trò chuyện mới"
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Monotonic allocator for the next user_turn_no in this conversation.
    next_user_turn_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    turns: Mapped[list["ConversationTurn"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("next_user_turn_no >= 1", name="ck_conversations_turn_no"),
        Index(
            "ix_conversations_owner_history",
            "owner_kind",
            "owner_principal_id",
            "is_deleted",
            "updated_at",
        ),
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_turn_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    user_turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TurnStatus] = mapped_column(
        _enum(TurnStatus, "turn_status"),
        nullable=False,
    )
    resolution_status: Mapped[ResolutionStatus | None] = mapped_column(
        _enum(ResolutionStatus, "resolution_status"),
        nullable=True,
    )
    resolution_reason_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    standalone_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Validated SSE replay payload; snapshot schema enforced in the repository.
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    conversation: Mapped[Conversation] = relationship(back_populates="turns")

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "client_turn_id",
            name="uq_turn_client_id",
        ),
        UniqueConstraint(
            "conversation_id",
            "user_turn_no",
            name="uq_turn_user_no",
        ),
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        _enum(MessageRole, "message_role"),
        nullable=False,
    )
    kind: Mapped[MessageKind] = mapped_column(
        _enum(MessageKind, "message_kind"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Global monotonic ordering within a conversation.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    citations: Mapped[list["MessageCitation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "ordinal",
            name="uq_message_ordinal",
        ),
    )


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id: Mapped[str] = mapped_column(String(256), nullable=False)
    citation_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    # Canonical document/unit metadata snapshot at grounding time.
    citation_label: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    article_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    clause_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    deep_link: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    message: Mapped[ConversationMessage] = relationship(back_populates="citations")

    __table_args__ = (
        UniqueConstraint("message_id", "unit_id", name="uq_citation_message_unit"),
    )


class GroundedFocus(Base):
    __tablename__ = "grounded_focuses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_label: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    article_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    clause_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    document_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_grounded_user_turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", "node_id", name="uq_focus_conv_node"),
    )


class PendingClarification(Base):
    __tablename__ = "pending_clarifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[ClarificationMode] = mapped_column(
        _enum(ClarificationMode, "clarification_mode"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # At most 5 items; JSONB schema validated on read/write in the repository.
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_pending_conversation"),
    )
