"""Per-muscle weekly volume — the trailing-window rollup off ``exercise_muscles``.

A muscle-grouped aggregate of a user's recent Set volume: how many working Sets
and how much volume-load (``weight × reps``) each muscle group has absorbed over a
trailing window. It powers the volume side of the analytics heatmap now and the
Recommendation engine's weekly-volume targets later (ADR-0002).

It is the SQL counterpart to :mod:`app.services.recovery`: where Recovery weights
by time-decay, this is a flat trailing-window sum. Both attribute load to muscles
through the normalized ``exercise_muscles`` mapping — the whole reason that
mapping is a GROUP-BY-able typed dimension and not JSON (see
``app/models/exercise.py``). Rows are split by ``role`` (primary/secondary) so a
caller can count "primary working sets per muscle" the way competitor heatmaps do,
or fold in secondary work with its own weighting.

The non-normal-Set exclusion is **not re-derived here**: the query filters
``set_type = 'normal'`` using the single canonical value owned by
:func:`app.services.volume.counts_for_volume` (CONTEXT.md "Set"). ``now`` is a
parameter (not ``func.now()``) so the window is deterministic and testable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import Float, Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import ExerciseMuscle, Muscle, MuscleRole
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.volume import counts_for_volume


@dataclass(frozen=True)
class MuscleVolumeRow:
    """One muscle group's volume over the window: its role, set count, and load.

    ``muscle`` and ``role`` are the enum *values* (e.g. ``"chest"``,
    ``"primary"``) so the row serialises straight onto the wire / into the
    heatmap without leaking ORM types. A muscle worked both as a primary and a
    secondary mover (by different Exercises) yields two rows — one per role.
    """

    muscle: str
    role: str
    set_count: int
    volume_load: float


# The one set type that counts toward volume. We reference the canonical rule
# (volume.counts_for_volume — the CONTEXT.md exclusion's single source) rather
# than independently re-listing the excluded types: it accepts exactly normal, so
# filtering the query to this value is the SQL form of the same rule.
_NORMAL = SetType.normal
assert counts_for_volume(_NORMAL) and not any(
    counts_for_volume(t) for t in SetType if t is not _NORMAL
)


async def weekly_muscle_volume(
    session: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    weeks: int = 4,
) -> list[MuscleVolumeRow]:
    """Per-muscle (and role) set count + volume-load over the trailing ``weeks``.

    Joins the user's ``training_sets`` → owning ``training_sessions`` (for the
    timestamp and ownership) → the Exercise's ``exercise_muscles`` rows, keeps
    only ``normal`` Sets started on/after ``now - weeks``, and groups by
    ``(muscle, role)``. ``set_count`` counts the contributing Sets; ``volume_load``
    sums ``weight_kg × reps``. Ordered by volume-load descending so the heaviest-
    hit muscles surface first. Empty history ⇒ ``[]``.
    """
    window_start = now - dt.timedelta(weeks=weeks)

    volume_load = func.sum(TrainingSet.weight_kg * TrainingSet.reps)
    stmt = (
        select(
            ExerciseMuscle.muscle.label("muscle"),
            ExerciseMuscle.role.label("role"),
            cast(func.count(TrainingSet.id), Integer).label("set_count"),
            cast(volume_load, Float).label("volume_load"),
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .join(ExerciseMuscle, ExerciseMuscle.exercise_id == TrainingSet.exercise_id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == _NORMAL,
            TrainingSession.started_at >= window_start,
        )
        .group_by(ExerciseMuscle.muscle, ExerciseMuscle.role)
        .order_by(volume_load.desc())
    )

    result = await session.execute(stmt)
    return [
        MuscleVolumeRow(
            muscle=_enum_value(row.muscle),
            role=_enum_value(row.role),
            set_count=int(row.set_count),
            volume_load=float(row.volume_load or 0.0),
        )
        for row in result.all()
    ]


def _enum_value(v: Muscle | MuscleRole | str) -> str:
    """Return the wire string for a muscle/role, whether the driver hands back the
    Python enum member or its raw string label."""
    return v.value if isinstance(v, (Muscle, MuscleRole)) else str(v)


async def weekly_set_series(
    db: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    weeks: int = 12,
) -> list[dict]:
    """Counted (normal) Sets per ISO week over the trailing window — the
    training-volume series the body-comp overlay chart plots (plan M6).

    One row per week that HAD training, ``{"week_start": ISO date, "sets": n}``,
    oldest first. Weeks with no Sets are simply absent (the chart shows gaps
    honestly rather than fabricating zeros for pre-history).
    """
    window_start = now - dt.timedelta(weeks=weeks)
    week_bucket = func.date_trunc("week", TrainingSession.started_at)
    stmt = (
        select(
            week_bucket.label("wk"),
            func.count(TrainingSet.id).label("sets"),
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == SetType.normal,
            TrainingSession.started_at >= window_start,
        )
        .group_by(week_bucket)
        .order_by(week_bucket)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"week_start": r.wk.date().isoformat(), "sets": int(r.sets)} for r in rows
    ]
