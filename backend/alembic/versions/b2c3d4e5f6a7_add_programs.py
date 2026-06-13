"""add goal-driven Programs

Adds the generated multi-week **Program** layer (ADR-0004, issue #13): a Program
header plus its split days and ramping per-muscle weekly volume targets, all
composed by the deterministic generator from the cited Principles KB. Three
tables (entity-style UUID PKs, matching workouts/exercises/training_sessions):

* ``programs`` — the Program header: Goal, days/week, session length, mesocycle
  length + deload week, status (ONE active per user, partial unique index), and a
  JSONB ``provenance`` receipt mapping every generated parameter to its Principle
  key (so #14's receipts UI can render "why this number").
* ``program_days`` — the split: one row per training day, each with its ordered
  muscle ``slots`` (JSONB) the Recommendation fills with Exercises.
* ``program_muscle_volumes`` — the ramping weekly per-muscle volume target: one
  row per (muscle, week), ramping up then dropping on the deload week.

One new native enum, ``program_status`` (active/archived). The ``training_goal``,
``experience_level`` and ``muscle`` enums already exist (from the Principles and
Exercise migrations); they are referenced with ``create_type=False`` and NOT
recreated. Programs are generated only — no user-authored plans (ADR-0004).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-13 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New enum for this migration (stored as the enum *values*, matching the ORM's
# values_callable). create_type=False so we drive creation explicitly below.
_STATUS_LABELS = ["active", "archived"]
status_enum = postgresql.ENUM(
    *_STATUS_LABELS, name="program_status", create_type=False
)

# Pre-existing enums referenced by these tables — created by earlier migrations,
# so NOT (re)created here; create_type=False prevents Alembic from emitting CREATE
# TYPE for them when used as column types.
goal_enum = postgresql.ENUM(name="training_goal", create_type=False)
level_enum = postgresql.ENUM(name="experience_level", create_type=False)
muscle_enum = postgresql.ENUM(name="muscle", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    status_enum.create(bind, checkfirst=True)

    op.create_table(
        'programs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('preset_key', sa.String(), nullable=True),
        sa.Column('goal', goal_enum, nullable=False),
        sa.Column('experience', level_enum, nullable=False),
        sa.Column('days_per_week', sa.Integer(), nullable=False),
        sa.Column('session_minutes', sa.Integer(), nullable=False),
        sa.Column('mesocycle_weeks', sa.Integer(), nullable=False),
        sa.Column('total_weeks', sa.Integer(), nullable=False),
        sa.Column('deload_week', sa.Integer(), nullable=False),
        sa.Column('rep_range_low', sa.Integer(), nullable=False),
        sa.Column('rep_range_high', sa.Integer(), nullable=False),
        sa.Column('effort_rir', sa.Integer(), nullable=False),
        sa.Column('status', status_enum, nullable=False),
        sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # At most ONE active Program per user (the one driving the daily
    # Recommendation). Partial unique index — archived rows never collide.
    op.create_index(
        'uq_program_active_per_user',
        'programs',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index('ix_programs_user', 'programs', ['user_id'], unique=False)

    op.create_table(
        'program_days',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('program_id', sa.UUID(), nullable=False),
        sa.Column('day_index', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slots', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ['program_id'], ['programs.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_program_day', 'program_days', ['program_id', 'day_index'], unique=True
    )

    op.create_table(
        'program_muscle_volumes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('program_id', sa.UUID(), nullable=False),
        sa.Column('muscle', muscle_enum, nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('target_sets', sa.Integer(), nullable=False),
        sa.Column('is_deload', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ['program_id'], ['programs.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_program_muscle_week',
        'program_muscle_volumes',
        ['program_id', 'muscle', 'week'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_program_muscle_week', table_name='program_muscle_volumes')
    op.drop_table('program_muscle_volumes')
    op.drop_index('uq_program_day', table_name='program_days')
    op.drop_table('program_days')
    op.drop_index('ix_programs_user', table_name='programs')
    op.drop_index('uq_program_active_per_user', table_name='programs')
    op.drop_table('programs')
    bind = op.get_bind()
    status_enum.drop(bind, checkfirst=True)
