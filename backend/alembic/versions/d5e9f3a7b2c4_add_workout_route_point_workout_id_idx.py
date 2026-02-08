"""add workout route point workout_id index

Revision ID: d5e9f3a7b2c4
Revises: c4d8e2f6a1b3
Create Date: 2026-02-08 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd5e9f3a7b2c4'
down_revision: Union[str, None] = 'c4d8e2f6a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_workout_route_points_workout_id',
        'workout_route_points',
        ['workout_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_workout_route_points_workout_id', table_name='workout_route_points')
