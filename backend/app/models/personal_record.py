"""Personal Record model — the persisted, authoritative PR per user/exercise/kind.

CONTEXT.md ("PR"): "A user's personal record for an Exercise — best weight,
reps-at-weight, estimated 1RM, or volume; detected live as a Set is logged
(offline included) and celebrated in the UI."

PR *detection* is a pure function (:mod:`app.services.pr`) that runs both in the
browser (instant, offline) and on the backend. This table is the **record of
truth**: the server recomputes and upserts the authoritative best on sync, so a
client-side celebration that turns out to be wrong (e.g. a since-deleted set, or
an offline set that loses a last-write-wins race) is reconciled here without
duplicates or false PRs.

Storage shape: **one row per (user, exercise, kind, weight_bucket)** holding the
current best ``value`` and a pointer to the Set that achieved it.

* For the three weight-independent kinds (``weight`` / ``e1rm`` / ``volume``)
  there is exactly one row per (user, exercise) — ``weight_bucket`` is NULL.
* For ``reps_at_weight`` the record is per-weight (most reps at *that* load), so
  there is one row per distinct ``weight_bucket``.

Two partial unique indexes enforce "one row per slot" because Postgres treats
NULLs as distinct in a plain composite unique (the same split-by-namespace
pattern the Exercise ``slug`` uses). That uniqueness is what makes the table
queryable without double-counting: the upsert targets the matching index.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.pr import PRKind

# Native Postgres enum for the four PR dimensions, mirroring the SetType/muscle
# enum pattern (typed, GROUP-BY-able). ``values_callable`` stores the enum values
# as the DB labels; ``create_type`` defaults True so metadata create_all (tests)
# provisions it, while the Alembic migration creates it explicitly.
_PR_KIND_ENUM = SAEnum(
    PRKind,
    name="pr_kind",
    values_callable=lambda e: [m.value for m in e],
)


class PersonalRecord(Base):
    """The current best on one PR dimension for a (user, exercise[, weight])."""

    __tablename__ = "personal_records"
    __table_args__ = (
        # One row per slot for the weight-independent kinds (weight_bucket NULL).
        Index(
            "uq_pr_user_exercise_kind",
            "user_id",
            "exercise_id",
            "kind",
            unique=True,
            postgresql_where=text("weight_bucket IS NULL"),
        ),
        # One row per weight for reps_at_weight (weight_bucket NOT NULL).
        Index(
            "uq_pr_user_exercise_kind_weight",
            "user_id",
            "exercise_id",
            "kind",
            "weight_bucket",
            unique=True,
            postgresql_where=text("weight_bucket IS NOT NULL"),
        ),
        # Read path: "this user's PRs for this Exercise" (the celebration + the
        # later PR-aware analytics both hit this).
        Index("ix_pr_user_exercise", "user_id", "exercise_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[PRKind] = mapped_column(_PR_KIND_ENUM, nullable=False)
    # The weight this rep PR was set at; NULL for weight/e1rm/volume kinds.
    weight_bucket: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The record value: kg (weight), estimated kg (e1rm), reps (reps_at_weight),
    # or kg·reps (volume).
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # The Set that holds the record. ON DELETE SET NULL so deleting the Set keeps
    # the (recomputed-on-sync) record row rather than cascading it away.
    achieved_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_sets.id", ondelete="SET NULL"),
        nullable=True,
    )
    achieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
