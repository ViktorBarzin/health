"""add metric_daily rollup table (ADR-0009)

Adds ``metric_daily`` — the daily per-metric rollup of ``health_records`` that the
dashboard/metrics read path reads instead of aggregating ~1M raw rows per
wide-window load (ADR-0009). One row per ``(user_id, metric_type, day)`` storing
``count`` / ``sum`` / ``min`` / ``max`` (avg is derived = sum/count) plus a
representative ``unit``; the composite PK ``(user_id, metric_type, day)`` is the
natural key the targeted post-ingest recompute upserts on.

The table is **derived data** — populated by a one-time backfill (a single
``GROUP BY user_id, metric_type, date_trunc('day', time)`` over the existing rows,
run once at deploy / on demand via ``python -m app.services.rollup``) and kept
fresh by a targeted recompute of the buckets each ingest batch touched. It carries
no data the raw table doesn't; a full rebuild is the recovery path.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-14 03:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'metric_daily',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('metric_type', sa.String(), nullable=False),
        # The UTC calendar day (date_trunc('day', time)::date).
        sa.Column('day', sa.Date(), nullable=False),
        # Aggregates over the raw readings in this (user, metric, day). avg is
        # derived (sum / count) and intentionally NOT stored.
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('sum', sa.Float(), nullable=False),
        sa.Column('min', sa.Float(), nullable=False),
        sa.Column('max', sa.Float(), nullable=False),
        # Representative unit for the day (max(unit)); nullable for safety.
        sa.Column('unit', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'metric_type', 'day'),
    )


def downgrade() -> None:
    op.drop_table('metric_daily')
