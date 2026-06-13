"""add training sessions and sets

Adds the live gym-logging core: ``training_sessions`` (a per-user, ordered list
of Sets, with a start and optional end time) and ``training_sets`` (one performed
set referencing exactly one Exercise — weight × reps, optional Effort stored as
its RPE-equivalent, and a set type). The tables are named ``training_*`` because
``session`` collides with the auth-session concept and ``set`` is a SQL reserved
word; the API/URL vocabulary stays the clean "session"/"set".

``set_type`` is a native Postgres enum (normal/warmup/drop/failure), created here
explicitly with ``create_type=False`` — mirroring the Exercise muscle enums — so
it exists once for the migrated database. Set order is an explicit 0-based
``order_index`` kept gap-free by the app, with a unique ``(session_id,
order_index)``.

Revision ID: d4f6a8c0e2b5
Revises: c9d3e5f7a2b4
Create Date: 2026-06-13 06:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd4f6a8c0e2b5'
down_revision: Union[str, None] = 'c9d3e5f7a2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The four set types, stored as their enum values. A native Postgres enum so
# later volume/PR analytics filter on a typed dimension (same pattern as the
# Exercise muscle enums). create_type=False — created explicitly in upgrade().
_SET_TYPE_LABELS = ["normal", "warmup", "drop", "failure"]
set_type_enum = postgresql.ENUM(*_SET_TYPE_LABELS, name="set_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    set_type_enum.create(bind, checkfirst=True)

    op.create_table(
        'training_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_training_sessions_user_started',
        'training_sessions',
        ['user_id', 'started_at'],
        unique=False,
    )

    op.create_table(
        'training_sets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('exercise_id', sa.UUID(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('weight_kg', sa.Float(), nullable=False),
        sa.Column('reps', sa.Integer(), nullable=False),
        sa.Column('rpe', sa.Float(), nullable=True),
        sa.Column('set_type', set_type_enum, nullable=False),
        sa.ForeignKeyConstraint(
            ['session_id'], ['training_sessions.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['exercise_id'], ['exercises.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'session_id', 'order_index', name='uq_training_set_session_order'
        ),
    )
    op.create_index(
        'ix_training_sets_session_order',
        'training_sets',
        ['session_id', 'order_index'],
        unique=False,
    )
    op.create_index(
        'ix_training_sets_exercise', 'training_sets', ['exercise_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_training_sets_exercise', table_name='training_sets')
    op.drop_index('ix_training_sets_session_order', table_name='training_sets')
    op.drop_table('training_sets')
    op.drop_index(
        'ix_training_sessions_user_started', table_name='training_sessions'
    )
    op.drop_table('training_sessions')
    set_type_enum.drop(op.get_bind(), checkfirst=True)
