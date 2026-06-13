"""Program models — a generated, multi-week training schedule (ADR-0004).

CONTEXT.md ("Program"): "A generated multi-week training schedule serving the
user's Goal — split structure, ramping weekly per-muscle volume targets,
progression scheme, and Deloads. Entered via a guided quiz or picked from a
catalog of named presets; never user-authored." ADR-0004 makes the generator
compose Programs *only* from the cited Principles KB, so every numeric parameter
traces to a study.

Why three tables (entity-style UUID PKs, matching ``workouts`` / ``exercises`` /
``training_sessions``):

* :class:`Program` — the Program header: the Goal, days/week, the chosen split's
  shape parameters (mesocycle length, deload week), the ``status`` (one **active**
  per user), and the **provenance** JSONB — the receipt mapping every Program-level
  parameter to the Principle ``key`` and the value/range it came from, so #14's
  receipts UI can render "why this number".
* :class:`ProgramDay` — the split: one row per training day in the weekly
  microcycle (``days_per_week`` rows), each carrying its ordered muscle **slots**
  (JSONB list of ``{muscle, ...}``) the Recommendation fills with Exercises.
* :class:`ProgramMuscleVolume` — the **ramping weekly volume target**: one row per
  (muscle, week), so the per-muscle weekly sets ramp up across the mesocycle and
  drop on the scheduled deload week. Stored (not recomputed) because it is the
  receipt the overview renders and the signal #14 autoregulates against.

The generator (the pure :mod:`app.services.program_generation`) produces these;
this module is only the persistence shape. ``provenance`` and ``slots`` are JSONB
read-whole/write-whole structures, matching the repo's existing convention (Gym
Profile lists, Principle params).
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.exercise import _MUSCLE_ENUM, Muscle  # reuse the muscle enum
from app.models.principle import _GOAL_ENUM, _LEVEL_ENUM  # reuse Goal/level enums


class ProgramStatus(str, enum.Enum):
    """Lifecycle of a generated Program.

    ``active`` = the one Program currently driving the daily Recommendation (at
    most one per user, enforced by a partial unique index). ``archived`` = a prior
    Program, kept for history (generating a new one archives the old rather than
    deleting it) and re-activatable.
    """

    active = "active"
    archived = "archived"


# ``values_callable`` stores the enum *values* as the DB labels (matching the
# other enums in this codebase). ``create_type`` defaults True so metadata-driven
# ``create_all`` (the test suite) provisions it; the Alembic migration creates it
# explicitly for real databases.
_STATUS_ENUM = SAEnum(
    ProgramStatus,
    name="program_status",
    values_callable=lambda e: [m.value for m in e],
)


class Program(Base):
    """A generated multi-week Program header serving a user's Goal."""

    __tablename__ = "programs"
    __table_args__ = (
        # At most ONE active Program per user — the one that drives the daily
        # Recommendation. A partial unique index (NULLs/archived rows don't
        # collide) is the same pattern the Exercise/PR tables use.
        Index(
            "uq_program_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        # The common read: a user's Programs.
        Index("ix_programs_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # The catalog preset this was generated from (``gzclp`` …), or NULL for a
    # bespoke quiz. Not a FK — presets are code-defined data, not a DB table.
    preset_key: Mapped[str | None] = mapped_column(String, nullable=True)
    goal: Mapped[str] = mapped_column(_GOAL_ENUM, nullable=False)
    experience: Mapped[str] = mapped_column(_LEVEL_ENUM, nullable=False)
    days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    session_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Accumulation weeks before the deload, and the totals derived from it.
    mesocycle_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    total_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1-based week index that is the scheduled deload (== total_weeks).
    deload_week: Mapped[int] = mapped_column(Integer, nullable=False)
    # The working prescription parameters (each Principle-derived; their source is
    # in ``provenance``): the goal rep range and the effort (RIR) target the daily
    # Recommendation prescribes. Stored as first-class columns (not only in the
    # receipt) because the recommendation path reads them directly.
    rep_range_low: Mapped[int] = mapped_column(Integer, nullable=False)
    rep_range_high: Mapped[int] = mapped_column(Integer, nullable=False)
    effort_rir: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ProgramStatus] = mapped_column(
        _STATUS_ENUM, nullable=False, default=ProgramStatus.active
    )
    # Receipt: {param_name: {principle_key, value, unit?, min?, max?}} — every
    # Program-level number's source Principle, for the #14 receipts UI.
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    days: Mapped[list["ProgramDay"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="ProgramDay.day_index",
        lazy="selectin",
    )
    muscle_volumes: Mapped[list["ProgramMuscleVolume"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="ProgramMuscleVolume.week",
        lazy="selectin",
    )


class ProgramDay(Base):
    """One training day in the weekly microcycle: its ordered muscle slots.

    ``slots`` is a JSONB list of ``{"muscle": <muscle enum value>, ...}`` — the
    ordered exercise slots the Recommendation fills with concrete Exercises
    (constrained by the Gym Profile, loaded via the Progression core). A day is the
    structural unit of the split (e.g. "Upper A", "Push").
    """

    __tablename__ = "program_days"
    __table_args__ = (
        Index("uq_program_day", "program_id", "day_index", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 0-based position within the training week (0 = the first training day).
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Ordered exercise slots: [{"muscle": "chest"}, {"muscle": "triceps"}, …].
    slots: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)

    program: Mapped["Program"] = relationship(back_populates="days")


class ProgramMuscleVolume(Base):
    """A per-muscle weekly volume target for one week of the Program.

    The ramping volume signal: one row per (muscle, week). ``target_sets`` ramps up
    across the accumulation weeks (from the Principle volume floor toward its top)
    and drops on the deload week (``is_deload`` true). Only muscles the split
    actually trains get rows.
    """

    __tablename__ = "program_muscle_volumes"
    __table_args__ = (
        Index("uq_program_muscle_week", "program_id", "muscle", "week", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    muscle: Mapped[Muscle] = mapped_column(_MUSCLE_ENUM, nullable=False)
    # 1-based week index.
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    target_sets: Mapped[int] = mapped_column(Integer, nullable=False)
    is_deload: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    program: Mapped["Program"] = relationship(back_populates="muscle_volumes")
