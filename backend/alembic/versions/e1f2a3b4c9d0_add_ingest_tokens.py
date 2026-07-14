"""add ingest tokens (Apple Health push Connector, M7 / ADR-0012)

Per-user revocable bearer credentials for the auth-free public ingest host.
Only the SHA-256 hash is stored (plaintext shown once at mint time); ``prefix``
identifies a token in the list UI; ``last_used_at`` is the auto-sync liveness
signal.

Revision ID: e1f2a3b4c9d0
Revises: d0e1f2a3b4c9
Create Date: 2026-07-14 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'e1f2a3b4c9d0'
down_revision: Union[str, None] = 'd0e1f2a3b4c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ingest_tokens',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_ingest_tokens_user_id', 'ingest_tokens', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_ingest_tokens_user_id', table_name='ingest_tokens')
    op.drop_table('ingest_tokens')
