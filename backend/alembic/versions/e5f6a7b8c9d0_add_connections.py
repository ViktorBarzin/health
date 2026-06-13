"""add per-user Connections (BYOT integrations)

Adds the Connection framework (CONTEXT.md "Connector"; ADR-0006, BYOT variant —
connections):

* ``connections`` — one row per (user, provider). The user's external API
  credential (e.g. an Oura Personal Access Token) is stored ENCRYPTED at rest in
  ``encrypted_credential`` (Fernet ciphertext, a ``bytea``) — never plaintext,
  never returned, never logged. Operational metadata: ``status``
  (active/error/disabled), ``last_sync_at``, ``last_error``, ``created_at`` /
  ``updated_at``. ``UNIQUE(user_id, provider)`` so re-connecting a provider
  updates the existing row rather than duplicating.

Two native enums (stored as the enum *values*, matching the ORM's
``values_callable``), created explicitly here with ``create_type=False``:

* ``connection_provider`` — the external platform; starts with ``oura`` (the clean
  BYOT/PAT case). Extensible: a new provider is one new label + one connector
  class (Whoop/Garmin are documented but not built).
* ``connection_status`` — ``active`` / ``error`` / ``disabled``.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-13 19:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New native enums for this migration (stored as the enum values, matching the
# ORM's values_callable). create_type=False so we drive creation explicitly.
_PROVIDER_LABELS = ["oura"]
_STATUS_LABELS = ["active", "error", "disabled"]
provider_enum = postgresql.ENUM(
    *_PROVIDER_LABELS, name="connection_provider", create_type=False
)
status_enum = postgresql.ENUM(
    *_STATUS_LABELS, name="connection_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    provider_enum.create(bind, checkfirst=True)
    status_enum.create(bind, checkfirst=True)

    op.create_table(
        'connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', provider_enum, nullable=False),
        # The user's API credential, Fernet-encrypted — never plaintext.
        sa.Column('encrypted_credential', sa.LargeBinary(), nullable=False),
        sa.Column(
            'status', status_enum, server_default='active', nullable=False
        ),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # One Connection per provider per user — re-connecting updates the row.
        sa.UniqueConstraint(
            'user_id', 'provider', name='uq_connection_user_provider'
        ),
    )


def downgrade() -> None:
    op.drop_table('connections')
    bind = op.get_bind()
    status_enum.drop(bind, checkfirst=True)
    provider_enum.drop(bind, checkfirst=True)
