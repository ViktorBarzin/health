"""add web push tables (ADR-0010)

``push_subscriptions`` (browser PushManager subscriptions, endpoint-unique,
per-user) and ``push_timers`` (the single pending rest-timer push per user,
claimed with SKIP LOCKED by the delivery poller). The rest timer's
locked-iPhone / mirrored-Apple-Watch path — plan
2026-07-13-fitbod-exit-gym-pwa ②.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-13 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'push_subscriptions',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.Text(), nullable=False),
        sa.Column('auth', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index(
        'ix_push_subscriptions_user_id', 'push_subscriptions', ['user_id']
    )

    op.create_table(
        'push_timers',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('fire_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('body', sa.String(length=200), nullable=False),
        sa.Column('url', sa.String(length=200), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_index('ix_push_timers_fire_at', 'push_timers', ['fire_at'])


def downgrade() -> None:
    op.drop_index('ix_push_timers_fire_at', table_name='push_timers')
    op.drop_table('push_timers')
    op.drop_index('ix_push_subscriptions_user_id', table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
