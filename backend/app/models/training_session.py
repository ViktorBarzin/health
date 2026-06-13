"""Training Session and Set models — the live gym-logging core.

Vocabulary (CONTEXT.md, *strictly* observed here):

* A **Session** is "a gym workout logged live in the app by the user — an ordered
  list of Sets". It is NOT a *Workout* (that word is reserved for an imported
  sensor record from a device — a separate future table). To keep the SQL/Python
  identifiers unambiguous — ``session`` collides with the auth-session concept and
  ``set`` is a SQL reserved word — the tables are named ``training_sessions`` and
  ``training_sets`` (the API/URL vocabulary stays the clean "session"/"set").
* A **Set** is "one performed set within a Session: an Exercise, weight × reps,
  optional Effort, and a set type — normal, warmup, drop, or failure. Non-normal
  types are excluded from volume and PR statistics by default."
* **Effort** is stored as its RPE-equivalent (see :mod:`app.services.effort`);
  the column is ``rpe`` and is nullable because Effort is optional on every Set.

Design choices for this slice (online logging only):

* Both are entity tables with **UUID** primary keys (matching ``workouts`` and
  ``exercises``) — a Set is individually addressable for reorder/edit/delete and
  has no timestamp of its own, so a time-series composite PK doesn't fit.
* Set order within a Session is an explicit 0-based ``order_index`` integer,
  maintained server-side. A unique ``(session_id, order_index)`` keeps the order
  total and gap-free per Session; reordering rewrites the indices.
* ``set_type`` is a native Postgres enum so later volume/PR analytics filter on a
  typed dimension (the same pattern as the Exercise muscle enums).
* Supersets are explicitly out of scope for this slice (#7); no group column is
  added yet.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SetType(str, enum.Enum):
    """How a Set counts. CONTEXT.md: the four set types.

    Only ``normal`` counts toward volume and PR statistics by default; the other
    three are logged for completeness but excluded (see
    :mod:`app.services.volume`). A typed dimension, not free text, so later
    analytics can ``GROUP BY``/filter it.
    """

    normal = "normal"
    warmup = "warmup"
    drop = "drop"
    failure = "failure"


# SQLAlchemy Enum type. ``values_callable`` stores the enum *values* as the DB
# labels (consistent with the Exercise muscle enums). ``create_type`` defaults to
# True so metadata-driven ``create_all`` (the test suite) provisions the Postgres
# type; the Alembic migration creates it explicitly with ``create_type=False``.
_SET_TYPE_ENUM = SAEnum(
    SetType,
    name="set_type",
    values_callable=lambda e: [m.value for m in e],
)


class TrainingSession(Base):
    """A live-logged gym Session: a per-user, ordered list of Sets."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        # The common read: "this user's recent Sessions, newest first."
        Index("ix_training_sessions_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # When the user started logging. Defaults to now() on create ("start a
    # Session"); ``ended_at`` is set when they finish and stays NULL while live.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sets: Mapped[list["TrainingSet"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TrainingSet.order_index",
        lazy="selectin",
    )

    @property
    def is_active(self) -> bool:
        """True while the Session is still being logged (not yet finished)."""
        return self.ended_at is None


class TrainingSet(Base):
    """One performed Set within a Session: an Exercise, weight × reps, etc."""

    __tablename__ = "training_sets"
    __table_args__ = (
        # Order is total and gap-free per Session; reordering rewrites indices.
        UniqueConstraint(
            "session_id", "order_index", name="uq_training_set_session_order"
        ),
        # Fetch a Session's Sets in order; also the FK lookup path.
        Index("ix_training_sets_session_order", "session_id", "order_index"),
        # Analytics/PR (later slices): a user's Set history for one Exercise.
        Index("ix_training_sets_exercise", "exercise_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Exactly one Exercise from the shared library (global or the user's custom).
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # 0-based position within the Session.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Weight in kilograms (the platform's canonical unit) and whole/partial reps.
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    # Effort as its RPE-equivalent (see app.services.effort); NULL = not rated.
    rpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    set_type: Mapped[SetType] = mapped_column(
        _SET_TYPE_ENUM, nullable=False, default=SetType.normal
    )

    session: Mapped["TrainingSession"] = relationship(back_populates="sets")
    exercise: Mapped["Exercise"] = relationship(lazy="selectin")  # noqa: F821


from app.models.exercise import Exercise  # noqa: E402,F401  (resolve relationship)
