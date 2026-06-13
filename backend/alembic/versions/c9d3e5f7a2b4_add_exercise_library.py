"""add exercise library

Adds the shared Exercise library (``exercises``) and its normalized muscle
mappings (``exercise_muscles``). A row with ``user_id IS NULL`` is a global,
shared Exercise (seeded from free-exercise-db); a non-NULL ``user_id`` is a
user's private custom Exercise. Two partial unique indexes enforce the natural
key (``slug``) separately for the global namespace and each user's namespace,
since a plain composite unique would treat NULL user_ids as distinct.

Revision ID: c9d3e5f7a2b4
Revises: b8c2d4e6f0a1
Create Date: 2026-06-13 05:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c9d3e5f7a2b4'
down_revision: Union[str, None] = 'b8c2d4e6f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The 17 free-exercise-db muscle groups (stored as the dataset labels, e.g.
# "lower back") and the primary/secondary role — both native Postgres enums so
# per-muscle volume/Recovery analytics can GROUP BY a typed dimension.
_MUSCLE_LABELS = [
    "abdominals", "abductors", "adductors", "biceps", "calves", "chest",
    "forearms", "glutes", "hamstrings", "lats", "lower back", "middle back",
    "neck", "quadriceps", "shoulders", "traps", "triceps",
]
_ROLE_LABELS = ["primary", "secondary"]

muscle_enum = postgresql.ENUM(*_MUSCLE_LABELS, name="muscle", create_type=False)
role_enum = postgresql.ENUM(*_ROLE_LABELS, name="muscle_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    muscle_enum.create(bind, checkfirst=True)
    role_enum.create(bind, checkfirst=True)

    op.create_table(
        'exercises',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('force', sa.String(), nullable=True),
        sa.Column('level', sa.String(), nullable=True),
        sa.Column('mechanic', sa.String(), nullable=True),
        sa.Column('equipment', sa.String(), nullable=True),
        sa.Column('instructions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('images', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('source', sa.String(), server_default='custom', nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Idempotency / natural-key uniqueness, split by namespace (NULLs compare
    # distinct in a plain unique, so the global namespace needs its own partial
    # index).
    op.create_index(
        'uq_exercise_global_slug', 'exercises', ['slug'], unique=True,
        postgresql_where=sa.text('user_id IS NULL'),
    )
    op.create_index(
        'uq_exercise_user_slug', 'exercises', ['user_id', 'slug'], unique=True,
        postgresql_where=sa.text('user_id IS NOT NULL'),
    )
    op.create_index('ix_exercises_user_id', 'exercises', ['user_id'], unique=False)

    op.create_table(
        'exercise_muscles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('exercise_id', sa.UUID(), nullable=False),
        sa.Column('muscle', muscle_enum, nullable=False),
        sa.Column('role', role_enum, nullable=False),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_exercise_muscle', 'exercise_muscles',
        ['exercise_id', 'muscle', 'role'], unique=True,
    )
    op.create_index('ix_exercise_muscles_muscle', 'exercise_muscles', ['muscle'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_exercise_muscles_muscle', table_name='exercise_muscles')
    op.drop_index('uq_exercise_muscle', table_name='exercise_muscles')
    op.drop_table('exercise_muscles')
    op.drop_index('ix_exercises_user_id', table_name='exercises')
    op.drop_index('uq_exercise_user_slug', table_name='exercises')
    op.drop_index('uq_exercise_global_slug', table_name='exercises')
    op.drop_table('exercises')
    bind = op.get_bind()
    role_enum.drop(bind, checkfirst=True)
    muscle_enum.drop(bind, checkfirst=True)
