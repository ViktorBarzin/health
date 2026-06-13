"""reconcile existing users to their Authentik identities

ADR-0003: with WebAuthn retired, the 3 existing prod users are mapped to the
emails their Authentik identities present:
  - ancaelena98@yahoo.com -> ancaelena98@gmail.com (rename)
  - me@viktorbarzin.me MERGED INTO vbarzin@gmail.com (reassign all owned rows,
    then delete the empty me@ user)

The logic lives in app.migrations_support.user_reconciliation and is unit-tested
there. It is idempotent and acts only on rows that exist, so it is safe to run on
any database (dev, fresh, or prod) — no-op where the identities are absent. This
is a one-way data fix: downgrade does not un-merge.

Revision ID: b8c2d4e6f0a1
Revises: a7d3f9b2c1e4
Create Date: 2026-06-13 00:05:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.migrations_support.user_reconciliation import reconcile_identities

revision: str = "b8c2d4e6f0a1"
down_revision: Union[str, None] = "a7d3f9b2c1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    reconcile_identities(op.get_bind())


def downgrade() -> None:
    # A data reconciliation cannot be safely reversed: the me@ user's rows have
    # been folded into vbarzin@ and colliding duplicates discarded. No-op.
    pass
