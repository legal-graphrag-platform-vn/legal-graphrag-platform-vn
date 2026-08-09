"""add turn_debug_trace table (Plan 21 §4)

Revision ID: b1c2d3e4f5a6
Revises: 7a8b9c0d1e2f
Create Date: 2026-08-09 10:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'b1c2d3e4f5a6'
down_revision: str | None = '7a8b9c0d1e2f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'turn_debug_trace',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.Uuid(), nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('owner_principal_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('events', JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_turn_debug_trace_trace_id'),
        'turn_debug_trace',
        ['trace_id'],
        unique=False,
    )
    op.create_index(
        'ix_turn_debug_trace_conversation',
        'turn_debug_trace',
        ['conversation_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_turn_debug_trace_conversation', table_name='turn_debug_trace')
    op.drop_index(
        op.f('ix_turn_debug_trace_trace_id'), table_name='turn_debug_trace'
    )
    op.drop_table('turn_debug_trace')
