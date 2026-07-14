"""add analysis reports + proposals (LLM layer, ADR-0011 M5)

``analysis_reports`` (one qwen coach's-notes narrative per Program training
week, digest stored for audit) and ``proposals`` (LLM-suggested changes that
apply only after engine validation + user approval).

Revision ID: d0e1f2a3b4c9
Revises: c9d0e1f2a3b4
Create Date: 2026-07-14 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision: str = 'd0e1f2a3b4c9'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_proposal_status = ENUM(
    'pending', 'approved', 'rejected', name='proposal_status', create_type=False
)


def upgrade() -> None:
    _proposal_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'analysis_reports',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('program_id', UUID(as_uuid=True), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('narrative', sa.Text(), nullable=False),
        sa.Column('digest', JSONB(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_analysis_report_week',
        'analysis_reports',
        ['program_id', 'week'],
        unique=True,
    )
    op.create_index('ix_analysis_reports_user', 'analysis_reports', ['user_id'])

    op.create_table(
        'proposals',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('program_id', UUID(as_uuid=True), nullable=False),
        sa.Column('report_id', UUID(as_uuid=True), nullable=True),
        sa.Column('change', JSONB(), nullable=False),
        sa.Column('status', _proposal_status, nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['report_id'], ['analysis_reports.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_proposals_user_status', 'proposals', ['user_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_proposals_user_status', table_name='proposals')
    op.drop_table('proposals')
    op.drop_index('ix_analysis_reports_user', table_name='analysis_reports')
    op.drop_index('uq_analysis_report_week', table_name='analysis_reports')
    op.drop_table('analysis_reports')
    _proposal_status.drop(op.get_bind(), checkfirst=True)
