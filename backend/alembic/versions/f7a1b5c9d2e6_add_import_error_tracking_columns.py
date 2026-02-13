"""add import error tracking columns

Revision ID: f7a1b5c9d2e6
Revises: e6f0a4b8c3d5
Create Date: 2026-02-13 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f7a1b5c9d2e6'
down_revision: Union[str, None] = 'e6f0a4b8c3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'import_batches',
        sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'import_batches',
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'import_batches',
        sa.Column('error_messages', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('import_batches', 'error_messages')
    op.drop_column('import_batches', 'skipped_count')
    op.drop_column('import_batches', 'error_count')
