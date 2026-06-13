"""add personal records

Adds ``personal_records`` — the persisted, authoritative per-user/per-exercise
personal record (CONTEXT.md "PR"). PR *detection* is a pure function shared by the
offline browser and the backend; this table is the record-of-truth the server
recomputes and upserts on sync, so a client-side celebration is reconciled here
without duplicate or false PRs.

One row per (user, exercise, kind, weight_bucket): for the weight-independent
kinds (weight/e1rm/volume) ``weight_bucket`` is NULL (one row each); for
``reps_at_weight`` it is the weight (one row per distinct load). Two partial
unique indexes enforce "one row per slot" because Postgres treats NULLs as
distinct in a plain composite unique — the same split-namespace pattern the
Exercise ``slug`` uses.

``kind`` is a native Postgres enum (pr_kind), created here explicitly with
``create_type=False`` (mirroring set_type / the muscle enums) so it exists once
for the migrated database.

Revision ID: e7a9c1d3f5b7
Revises: d4f6a8c0e2b5
Create Date: 2026-06-13 06:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e7a9c1d3f5b7'
down_revision: Union[str, None] = 'd4f6a8c0e2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The four PR dimensions, stored as their enum values. create_type=False —
# created explicitly in upgrade(), matching the set_type / muscle enum pattern.
_PR_KIND_LABELS = ["weight", "e1rm", "reps_at_weight", "volume"]
pr_kind_enum = postgresql.ENUM(*_PR_KIND_LABELS, name="pr_kind", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    pr_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        'personal_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('exercise_id', sa.UUID(), nullable=False),
        sa.Column('kind', pr_kind_enum, nullable=False),
        sa.Column('weight_bucket', sa.Float(), nullable=True),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('achieved_set_id', sa.UUID(), nullable=True),
        sa.Column(
            'achieved_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['exercise_id'], ['exercises.id'], ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(
            ['achieved_set_id'], ['training_sets.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    # One row per slot for the weight-independent kinds (weight_bucket NULL).
    op.create_index(
        'uq_pr_user_exercise_kind',
        'personal_records',
        ['user_id', 'exercise_id', 'kind'],
        unique=True,
        postgresql_where=sa.text('weight_bucket IS NULL'),
    )
    # One row per weight for reps_at_weight (weight_bucket NOT NULL).
    op.create_index(
        'uq_pr_user_exercise_kind_weight',
        'personal_records',
        ['user_id', 'exercise_id', 'kind', 'weight_bucket'],
        unique=True,
        postgresql_where=sa.text('weight_bucket IS NOT NULL'),
    )
    # Read path: this user's PRs for this Exercise.
    op.create_index(
        'ix_pr_user_exercise',
        'personal_records',
        ['user_id', 'exercise_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_pr_user_exercise', table_name='personal_records')
    op.drop_index('uq_pr_user_exercise_kind_weight', table_name='personal_records')
    op.drop_index('uq_pr_user_exercise_kind', table_name='personal_records')
    op.drop_table('personal_records')
    pr_kind_enum.drop(op.get_bind(), checkfirst=True)
