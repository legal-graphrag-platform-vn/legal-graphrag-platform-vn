"""SQLAlchemy conversation context repository (Plan 19 §3-§4).

Concurrency contract:

    acquire session-level advisory lock
    -> short begin-turn transaction -> commit
    -> retrieval/generation happen OUTSIDE any transaction (caller)
    -> short finalize transaction -> commit
    -> release advisory lock in finally, returning the connection to the pool

No SQL transaction stays open during Neo4j/Gemini calls. Every operation is
owner-scoped; a conversation owned by another principal is reported as missing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from persistence.domain import (
    BegunTurn,
    CitationSnapshot,
    ClarificationCandidate,
    FocusUpsert,
    GroundedFocus,
    HistoryContext,
    HistoryMessage,
    Owner,
    PendingClarification,
    TurnRecord,
    candidates_from_json,
    candidates_to_json,
    validate_candidates,
)
from conversation.title import derive_title
from persistence.enums import (
    ClarificationMode,
    MessageKind,
    MessageRole,
    ResolutionStatus,
    TurnStatus,
)
from persistence.errors import (
    ConversationBusyError,
    ConversationNotFoundError,
    TurnSnapshotError,
)
from persistence.lock import (
    acquire_with_deadline,
    advisory_unlock,
    conversation_lock_key,
)
from persistence.models import (
    Account,
    Conversation,
    ConversationMessage,
    ConversationTurn,
    GroundedFocus as GroundedFocusModel,
    MessageCitation,
    PendingClarification as PendingClarificationModel,
    User,
)

# Focus policy (Plan 19 §4).
MAX_GROUNDED_FOCUSES = 5
FOCUS_TTL_USER_TURNS = 5
# Effective recent history (Plan 19 §4).
MAX_RECENT_MESSAGES = 6
MAX_RECENT_HISTORY_CHARS = 4000

_COMPLETED_TURN_STATUSES = (
    TurnStatus.COMPLETED,
    TurnStatus.CANNOT_ANSWER,
    TurnStatus.NEEDS_CLARIFICATION,
)

_usr_t = User.__table__
_acc_t = Account.__table__
_conv_t = Conversation.__table__
_turn_t = ConversationTurn.__table__
_msg_t = ConversationMessage.__table__
_cit_t = MessageCitation.__table__
_focus_t = GroundedFocusModel.__table__
_pend_t = PendingClarificationModel.__table__


class LockedTurnPort(Protocol):
    async def find_turn_by_client_id(
        self, client_turn_id: uuid.UUID
    ) -> TurnRecord | None: ...

    async def begin_turn_and_load_context(
        self, *, client_turn_id: uuid.UUID, user_message: str
    ) -> BegunTurn: ...

    async def persist_clarification(
        self,
        *,
        turn_id: uuid.UUID,
        mode: ClarificationMode,
        question: str,
        candidates: tuple[ClarificationCandidate, ...],
        resolution_status: ResolutionStatus,
        resolution_reason_code: str | None,
        response_snapshot: dict[str, Any],
    ) -> None: ...

    async def persist_grounded_answer(
        self,
        *,
        turn_id: uuid.UUID,
        user_turn_no: int,
        status: TurnStatus,
        kind: MessageKind,
        content: str,
        standalone_query: str,
        resolution_status: ResolutionStatus,
        resolution_reason_code: str | None,
        citations: tuple[CitationSnapshot, ...],
        focus_upserts: tuple[FocusUpsert, ...],
        update_focus: bool,
        response_snapshot: dict[str, Any],
    ) -> None: ...

    async def mark_turn_failed(
        self,
        *,
        turn_id: uuid.UUID,
        error_code: str,
        response_snapshot: dict[str, Any],
    ) -> None: ...

    async def clear_pending(self) -> None: ...


class ConversationStorePort(Protocol):
    async def find_turn_by_client_id(
        self,
        *,
        conversation_id: uuid.UUID,
        owner: Owner,
        client_turn_id: uuid.UUID,
    ) -> TurnRecord | None: ...

    async def replay_turn(
        self,
        *,
        conversation_id: uuid.UUID,
        owner: Owner,
        client_turn_id: uuid.UUID,
    ) -> dict[str, Any]: ...

    def locked_turn(
        self, *, conversation_id: uuid.UUID, owner: Owner
    ) -> "AbstractAsyncLockedTurn": ...


class AbstractAsyncLockedTurn(Protocol):
    async def __aenter__(self) -> LockedTurnPort: ...

    async def __aexit__(self, *exc: object) -> None: ...


def _to_turn_record(row: Any) -> TurnRecord:
    return TurnRecord(
        turn_id=row.id,
        conversation_id=row.conversation_id,
        client_turn_id=row.client_turn_id,
        user_turn_no=row.user_turn_no,
        status=row.status,
        resolution_status=row.resolution_status,
        resolution_reason_code=row.resolution_reason_code,
        standalone_query=row.standalone_query,
        error_code=row.error_code,
        response_snapshot=row.response_snapshot,
        created_at=row.created_at,
    )


async def _load_owned_conversation(
    conn: AsyncConnection,
    conversation_id: uuid.UUID,
    owner: Owner,
    *,
    for_update: bool = False,
) -> Any | None:
    stmt = select(_conv_t).where(_conv_t.c.id == conversation_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await conn.execute(stmt)).mappings().first()
    if row is None:
        return None
    if (
        row["owner_principal_id"] != owner.owner_principal_id
        or row["owner_kind"] != owner.owner_kind
    ):
        raise ConversationNotFoundError("Conversation not found")
    return row


async def _next_ordinal(conn: AsyncConnection, conversation_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(_msg_t.c.ordinal), 0)).where(
        _msg_t.c.conversation_id == conversation_id
    )
    return int((await conn.execute(stmt)).scalar_one()) + 1


class LockedTurn:
    """Operations that run while the per-conversation advisory lock is held."""

    def __init__(
        self,
        conn: AsyncConnection,
        *,
        conversation_id: uuid.UUID,
        owner: Owner,
    ) -> None:
        self._conn = conn
        self._conversation_id = conversation_id
        self._owner = owner

    async def find_turn_by_client_id(
        self, client_turn_id: uuid.UUID
    ) -> TurnRecord | None:
        stmt = select(_turn_t).where(
            _turn_t.c.conversation_id == self._conversation_id,
            _turn_t.c.client_turn_id == client_turn_id,
        )
        # Wrap the read so it does not leave an autobegun transaction open on the
        # locked connection ahead of the begin-turn transaction.
        async with self._conn.begin():
            row = (await self._conn.execute(stmt)).mappings().first()
        return _to_turn_record(row) if row is not None else None

    async def begin_turn_and_load_context(
        self, *, client_turn_id: uuid.UUID, user_message: str
    ) -> BegunTurn:
        async with self._conn.begin():
            conversation = await _load_owned_conversation(
                self._conn,
                self._conversation_id,
                self._owner,
                for_update=True,
            )
            if conversation is None:
                user_turn_no = 1
                initial_title = (
                    user_message[:50].strip()
                    if user_message and user_message.strip()
                    else "Cuộc trò chuyện mới"
                )
                await self._conn.execute(
                    _conv_t.insert().values(
                        id=self._conversation_id,
                        owner_kind=self._owner.owner_kind,
                        owner_principal_id=self._owner.owner_principal_id,
                        title=initial_title,
                        next_user_turn_no=user_turn_no + 1,
                    )
                )
            else:
                user_turn_no = int(conversation["next_user_turn_no"])
                title_update = {}
                if (
                    (
                        conversation.get("title") == "Cuộc trò chuyện mới"
                        or not conversation.get("title")
                    )
                    and user_message
                    and user_message.strip()
                ):
                    title_update["title"] = user_message[:50].strip()
                await self._conn.execute(
                    update(_conv_t)
                    .where(_conv_t.c.id == self._conversation_id)
                    .values(next_user_turn_no=user_turn_no + 1, **title_update)
                )

            turn_id = uuid.uuid4()
            await self._conn.execute(
                _turn_t.insert().values(
                    id=turn_id,
                    conversation_id=self._conversation_id,
                    client_turn_id=client_turn_id,
                    user_turn_no=user_turn_no,
                    status=TurnStatus.PROCESSING,
                )
            )
            ordinal = await _next_ordinal(self._conn, self._conversation_id)
            await self._conn.execute(
                _msg_t.insert().values(
                    id=uuid.uuid4(),
                    turn_id=turn_id,
                    conversation_id=self._conversation_id,
                    role=MessageRole.USER,
                    kind=MessageKind.USER_QUERY,
                    content=user_message,
                    ordinal=ordinal,
                )
            )
            context = await self._load_context(
                current_turn_id=turn_id,
                current_user_turn_no=user_turn_no,
            )
            return BegunTurn(
                turn_id=turn_id,
                conversation_id=self._conversation_id,
                user_turn_no=user_turn_no,
                user_message_ordinal=ordinal,
                context=context,
            )

    async def persist_clarification(
        self,
        *,
        turn_id: uuid.UUID,
        mode: ClarificationMode,
        question: str,
        candidates: tuple[ClarificationCandidate, ...],
        resolution_status: ResolutionStatus,
        resolution_reason_code: str | None,
        response_snapshot: dict[str, Any],
    ) -> None:
        payload = candidates_to_json(validate_candidates(candidates))
        async with self._conn.begin():
            ordinal = await _next_ordinal(self._conn, self._conversation_id)
            await self._conn.execute(
                _msg_t.insert().values(
                    id=uuid.uuid4(),
                    turn_id=turn_id,
                    conversation_id=self._conversation_id,
                    role=MessageRole.ASSISTANT,
                    kind=MessageKind.CLARIFICATION,
                    content=question,
                    ordinal=ordinal,
                )
            )
            upsert = pg_insert(_pend_t).values(
                id=uuid.uuid4(),
                conversation_id=self._conversation_id,
                source_turn_id=turn_id,
                mode=mode,
                question=question,
                candidates=payload,
            )
            await self._conn.execute(
                upsert.on_conflict_do_update(
                    index_elements=[_pend_t.c.conversation_id],
                    set_={
                        "source_turn_id": turn_id,
                        "mode": mode,
                        "question": question,
                        "candidates": payload,
                        "updated_at": func.now(),
                    },
                )
            )
            await self._conn.execute(
                update(_turn_t)
                .where(_turn_t.c.id == turn_id)
                .values(
                    status=TurnStatus.NEEDS_CLARIFICATION,
                    resolution_status=resolution_status,
                    resolution_reason_code=resolution_reason_code,
                    standalone_query=None,
                    response_snapshot=response_snapshot,
                )
            )

    async def persist_grounded_answer(
        self,
        *,
        turn_id: uuid.UUID,
        user_turn_no: int,
        status: TurnStatus,
        kind: MessageKind,
        content: str,
        standalone_query: str,
        resolution_status: ResolutionStatus,
        resolution_reason_code: str | None,
        citations: tuple[CitationSnapshot, ...],
        focus_upserts: tuple[FocusUpsert, ...],
        update_focus: bool,
        response_snapshot: dict[str, Any],
    ) -> None:
        async with self._conn.begin():
            ordinal = await _next_ordinal(self._conn, self._conversation_id)
            message_id = uuid.uuid4()
            await self._conn.execute(
                _msg_t.insert().values(
                    id=message_id,
                    turn_id=turn_id,
                    conversation_id=self._conversation_id,
                    role=MessageRole.ASSISTANT,
                    kind=kind,
                    content=content,
                    ordinal=ordinal,
                )
            )
            if citations:
                await self._conn.execute(
                    _cit_t.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "message_id": message_id,
                            "conversation_id": self._conversation_id,
                            "unit_id": citation.unit_id,
                            "citation_ordinal": citation.citation_ordinal,
                            "citation_label": citation.citation_label,
                            "document_id": citation.document_id,
                            "article_id": citation.article_id,
                            "clause_id": citation.clause_id,
                            "deep_link": citation.deep_link,
                            "metadata_snapshot": citation.metadata or None,
                        }
                        for citation in citations
                    ],
                )
            # Clearing pending is unconditional: a resolved answer ends any
            # outstanding clarification for this conversation.
            await self._conn.execute(
                delete(_pend_t).where(
                    _pend_t.c.conversation_id == self._conversation_id
                )
            )
            if update_focus and focus_upserts:
                await self._upsert_focuses(focus_upserts, user_turn_no=user_turn_no)
                await self._prune_focuses()
            await self._conn.execute(
                update(_turn_t)
                .where(_turn_t.c.id == turn_id)
                .values(
                    status=status,
                    resolution_status=resolution_status,
                    resolution_reason_code=resolution_reason_code,
                    standalone_query=standalone_query,
                    response_snapshot=response_snapshot,
                )
            )

    async def mark_turn_failed(
        self,
        *,
        turn_id: uuid.UUID,
        error_code: str,
        response_snapshot: dict[str, Any],
    ) -> None:
        async with self._conn.begin():
            await self._conn.execute(
                update(_turn_t)
                .where(_turn_t.c.id == turn_id)
                .values(
                    status=TurnStatus.FAILED,
                    error_code=error_code,
                    response_snapshot=response_snapshot,
                )
            )

    async def clear_pending(self) -> None:
        async with self._conn.begin():
            await self._conn.execute(
                delete(_pend_t).where(
                    _pend_t.c.conversation_id == self._conversation_id
                )
            )

    # -- internal helpers --------------------------------------------------- #

    async def _upsert_focuses(
        self, focus_upserts: tuple[FocusUpsert, ...], *, user_turn_no: int
    ) -> None:
        for focus in focus_upserts:
            upsert = pg_insert(_focus_t).values(
                id=uuid.uuid4(),
                conversation_id=self._conversation_id,
                node_id=focus.node_id,
                node_type=focus.node_type,
                document_type=focus.document_type,
                canonical_label=focus.canonical_label,
                document_id=focus.document_id,
                article_id=focus.article_id,
                clause_id=focus.clause_id,
                document_metadata=focus.document_metadata or None,
                last_grounded_user_turn_no=user_turn_no,
                citation_order=focus.citation_order,
            )
            await self._conn.execute(
                upsert.on_conflict_do_update(
                    index_elements=[
                        _focus_t.c.conversation_id,
                        _focus_t.c.node_id,
                    ],
                    set_={
                        "node_type": focus.node_type,
                        "document_type": focus.document_type,
                        "canonical_label": focus.canonical_label,
                        "document_id": focus.document_id,
                        "article_id": focus.article_id,
                        "clause_id": focus.clause_id,
                        "document_metadata": focus.document_metadata or None,
                        "last_grounded_user_turn_no": user_turn_no,
                        "citation_order": focus.citation_order,
                        "updated_at": func.now(),
                    },
                )
            )

    async def _prune_focuses(self) -> None:
        keep = (
            select(_focus_t.c.id)
            .where(_focus_t.c.conversation_id == self._conversation_id)
            .order_by(
                _focus_t.c.last_grounded_user_turn_no.desc(),
                _focus_t.c.citation_order.asc(),
                _focus_t.c.node_id.asc(),
            )
            .offset(MAX_GROUNDED_FOCUSES)
        )
        await self._conn.execute(delete(_focus_t).where(_focus_t.c.id.in_(keep)))

    async def _load_context(
        self, *, current_turn_id: uuid.UUID, current_user_turn_no: int
    ) -> HistoryContext:
        recent = await self._load_recent_messages(current_turn_id)
        focuses = await self._load_focuses(current_user_turn_no)
        pending = await self._load_pending()
        return HistoryContext(
            recent_messages=recent,
            grounded_focuses=focuses,
            pending_clarification=pending,
        )

    async def _load_recent_messages(
        self, current_turn_id: uuid.UUID
    ) -> tuple[HistoryMessage, ...]:
        stmt = (
            select(
                _msg_t.c.role,
                _msg_t.c.kind,
                _msg_t.c.content,
                _msg_t.c.ordinal,
                _turn_t.c.user_turn_no,
            )
            .join(_turn_t, _msg_t.c.turn_id == _turn_t.c.id)
            .where(
                _msg_t.c.conversation_id == self._conversation_id,
                _msg_t.c.turn_id != current_turn_id,
                _turn_t.c.status.in_(_COMPLETED_TURN_STATUSES),
            )
            .order_by(_msg_t.c.ordinal.desc())
            .limit(MAX_RECENT_MESSAGES)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        selected: list[Any] = []
        total = 0
        for row in rows:  # most recent first
            length = len(row["content"])
            if selected and total + length > MAX_RECENT_HISTORY_CHARS:
                break
            selected.append(row)
            total += length
        selected.reverse()  # chronological order
        return tuple(
            HistoryMessage(
                role=row["role"],
                kind=row["kind"],
                content=row["content"],
                ordinal=row["ordinal"],
                user_turn_no=row["user_turn_no"],
            )
            for row in selected
        )

    async def _load_focuses(
        self, current_user_turn_no: int
    ) -> tuple[GroundedFocus, ...]:
        # Evict focuses idle for more than the TTL window (schema dictionary §7):
        # a focus not re-grounded within FOCUS_TTL_USER_TURNS user turns is deleted.
        await self._conn.execute(
            delete(_focus_t).where(
                _focus_t.c.conversation_id == self._conversation_id,
                current_user_turn_no - _focus_t.c.last_grounded_user_turn_no
                > FOCUS_TTL_USER_TURNS,
            )
        )
        stmt = (
            select(_focus_t)
            .where(
                _focus_t.c.conversation_id == self._conversation_id,
            )
            .order_by(
                _focus_t.c.last_grounded_user_turn_no.desc(),
                _focus_t.c.citation_order.asc(),
                _focus_t.c.node_id.asc(),
            )
            .limit(MAX_GROUNDED_FOCUSES)
        )
        rows = (await self._conn.execute(stmt)).mappings().all()
        return tuple(
            GroundedFocus(
                node_id=row["node_id"],
                node_type=row["node_type"],
                canonical_label=row["canonical_label"],
                document_id=row["document_id"],
                citation_order=row["citation_order"],
                last_grounded_user_turn_no=row["last_grounded_user_turn_no"],
                document_type=row["document_type"],
                article_id=row["article_id"],
                clause_id=row["clause_id"],
                document_metadata=row["document_metadata"] or {},
            )
            for row in rows
        )

    async def _load_pending(self) -> PendingClarification | None:
        stmt = (
            select(_pend_t, _turn_t.c.user_turn_no)
            .join(_turn_t, _pend_t.c.source_turn_id == _turn_t.c.id)
            .where(_pend_t.c.conversation_id == self._conversation_id)
        )
        row = (await self._conn.execute(stmt)).mappings().first()
        if row is None:
            return None
        return PendingClarification(
            mode=row["mode"],
            question=row["question"],
            candidates=candidates_from_json(row["candidates"]),
            source_turn_id=row["source_turn_id"],
            source_user_turn_no=row["user_turn_no"],
        )


class SqlAlchemyConversationStore:
    """Owner-scoped conversation store backed by PostgreSQL."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        lock_timeout_seconds: float,
        lock_poll_interval_seconds: float,
    ) -> None:
        self._engine = engine
        self._lock_timeout_seconds = lock_timeout_seconds
        self._lock_poll_interval_seconds = lock_poll_interval_seconds

    async def find_turn_by_client_id(
        self,
        *,
        conversation_id: uuid.UUID,
        owner: Owner,
        client_turn_id: uuid.UUID,
    ) -> TurnRecord | None:
        async with self._engine.connect() as conn:
            conversation = await _load_owned_conversation(conn, conversation_id, owner)
            if conversation is None:
                return None
            stmt = select(_turn_t).where(
                _turn_t.c.conversation_id == conversation_id,
                _turn_t.c.client_turn_id == client_turn_id,
            )
            row = (await conn.execute(stmt)).mappings().first()
            return _to_turn_record(row) if row is not None else None

    async def replay_turn(
        self,
        *,
        conversation_id: uuid.UUID,
        owner: Owner,
        client_turn_id: uuid.UUID,
    ) -> dict[str, Any]:
        record = await self.find_turn_by_client_id(
            conversation_id=conversation_id,
            owner=owner,
            client_turn_id=client_turn_id,
        )
        if record is None or record.response_snapshot is None:
            raise TurnSnapshotError("No persisted snapshot to replay")
        return record.response_snapshot

    @asynccontextmanager
    async def locked_turn(
        self, *, conversation_id: uuid.UUID, owner: Owner
    ) -> AsyncIterator[LockedTurn]:
        key = conversation_lock_key(conversation_id)
        conn = await self._engine.connect()
        try:
            acquired = await acquire_with_deadline(
                conn,
                key,
                timeout_seconds=self._lock_timeout_seconds,
                poll_interval_seconds=self._lock_poll_interval_seconds,
            )
            if not acquired:
                raise ConversationBusyError("Conversation is busy")
            try:
                yield LockedTurn(conn, conversation_id=conversation_id, owner=owner)
            finally:
                await advisory_unlock(conn, key)
        finally:
            await conn.close()

    async def create_user_with_account(
        self, username: str, password_hash: str, full_name: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Create a user profile and an associated login account."""
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()
        async with self._engine.begin() as conn:
            # 1. Insert into accounts first
            await conn.execute(
                _acc_t.insert().values(
                    id=account_id,
                    username=username.strip().lower(),
                    password_hash=password_hash,
                )
            )
            # 2. Insert into users referencing account_id
            await conn.execute(
                _usr_t.insert().values(
                    id=user_id,
                    account_id=account_id,
                    full_name=full_name,
                )
            )
        return {
            "id": user_id,
            "account_id": account_id,
            "full_name": full_name,
        }, {
            "id": account_id,
            "username": username.strip().lower(),
        }

    async def get_account_by_username(self, username: str) -> dict[str, Any] | None:
        """Fetch account credentials and associated user_id by username."""
        async with self._engine.connect() as conn:
            res = await conn.execute(
                select(_acc_t, _usr_t.c.id.label("user_id"))
                .join(_usr_t, _usr_t.c.account_id == _acc_t.c.id, isouter=True)
                .where(_acc_t.c.username == username.strip().lower())
            )
            row = res.mappings().first()
            return dict(row) if row else None

    async def get_user_by_id(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        """Fetch user profile by user_id."""
        async with self._engine.connect() as conn:
            res = await conn.execute(
                select(_usr_t, _acc_t.c.username)
                .join(_acc_t, _usr_t.c.account_id == _acc_t.c.id, isouter=True)
                .where(_usr_t.c.id == user_id)
            )
            row = res.mappings().first()
            return dict(row) if row else None

    async def list_conversations(
        self, owner: Owner, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List active conversation history for the authenticated owner."""
        async with self._engine.connect() as conn:
            query = (
                select(
                    _conv_t.c.id,
                    _conv_t.c.title,
                    _conv_t.c.created_at,
                    _conv_t.c.updated_at,
                    _conv_t.c.next_user_turn_no,
                )
                .where(
                    _conv_t.c.owner_kind == owner.owner_kind,
                    _conv_t.c.owner_principal_id == owner.owner_principal_id,
                    _conv_t.c.is_deleted.is_(False),
                )
                .order_by(_conv_t.c.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            res = await conn.execute(query)
            rows = res.mappings().all()
            return [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "created_at": r["created_at"].isoformat()
                    if r["created_at"]
                    else None,
                    "updated_at": r["updated_at"].isoformat()
                    if r["updated_at"]
                    else None,
                    "turn_count": max(0, r["next_user_turn_no"] - 1),
                }
                for r in rows
            ]

    async def get_conversation_detail(
        self, conversation_id: uuid.UUID, owner: Owner
    ) -> dict[str, Any] | None:
        """Fetch full conversation details and transcript messages."""
        async with self._engine.connect() as conn:
            # 1. Fetch conversation
            conv_res = await conn.execute(
                select(_conv_t).where(
                    _conv_t.c.id == conversation_id,
                    _conv_t.c.owner_kind == owner.owner_kind,
                    _conv_t.c.owner_principal_id == owner.owner_principal_id,
                    _conv_t.c.is_deleted.is_(False),
                )
            )
            conv = conv_res.mappings().first()
            if not conv:
                return None

            # 2. Fetch messages
            msg_res = await conn.execute(
                select(_msg_t)
                .where(_msg_t.c.conversation_id == conversation_id)
                .order_by(_msg_t.c.ordinal.asc())
            )
            messages = msg_res.mappings().all()

            # 3. Fetch citations
            cit_res = await conn.execute(
                select(_cit_t)
                .where(_cit_t.c.conversation_id == conversation_id)
                .order_by(_cit_t.c.citation_ordinal.asc())
            )
            citations_by_msg: dict[uuid.UUID, list[dict[str, Any]]] = {}
            for c in cit_res.mappings().all():
                msg_id = c["message_id"]
                citations_by_msg.setdefault(msg_id, []).append(
                    {
                        "unit_id": c["unit_id"],
                        "citation_label": c["citation_label"],
                        "document_id": c["document_id"],
                        "deep_link": c["deep_link"],
                    }
                )

            formatted_msgs = [
                {
                    "id": str(m["id"]),
                    "role": m["role"],
                    "kind": m["kind"],
                    "content": m["content"],
                    "ordinal": m["ordinal"],
                    "citations": citations_by_msg.get(m["id"], []),
                }
                for m in messages
            ]

            return {
                "id": str(conv["id"]),
                "title": conv["title"],
                "created_at": conv["created_at"].isoformat()
                if conv["created_at"]
                else None,
                "updated_at": conv["updated_at"].isoformat()
                if conv["updated_at"]
                else None,
                "messages": formatted_msgs,
            }

    async def patch_conversation_title(
        self, conversation_id: uuid.UUID, owner: Owner, title: str
    ) -> bool:
        """Update conversation title."""
        async with self._engine.begin() as conn:
            res = await conn.execute(
                update(_conv_t)
                .where(
                    _conv_t.c.id == conversation_id,
                    _conv_t.c.owner_kind == owner.owner_kind,
                    _conv_t.c.owner_principal_id == owner.owner_principal_id,
                )
                .values(title=title.strip())
            )
            return res.rowcount > 0

    async def generate_conversation_title(
        self, conversation_id: uuid.UUID, owner: Owner
    ) -> str | None:
        """Derive and persist a title from the first user message (Plan 20 §5).

        Owner-scoped. Returns the new title, or ``None`` when the conversation
        does not exist for this owner or has no user message yet.
        """
        async with self._engine.begin() as conn:
            # 1. Verify ownership and that the conversation is live.
            conv = (
                await conn.execute(
                    select(_conv_t.c.id).where(
                        _conv_t.c.id == conversation_id,
                        _conv_t.c.owner_kind == owner.owner_kind,
                        _conv_t.c.owner_principal_id == owner.owner_principal_id,
                        _conv_t.c.is_deleted.is_(False),
                    )
                )
            ).first()
            if conv is None:
                return None

            # 2. Fetch the earliest user message content.
            first_user = (
                await conn.execute(
                    select(_msg_t.c.content)
                    .where(
                        _msg_t.c.conversation_id == conversation_id,
                        _msg_t.c.role == MessageRole.USER,
                    )
                    .order_by(_msg_t.c.ordinal.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if first_user is None:
                return None

            # 3. Derive a concise title and persist it.
            title = derive_title(first_user)
            await conn.execute(
                update(_conv_t)
                .where(_conv_t.c.id == conversation_id)
                .values(title=title)
            )
            return title

    async def delete_conversation(
        self, conversation_id: uuid.UUID, owner: Owner
    ) -> bool:
        """Soft delete a conversation."""
        async with self._engine.begin() as conn:
            res = await conn.execute(
                update(_conv_t)
                .where(
                    _conv_t.c.id == conversation_id,
                    _conv_t.c.owner_kind == owner.owner_kind,
                    _conv_t.c.owner_principal_id == owner.owner_principal_id,
                )
                .values(is_deleted=True)
            )
            return res.rowcount > 0

    async def claim_guest_conversations(
        self, anon_principal_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        """Transfer all anonymous conversations owned by anon_principal_id to user_id."""
        async with self._engine.begin() as conn:
            res = await conn.execute(
                update(_conv_t)
                .where(
                    _conv_t.c.owner_kind == "ANONYMOUS",
                    _conv_t.c.owner_principal_id == anon_principal_id,
                )
                .values(owner_kind="USER", owner_principal_id=user_id)
            )
            return res.rowcount


def focus_upserts_from_citations(
    citations: Sequence[CitationSnapshot],
) -> tuple[FocusUpsert, ...]:
    """Derive focus upserts from grounded citations (Plan 19 §4).

    Only citations become focuses; ``node_id`` is the citation's most specific
    canonical unit id.
    """
    upserts: list[FocusUpsert] = []
    for citation in citations:
        node_id = citation.clause_id or citation.article_id or citation.document_id
        node_type = (
            "Clause"
            if citation.clause_id
            else "Article"
            if citation.article_id
            else "Document"
        )
        upserts.append(
            FocusUpsert(
                node_id=node_id,
                node_type=node_type,
                canonical_label=citation.citation_label,
                document_id=citation.document_id,
                citation_order=citation.citation_ordinal,
                article_id=citation.article_id,
                clause_id=citation.clause_id,
                document_metadata=citation.metadata,
            )
        )
    return tuple(upserts)
