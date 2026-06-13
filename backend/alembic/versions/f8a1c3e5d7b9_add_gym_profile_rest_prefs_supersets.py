"""add gym profile, per-user rest prefs, and superset grouping

The in-gym toolkit (#7) adds three things to the schema:

* ``gym_profiles`` — a user's available equipment (CONTEXT.md "Gym Profile"):
  the bar(s) and plate denominations the plate calculator loads, plus a general
  equipment list aligned with ``exercises.equipment`` (for the #11 Recommendation
  engine to constrain by). One row per user (UNIQUE user_id), get-or-created.
* ``user_exercise_prefs`` — per-user, per-Exercise preferences; today just the
  rest timer's ``default_rest_seconds``. Stored here, NOT on the shared
  ``exercises`` row, because the library is shared across users and a rest
  default is a private per-user setting (isolation rule).
* ``training_sets.superset_group`` — a nullable per-Session integer tagging Sets
  that form one Superset (logged in alternation); NULL = standalone.

Revision ID: f8a1c3e5d7b9
Revises: e7a9c1d3f5b7
Create Date: 2026-06-13 07:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f8a1c3e5d7b9'
down_revision: Union[str, None] = 'e7a9c1d3f5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Gym Profile: one row per user, JSONB equipment lists. ---
    op.create_table(
        'gym_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('bar_weights_kg', postgresql.JSONB(), nullable=False),
        sa.Column('plate_weights_kg', postgresql.JSONB(), nullable=False),
        sa.Column('equipment', postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_gym_profile_user'),
    )

    # --- Per-user, per-Exercise preferences (rest-timer default). ---
    op.create_table(
        'user_exercise_prefs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('exercise_id', sa.UUID(), nullable=False),
        sa.Column('default_rest_seconds', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['exercise_id'], ['exercises.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'exercise_id', name='uq_user_exercise_pref'
        ),
    )

    # --- Superset grouping tag on Sets. ---
    op.add_column(
        'training_sets',
        sa.Column('superset_group', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('training_sets', 'superset_group')
    op.drop_table('user_exercise_prefs')
    op.drop_table('gym_profiles')
