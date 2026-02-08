"""add batch_id indexes for faster deletion

Revision ID: e6f0a4b8c3d5
Revises: d5e9f3a7b2c4
Create Date: 2026-02-08 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e6f0a4b8c3d5'
down_revision: Union[str, None] = 'd5e9f3a7b2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_health_records_batch_id',
        'health_records',
        ['batch_id'],
    )
    op.create_index(
        'ix_category_records_batch_id',
        'category_records',
        ['batch_id'],
    )
    op.create_index(
        'ix_workouts_batch_id',
        'workouts',
        ['batch_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_workouts_batch_id', table_name='workouts')
    op.drop_index('ix_category_records_batch_id', table_name='category_records')
    op.drop_index('ix_health_records_batch_id', table_name='health_records')
