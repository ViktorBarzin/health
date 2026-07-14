"""add prescriptions + program revisions (Block Review foundation, ADR-0011)

``prescriptions`` — the immutable snapshot of what a started Recommendation
prescribed (one per instantiated Session), so Adherence (performed vs planned)
becomes measurable. ``program_revisions`` — the versioned receipt log of every
automatic Program change. ``programs`` gains ``version`` (bumped per revision),
``reviewed_at`` (the evaluate-on-read gate) and ``parent_program_id`` (block
succession chain). Plan docs/plans/2026-07-14-adaptive-programming.md M4.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-14 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_prescription_source = ENUM(
    'program', 'freestyle', 'adjusted', 'explicit',
    name='prescription_source', create_type=False,
)
_revision_trigger = ENUM(
    'continuous_review', 'block_review', 'proposal',
    name='revision_trigger', create_type=False,
)


def upgrade() -> None:
    _prescription_source.create(op.get_bind(), checkfirst=True)
    _revision_trigger.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'prescriptions',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('program_id', UUID(as_uuid=True), nullable=True),
        sa.Column('program_version', sa.Integer(), nullable=True),
        sa.Column('day_index', sa.Integer(), nullable=True),
        sa.Column('source', _prescription_source, nullable=False),
        sa.Column('slots', JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['session_id'], ['training_sessions.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )
    op.create_index('ix_prescriptions_user_id', 'prescriptions', ['user_id'])

    op.create_table(
        'program_revisions',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('program_id', UUID(as_uuid=True), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('trigger', _revision_trigger, nullable=False),
        sa.Column('changes', JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_program_revisions_program', 'program_revisions', ['program_id', 'version']
    )

    op.add_column(
        'programs',
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column(
        'programs', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'programs', sa.Column('parent_program_id', UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        'fk_programs_parent',
        'programs',
        'programs',
        ['parent_program_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_programs_parent', 'programs', type_='foreignkey')
    op.drop_column('programs', 'parent_program_id')
    op.drop_column('programs', 'reviewed_at')
    op.drop_column('programs', 'version')
    op.drop_index('ix_program_revisions_program', table_name='program_revisions')
    op.drop_table('program_revisions')
    op.drop_index('ix_prescriptions_user_id', table_name='prescriptions')
    op.drop_table('prescriptions')
    _revision_trigger.drop(op.get_bind(), checkfirst=True)
    _prescription_source.drop(op.get_bind(), checkfirst=True)
