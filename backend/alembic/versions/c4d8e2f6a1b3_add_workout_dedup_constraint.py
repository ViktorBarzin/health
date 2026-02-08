"""add workout dedup constraint

Revision ID: c4d8e2f6a1b3
Revises: b3f7a1c2d4e5
Create Date: 2026-02-08 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4d8e2f6a1b3'
down_revision: Union[str, None] = 'b3f7a1c2d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove duplicate workouts before adding the constraint.
    # Keep the row with the smallest id (first inserted) for each
    # (user_id, time, activity_type) group.
    op.execute("""
        DELETE FROM workout_route_points
        WHERE workout_id IN (
            SELECT w.id FROM workouts w
            WHERE w.id NOT IN (
                SELECT DISTINCT ON (user_id, time, activity_type) id
                FROM workouts
                ORDER BY user_id, time, activity_type, id
            )
        )
    """)
    op.execute("""
        DELETE FROM workouts
        WHERE id NOT IN (
            SELECT DISTINCT ON (user_id, time, activity_type) id
            FROM workouts
            ORDER BY user_id, time, activity_type, id
        )
    """)

    op.create_unique_constraint(
        'uq_workout_dedup', 'workouts', ['user_id', 'time', 'activity_type']
    )


def downgrade() -> None:
    op.drop_constraint('uq_workout_dedup', 'workouts', type_='unique')
