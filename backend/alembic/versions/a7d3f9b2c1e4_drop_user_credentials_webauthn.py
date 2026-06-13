"""drop user_credentials (WebAuthn retired for Authentik forward-auth)

Identity is now established at the edge by Authentik forward-auth
(ADR-0003); the app no longer stores passkeys, so the user_credentials
table is removed. Done as its own migration ahead of the user
reconciliation so the merge step never has to reassign credential rows.

Revision ID: a7d3f9b2c1e4
Revises: f7b9c1d2e3f4
Create Date: 2026-06-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3f9b2c1e4"
down_revision: Union[str, None] = "f7b9c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_user_credentials_credential_id", table_name="user_credentials")
    op.drop_table("user_credentials")


def downgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=False),
        sa.Column("transports", sa.String(), nullable=True),
        sa.Column("device_name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_credentials_credential_id",
        "user_credentials",
        ["credential_id"],
        unique=True,
    )
