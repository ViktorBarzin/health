"""replace password with webauthn credentials

Revision ID: b3f7a1c2d4e5
Revises: a26a598bb610
Create Date: 2026-02-08 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b3f7a1c2d4e5'
down_revision: Union[str, None] = 'a26a598bb610'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop password_hash column from users
    op.drop_column('users', 'password_hash')

    # Create user_credentials table
    op.create_table('user_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('credential_id', sa.LargeBinary(), nullable=False),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False),
        sa.Column('transports', sa.String(), nullable=True),
        sa.Column('device_name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_credentials_credential_id', 'user_credentials', ['credential_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_credentials_credential_id', table_name='user_credentials')
    op.drop_table('user_credentials')
    op.add_column('users', sa.Column('password_hash', sa.String(), nullable=False, server_default=''))
