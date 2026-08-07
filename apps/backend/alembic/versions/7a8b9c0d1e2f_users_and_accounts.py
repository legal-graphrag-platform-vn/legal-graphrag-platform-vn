"""add users and accounts tables and conversation history metadata

Revision ID: 7a8b9c0d1e2f
Revises: 6febccd6a53b
Create Date: 2026-08-05 09:25:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '7a8b9c0d1e2f'
down_revision: str | None = '6febccd6a53b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create accounts table first
    op.create_table(
        'accounts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username', name='uq_accounts_username')
    )
    op.create_index(op.f('ix_accounts_username'), 'accounts', ['username'], unique=True)

    # 2. Create users table referencing accounts.id
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('account_id', sa.Uuid(), nullable=True),
        sa.Column('full_name', sa.String(length=128), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', name='uq_users_account_id')
    )
    op.create_index(op.f('ix_users_account_id'), 'users', ['account_id'], unique=True)

    # 3. Add title and is_deleted to conversations table
    op.add_column('conversations', sa.Column('title', sa.String(length=255), nullable=False, server_default='Cuộc trò chuyện mới'))
    op.add_column('conversations', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_index('ix_conversations_owner_history', 'conversations', ['owner_kind', 'owner_principal_id', 'is_deleted', 'updated_at'], unique=False)

    # 4. Update owner_kind check constraint on conversations table to allow USER
    op.drop_constraint('owner_kind', 'conversations', type_='check')
    op.create_check_constraint(
        'owner_kind',
        'conversations',
        "owner_kind IN ('ANONYMOUS', 'USER')"
    )


def downgrade() -> None:
    op.drop_constraint('owner_kind', 'conversations', type_='check')
    op.create_check_constraint(
        'owner_kind',
        'conversations',
        "owner_kind IN ('ANONYMOUS')"
    )
    op.drop_index('ix_conversations_owner_history', table_name='conversations')
    op.drop_column('conversations', 'is_deleted')
    op.drop_column('conversations', 'title')
    op.drop_index(op.f('ix_users_account_id'), table_name='users')
    op.drop_index(op.f('ix_accounts_username'), table_name='accounts')
    # Drop users first: it holds the FK to accounts.
    op.drop_table('users')
    op.drop_table('accounts')
