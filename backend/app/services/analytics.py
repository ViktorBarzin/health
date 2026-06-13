"""Analytics query layer — binds the pure cores to a user's logged Sets.

The DB-touching glue for the training-analytics endpoints (#10). The maths lives
in the pure cores (:mod:`app.services.recovery`, :mod:`app.services.e1rm`); this
module only fetches the right rows and feeds them in:

* :func:`recovery_for_user` — expand a user's recent normal Sets into per-muscle
  load events (via ``exercise_muscles``) and run them through the Recovery core;
* :func:`e1rm_trend_for_user` — a chronological estimated-1RM series for one
  Exercise, one point per normal Set, reusing the canonical Effort-adjusted Epley.

Per-muscle weekly volume has its own module (:mod:`app.services.muscle_volume`)
since it is a pure SQL GROUP-BY with no core to feed.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise, ExerciseMuscle
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.e1rm import estimated_1rm
from app.services.effort import rpe_to_rir
from app.services.recovery import (
    DEFAULT_HALF_LIFE_HOURS,
    MuscleSetLoad,
    muscle_recovery,
)

# How far back to read Set history when scoring Recovery. Fatigue decays by the
# half-life, so contributions older than several half-lives are negligible; a
# 4-week window captures everything that still matters while bounding the scan.
_RECOVERY_WINDOW = dt.timedelta(weeks=4)


async def recovery_for_user(
    session: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
) -> dict[str, float]:
    """Per-muscle Recovery (0–100) for a user as of ``now``.

    Reads the user's normal Sets from the trailing recovery window joined to their
    Exercise's ``exercise_muscles`` rows, turns each (Set × muscle-role) into a
    :class:`~app.services.recovery.MuscleSetLoad` carrying the Set's volume-load
    and timestamp, and defers to the pure core. Returns only muscles that carry
    fatigue; the API fills the untrained remainder at 100. ``now`` is injected, so
    given the same rows the result is deterministic.
    """
    window_start = now - _RECOVERY_WINDOW
    stmt = (
        select(
            ExerciseMuscle.muscle,
            ExerciseMuscle.role,
            TrainingSession.started_at,
            TrainingSet.weight_kg,
            TrainingSet.reps,
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .join(ExerciseMuscle, ExerciseMuscle.exercise_id == TrainingSet.exercise_id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == SetType.normal,
            TrainingSession.started_at >= window_start,
        )
    )
    rows = (await session.execute(stmt)).all()
    loads = [
        MuscleSetLoad(
            muscle=row.muscle.value if hasattr(row.muscle, "value") else str(row.muscle),
            role=row.role.value if hasattr(row.role, "value") else str(row.role),
            performed_at=row.started_at,
            volume_load=row.weight_kg * row.reps,
            set_type=SetType.normal,
        )
        for row in rows
    ]
    return muscle_recovery(loads, now=now, half_life_hours=half_life_hours)


async def e1rm_trend_for_user(
    session: AsyncSession,
    user_id: int,
    exercise_id: uuid.UUID,
    *,
    since: dt.datetime | None = None,
) -> list[tuple[dt.datetime, float]]:
    """Chronological ``(time, e1rm)`` points for one Exercise's normal Sets.

    One point per PR-eligible Set (``normal``, positive weight and reps — the same
    guard the PR core applies), timed by the owning Session's ``started_at`` and
    valued by the canonical Effort-adjusted Epley (:func:`estimated_1rm`, fed the
    Set's RIR recovered from its stored RPE). Oldest first, so a line chart reads
    left-to-right. Scoped to ``user_id`` — another user's Sets never appear.
    """
    stmt = (
        select(
            TrainingSession.started_at,
            TrainingSet.weight_kg,
            TrainingSet.reps,
            TrainingSet.rpe,
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.exercise_id == exercise_id,
            TrainingSet.set_type == SetType.normal,
        )
        .order_by(TrainingSession.started_at)
    )
    if since is not None:
        stmt = stmt.where(TrainingSession.started_at >= since)

    rows = (await session.execute(stmt)).all()
    points: list[tuple[dt.datetime, float]] = []
    for row in rows:
        if row.weight_kg <= 0 or row.reps <= 0:
            continue
        e1rm = estimated_1rm(row.weight_kg, row.reps, rir=rpe_to_rir(row.rpe))
        points.append((row.started_at, e1rm))
    return points


async def trained_exercises_for_user(
    session: AsyncSession,
    user_id: int,
) -> list[tuple[uuid.UUID, str]]:
    """``(exercise_id, name)`` for the Exercises a user has logged normal Sets for.

    The source for the e1RM-trend picker: only Exercises that actually have a
    PR-eligible (``normal``) Set in the user's history, so the dropdown lists what
    the user has trained rather than the whole ~870-row catalog. Ordered by name.
    """
    stmt = (
        select(Exercise.id, Exercise.name)
        .join(TrainingSet, TrainingSet.exercise_id == Exercise.id)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == SetType.normal,
        )
        .distinct()
        .order_by(Exercise.name)
    )
    rows = (await session.execute(stmt)).all()
    return [(row.id, row.name) for row in rows]
