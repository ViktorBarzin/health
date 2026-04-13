"""track import errors and activity summary batches

Revision ID: f7b9c1d2e3f4
Revises: e6f0a4b8c3d5
Create Date: 2026-04-13 23:59:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7b9c1d2e3f4"
down_revision: Union[str, None] = "e6f0a4b8c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activity_summaries",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_activity_summaries_batch_id_import_batches",
        "activity_summaries",
        "import_batches",
        ["batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_activity_summaries_batch_id",
        "activity_summaries",
        ["batch_id"],
    )
    op.add_column(
        "import_batches",
        sa.Column("error_message", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("import_batches", "error_message")
    op.drop_index("ix_activity_summaries_batch_id", table_name="activity_summaries")
    op.drop_constraint(
        "fk_activity_summaries_batch_id_import_batches",
        "activity_summaries",
        type_="foreignkey",
    )
    op.drop_column("activity_summaries", "batch_id")
