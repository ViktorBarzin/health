"""add excluded flag to user_exercise_prefs (Exclusion)

The per-user "never recommend this Exercise again" mark (CONTEXT.md
"Exclusion", plan 2026-07-13-fitbod-exit-gym-pwa). Lives on the existing
per-(user, exercise) preferences row — the table's docstring reserved exactly
this kind of per-user knob — so no new table. Every Recommendation generator
path (freestyle, Program slots, Swap alternatives) filters rows where this is
true, the same hard-filter semantics as Gym Profile equipment.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-13 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_exercise_prefs',
        sa.Column(
            'excluded', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column('user_exercise_prefs', 'excluded')
