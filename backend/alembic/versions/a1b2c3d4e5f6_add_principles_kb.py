"""add principles knowledge base

Adds the versioned, cited exercise-science Principles KB (ADR-0004): the
``principles`` table (one row per rule — stable ``key``, statement, category,
typed parameter ranges, Goal/experience applicability, evidence grade, version)
and its normalized one-to-many citations (``principle_citations`` — authors,
year, title, journal, DOI/PMID/URL). The deterministic Program generator (#13)
composes only from these rows, so every prescribed parameter traces to a cited
study; the receipts UI (#14) reads them too. Seeded idempotently by
``app.services.seed_principles`` (run from entrypoint.sh after this migration).

Four native enums back typed dimensions: ``training_goal`` (Goal applicability —
the canonical home for the CONTEXT.md Goal vocabulary), ``experience_level``,
``principle_category``, and ``evidence_grade``.

Revision ID: a1b2c3d4e5f6
Revises: f8a1c3e5d7b9
Create Date: 2026-06-13 09:20:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f8a1c3e5d7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Native Postgres enums (stored as the enum *values*, matching the ORM's
# values_callable). create_type=False so we drive creation explicitly below.
_GOAL_LABELS = ["bulk", "cut", "maintain", "strength"]
_LEVEL_LABELS = ["beginner", "intermediate", "advanced"]
_CATEGORY_LABELS = [
    "volume", "frequency", "intensity", "progression", "periodization",
    "deload", "rest", "nutrition",
]
_GRADE_LABELS = ["A", "B", "C"]

goal_enum = postgresql.ENUM(*_GOAL_LABELS, name="training_goal", create_type=False)
level_enum = postgresql.ENUM(
    *_LEVEL_LABELS, name="experience_level", create_type=False
)
category_enum = postgresql.ENUM(
    *_CATEGORY_LABELS, name="principle_category", create_type=False
)
grade_enum = postgresql.ENUM(*_GRADE_LABELS, name="evidence_grade", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    goal_enum.create(bind, checkfirst=True)
    level_enum.create(bind, checkfirst=True)
    category_enum.create(bind, checkfirst=True)
    grade_enum.create(bind, checkfirst=True)

    op.create_table(
        'principles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False),
        sa.Column('category', category_enum, nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('goals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'experience_levels',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column('evidence_grade', grade_enum, nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Stable natural key (upsert key for the seed) + category browse index.
    op.create_index('uq_principle_key', 'principles', ['key'], unique=True)
    op.create_index(
        'ix_principles_category', 'principles', ['category'], unique=False
    )

    op.create_table(
        'principle_citations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('principle_id', sa.UUID(), nullable=False),
        sa.Column('authors', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('journal', sa.String(), nullable=False),
        sa.Column('doi', sa.String(), nullable=True),
        sa.Column('pmid', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ['principle_id'], ['principles.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    # No exact-duplicate citation (same source title) under one Principle — the
    # seed reconciles citations keyed on title.
    op.create_index(
        'uq_principle_citation',
        'principle_citations',
        ['principle_id', 'title'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_principle_citation', table_name='principle_citations')
    op.drop_table('principle_citations')
    op.drop_index('ix_principles_category', table_name='principles')
    op.drop_index('uq_principle_key', table_name='principles')
    op.drop_table('principles')
    bind = op.get_bind()
    grade_enum.drop(bind, checkfirst=True)
    category_enum.drop(bind, checkfirst=True)
    level_enum.drop(bind, checkfirst=True)
    goal_enum.drop(bind, checkfirst=True)
