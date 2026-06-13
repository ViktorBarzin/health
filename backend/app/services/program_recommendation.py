"""Program-driven daily Recommendation — the active-Program path (#13, ADR-0004).

CONTEXT.md ("Recommendation"): "drawn from the active Program when one is running,
freestyle otherwise". This is the **active-Program** branch
:mod:`app.services.recommendation_query` delegates to when the user has an active
Program: today's proposal is the Program's prescription for the **next due
training day**, its muscle slots filled with concrete Exercises (constrained by
the Gym Profile, loaded via the existing **Progression** core), with the
**deload** week reducing volume on schedule. The freestyle path is unchanged and
used when no Program is active.

What "next due" and "current week" mean (deterministic, clock-injected)
=======================================================================
* **Next due day** = ``(# Sessions the user started since the Program's
  created_at) mod days_per_week`` → the :class:`~app.models.program.ProgramDay` at
  that ``day_index``. So the split rotates as the user logs Sessions, and a fresh
  Program starts at day 0.
* **Current week** = ``min(weeks_elapsed + 1, total_weeks)`` (whole weeks since
  ``created_at``, capped) — drives which row of the ramping per-muscle volume
  applies, and whether today is the **deload** week.

Per slot, the per-session set count realises that muscle's *weekly* target split
across the days that train it that week
(:func:`app.services.program_generation.sets_for_slot`), so following the Program
over the week hits the weekly volume; the rep range + effort target are the
Program's (themselves Principle-derived). Exercise selection prefers a movement
the user has **trained** for that muscle (so Progression has real history), else
any library Exercise with that muscle as a **primary** mover that the Gym Profile
can equip — a Program legitimately introduces new movements.

Pure-ish: all DB reads are here; the numeric work is the Program (already
generated from Principles) and the Progression core. ``now`` is injected so a
fixed DB state yields a fixed proposal.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise, ExerciseMuscle, MuscleRole
from app.models.gym_profile import DEFAULT_EQUIPMENT, GymProfile
from app.models.program import Program, ProgramDay, ProgramMuscleVolume
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.effort import rpe_to_rir
from app.services.program_generation import sets_for_slot
from app.services.progression import SetPerformance, next_target
from app.services.recommendation import (
    Recommendation,
    RecommendedExercise,
    is_bodyweight,
)

# Candidate history is read over the same wide window the freestyle path uses, so
# a lift trained infrequently still progresses off its last working set.
_HISTORY_WINDOW = dt.timedelta(weeks=12)


@dataclass(frozen=True)
class ProgramRecommendation:
    """Today's Program-driven proposal plus the context that explains it.

    Wraps the plain :class:`~app.services.recommendation.Recommendation` (so the
    existing ``instantiate_session`` path consumes it unchanged) with the day
    name, the current week, and the deload flag the UI surfaces ("Week 5 of 6 —
    Deload", "Upper A").
    """

    recommendation: Recommendation
    program_id: uuid.UUID
    program_name: str
    day_name: str
    day_index: int
    week: int
    total_weeks: int
    is_deload: bool


def _weeks_elapsed(created_at: dt.datetime, now: dt.datetime) -> int:
    """Whole weeks between ``created_at`` and ``now`` (>= 0, tz-tolerant)."""
    a, b = now, created_at
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    days = max(0.0, (a - b).total_seconds() / 86400.0)
    return int(days // 7)


async def _session_count_since(
    db: AsyncSession, user_id: int, since: dt.datetime
) -> int:
    """How many Sessions the user has started since the Program began."""
    stmt = (
        select(func.count())
        .select_from(TrainingSession)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSession.started_at >= since,
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def _equipment(db: AsyncSession, user_id: int) -> frozenset[str]:
    """The user's Gym Profile equipment (defaults if they have no profile)."""
    equipment = (
        await db.execute(
            select(GymProfile.equipment).where(GymProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    return frozenset(equipment if equipment is not None else DEFAULT_EQUIPMENT)


def _can_equip(equipment: str | None, available: frozenset[str]) -> bool:
    """Whether the Gym Profile can equip an Exercise (bodyweight always can)."""
    return is_bodyweight(equipment) or equipment in available


async def _latest_history(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> dict[uuid.UUID, SetPerformance]:
    """Most-recent working Set per Exercise the user has trained (for Progression).

    Mirrors the freestyle query's history read: newest normal Set per Exercise in
    the history window. Used to progress a slot's chosen Exercise off real history.
    """
    window_start = now - _HISTORY_WINDOW
    stmt = (
        select(
            TrainingSet.exercise_id,
            TrainingSession.started_at,
            TrainingSet.order_index,
            TrainingSet.weight_kg,
            TrainingSet.reps,
            TrainingSet.rpe,
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == SetType.normal,
            TrainingSession.started_at >= window_start,
            TrainingSet.weight_kg > 0,
            TrainingSet.reps > 0,
        )
        .order_by(
            TrainingSession.started_at.desc(),
            TrainingSet.order_index.desc(),
        )
    )
    rows = (await db.execute(stmt)).all()
    latest: dict[uuid.UUID, SetPerformance] = {}
    for r in rows:
        if r.exercise_id in latest:
            continue
        latest[r.exercise_id] = SetPerformance(
            weight_kg=r.weight_kg, reps=r.reps, rir=rpe_to_rir(r.rpe)
        )
    return latest


async def _exercises_for_muscle(
    db: AsyncSession, user_id: int, muscle: str
) -> list[tuple[Exercise, list[str], list[str]]]:
    """Library Exercises (global ∪ the user's own) with ``muscle`` as a PRIMARY mover.

    Returns ``(exercise, primary_muscle_values, secondary_muscle_values)`` ordered
    by Exercise id for determinism. Primary-mover only, so a slot for "chest" gets
    a chest movement, not an incidental one.
    """
    stmt = (
        select(Exercise)
        .join(ExerciseMuscle, ExerciseMuscle.exercise_id == Exercise.id)
        .where(
            ExerciseMuscle.muscle == muscle,
            ExerciseMuscle.role == MuscleRole.primary,
            (Exercise.user_id == user_id) | (Exercise.user_id.is_(None)),
        )
        .order_by(Exercise.id)
    )
    exercises = (await db.execute(stmt)).scalars().unique().all()
    out: list[tuple[Exercise, list[str], list[str]]] = []
    for ex in exercises:
        prim = [m.muscle.value for m in ex.muscles if m.role == MuscleRole.primary]
        sec = [m.muscle.value for m in ex.muscles if m.role == MuscleRole.secondary]
        out.append((ex, prim, sec))
    return out


def _pick_exercise(
    candidates: list[tuple[Exercise, list[str], list[str]]],
    *,
    available: frozenset[str],
    history: dict[uuid.UUID, SetPerformance],
    used: set[uuid.UUID],
):
    """Choose one equip-able Exercise for a slot: trained-and-unused first.

    Preference order (each restricted to Exercises the Gym Profile can equip and
    not already used today, so a day doesn't repeat a movement):
    1. one the user has **trained** (history exists) → real Progression;
    2. otherwise the first library Exercise (deterministic, id-ordered).
    Falls back to allowing a re-use only if every candidate is already used.
    Returns ``(exercise, primary, secondary)`` or ``None`` if nothing fits.
    """
    equippable = [c for c in candidates if _can_equip(c[0].equipment, available)]
    if not equippable:
        return None
    fresh = [c for c in equippable if c[0].id not in used]
    pool = fresh or equippable
    trained = [c for c in pool if c[0].id in history]
    if trained:
        return trained[0]
    return pool[0]


def _volume_by_muscle(program: Program, week: int) -> dict[str, ProgramMuscleVolume]:
    """The (muscle → volume row) map for one week of the Program."""
    return {v.muscle: v for v in program.muscle_volumes if v.week == week}


def _times_trained_per_week(program: Program) -> Counter:
    """How many training days in the week include each muscle (for set splitting)."""
    counts: Counter = Counter()
    for day in program.days:
        for slot in day.slots:
            counts[slot["muscle"]] += 1
    return counts


async def recommend_from_program(
    db: AsyncSession,
    user_id: int,
    program: Program,
    *,
    now: dt.datetime,
) -> ProgramRecommendation:
    """Today's Recommendation drawn from the active Program's next due day.

    Computes the next due day + current week, then fills each of that day's muscle
    slots with a Gym-Profile-equippable Exercise loaded via Progression at the
    Program's rep range, with per-session sets realising the week's per-muscle
    volume target (deload week reduces it automatically). Deterministic for fixed
    ``now`` + DB state.
    """
    days_per_week = program.days_per_week
    started = await _session_count_since(db, user_id, program.created_at)
    day_index = started % days_per_week if days_per_week else 0
    day: ProgramDay | None = next(
        (d for d in program.days if d.day_index == day_index), None
    )
    week = min(_weeks_elapsed(program.created_at, now) + 1, program.total_weeks)
    volume = _volume_by_muscle(program, week)
    is_deload = any(v.is_deload for v in volume.values())
    per_week = _times_trained_per_week(program)

    available = await _equipment(db, user_id)
    history = await _latest_history(db, user_id, now=now)

    rep_range = (program.rep_range_low, program.rep_range_high)

    chosen: list[RecommendedExercise] = []
    used: set[uuid.UUID] = set()
    if day is not None:
        for slot in day.slots:
            muscle = slot["muscle"]
            candidates = await _exercises_for_muscle(db, user_id, muscle)
            pick = _pick_exercise(
                candidates, available=available, history=history, used=used
            )
            if pick is None:
                continue
            exercise, primary, secondary = pick
            used.add(exercise.id)

            target = next_target(
                (history[exercise.id],) if exercise.id in history else (),
                rep_range=rep_range,
            )
            week_target = volume[muscle].target_sets if muscle in volume else 0
            sets = sets_for_slot(week_target, per_week.get(muscle, 1))
            chosen.append(
                RecommendedExercise(
                    exercise_id=exercise.id,
                    name=exercise.name,
                    target_sets=sets,
                    target_reps=target.reps,
                    target_weight_kg=target.weight_kg,
                    is_starting_point=target.is_starting_point,
                    primary_muscles=tuple(sorted(primary)),
                    secondary_muscles=tuple(sorted(secondary)),
                )
            )

    return ProgramRecommendation(
        recommendation=Recommendation(exercises=chosen),
        program_id=program.id,
        program_name=program.name,
        day_name=day.name if day is not None else "",
        day_index=day_index,
        week=week,
        total_weeks=program.total_weeks,
        is_deload=is_deload,
    )
