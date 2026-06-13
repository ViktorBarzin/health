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
from dataclasses import dataclass, replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise, ExerciseMuscle, MuscleRole
from app.models.gym_profile import DEFAULT_EQUIPMENT, GymProfile
from app.models.program import Program, ProgramDay, ProgramMuscleVolume
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.autoregulation import (
    AdjustableSlot,
    AdjustmentResult,
    autoregulate_day,
)
from app.services.effort import rpe_to_rir
from app.services.program_generation import sets_for_slot
from app.services.progression import SetPerformance, next_target
from app.services.recommendation import (
    Recommendation,
    RecommendedExercise,
    is_bodyweight,
)
from app.services.recovery import MuscleSetLoad, muscle_recovery

# Candidate history is read over the same wide window the freestyle path uses, so
# a lift trained infrequently still progresses off its last working set.
_HISTORY_WINDOW = dt.timedelta(weeks=12)

# Recovery is scored over the same trailing window the analytics + freestyle
# paths use (a few half-lives is plenty) so autoregulation reads the same
# per-muscle freshness the heatmap shows.
_RECOVERY_WINDOW = dt.timedelta(weeks=4)


@dataclass(frozen=True)
class ProgramRecommendation:
    """Today's Program-driven proposal plus the context that explains it.

    Wraps the plain :class:`~app.services.recommendation.Recommendation` (so the
    existing ``instantiate_session`` path consumes it unchanged) with the day
    name, the current week, and the deload flag the UI surfaces ("Week 5 of 6 —
    Deload", "Upper A").

    ``autoregulation`` is the result of adjusting the generated day on today's
    biometric **Readiness** and per-muscle **Recovery** (#14): the ``recommendation``
    already reflects the adjusted set counts; this field carries the
    human-readable **reason** ("Readiness 48/100 — trimmed top sets") and the flags
    the UI surfaces. ``early_deload`` is true when sustained low signals tripped a
    fatigue deload earlier than the calendar one.
    """

    recommendation: Recommendation
    program_id: uuid.UUID
    program_name: str
    day_name: str
    day_index: int
    week: int
    total_weeks: int
    is_deload: bool
    autoregulation: AdjustmentResult | None = None
    readiness: float | None = None
    early_deload: bool = False


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


def _session_volume_bounds(program: Program) -> dict[str, tuple[int, int]]:
    """Per-muscle (floor, ceiling) per-SESSION set counts — the autoregulation band.

    Autoregulation may move a slot's set count only **within the Principle-derived
    volume band the Program already encodes**. The ramp's *accumulation* weeks span
    the per-muscle weekly volume floor → top (deload weeks excluded — they're a
    deliberate cut, not the band); dividing each by how many days train the muscle
    (:func:`app.services.program_generation.sets_for_slot`) gives the per-session
    floor and ceiling. So a poor-readiness trim never drops below the week-1 floor's
    per-session share, and a strong-readiness bump never exceeds the volume
    ceiling's — keeping autoregulation inside the evidence window (ADR-0004).
    """
    per_week = _times_trained_per_week(program)
    by_muscle: dict[str, list[int]] = {}
    for v in program.muscle_volumes:
        if v.is_deload:
            continue
        by_muscle.setdefault(v.muscle, []).append(v.target_sets)
    bounds: dict[str, tuple[int, int]] = {}
    for muscle, targets in by_muscle.items():
        times = per_week.get(muscle, 1)
        floor = sets_for_slot(min(targets), times)
        ceiling = sets_for_slot(max(targets), times)
        bounds[muscle] = (max(1, floor), max(floor, ceiling))
    return bounds


def _session_deload_targets(program: Program) -> dict[str, int]:
    """Per-muscle per-SESSION set count at **deload depth**, for an early deload.

    Reuses the Program's *scheduled* deload week — the generator already cut each
    muscle's weekly volume to deload depth (from the deload Principle's
    ``deload_volume_reduction_percent``) on the ``is_deload`` rows — and converts
    that weekly target to a per-session count via the same ``sets_for_slot`` split.
    So a fatigue-triggered early deload cuts the day to exactly the same magnitude
    the calendar deload would, staying within Principle bounds (ADR-0004); no
    re-deriving the percent here keeps a single source of the deload depth.
    """
    per_week = _times_trained_per_week(program)
    targets: dict[str, int] = {}
    for v in program.muscle_volumes:
        if not v.is_deload:
            continue
        times = per_week.get(v.muscle, 1)
        targets[v.muscle] = max(1, sets_for_slot(v.target_sets, times))
    return targets


async def _recovery_map(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> dict[str, float]:
    """Per-muscle Recovery (0–100) for the user, reusing the Recovery core.

    The same per-muscle freshness the heatmap and the freestyle path read,
    duplicated minimally (matching :mod:`app.services.recommendation_query`) so the
    windows stay independent. Feeds autoregulation: a still-fatigued muscle is
    trimmed harder than a fresh one.
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
    rows = (await db.execute(stmt)).all()
    loads = [
        MuscleSetLoad(
            muscle=r.muscle.value if hasattr(r.muscle, "value") else str(r.muscle),
            role=r.role.value if hasattr(r.role, "value") else str(r.role),
            performed_at=r.started_at,
            volume_load=r.weight_kg * r.reps,
            set_type=SetType.normal,
        )
        for r in rows
    ]
    return muscle_recovery(loads, now=now)


async def recommend_from_program(
    db: AsyncSession,
    user_id: int,
    program: Program,
    *,
    now: dt.datetime,
    readiness: float | None = None,
    early_deload: bool = False,
) -> ProgramRecommendation:
    """Today's Recommendation drawn from the active Program's next due day.

    Computes the next due day + current week, then fills each of that day's muscle
    slots with a Gym-Profile-equippable Exercise loaded via Progression at the
    Program's rep range, with per-session sets realising the week's per-muscle
    volume target (deload week reduces it automatically). The day is then
    **autoregulated** on the injected biometric ``readiness`` and the user's
    per-muscle **Recovery** — trimming top sets (within the Program's Principle
    volume band) when fatigue is high, allowing the planned-or-slightly-more when
    strong — with a human-readable reason. Deterministic for fixed ``now`` + DB
    state + injected ``readiness``.
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
    bounds = _session_volume_bounds(program)
    deload_targets = _session_deload_targets(program)

    available = await _equipment(db, user_id)
    history = await _latest_history(db, user_id, now=now)
    recovery = await _recovery_map(db, user_id, now=now)

    rep_range = (program.rep_range_low, program.rep_range_high)

    chosen: list[RecommendedExercise] = []
    slot_muscles: list[str] = []
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
            slot_muscles.append(muscle)

    autoregulation = _autoregulate(
        chosen,
        slot_muscles,
        bounds,
        deload_targets,
        readiness=readiness,
        recovery=recovery,
        early_deload=early_deload,
    )
    chosen = _apply_adjustment(chosen, autoregulation)

    return ProgramRecommendation(
        recommendation=Recommendation(exercises=chosen),
        program_id=program.id,
        program_name=program.name,
        day_name=day.name if day is not None else "",
        day_index=day_index,
        week=week,
        total_weeks=program.total_weeks,
        is_deload=is_deload,
        autoregulation=autoregulation,
        readiness=readiness,
        early_deload=early_deload,
    )


def _autoregulate(
    chosen: list[RecommendedExercise],
    slot_muscles: list[str],
    bounds: dict[str, tuple[int, int]],
    deload_targets: dict[str, int],
    *,
    readiness: float | None,
    recovery: dict[str, float],
    early_deload: bool = False,
) -> AdjustmentResult:
    """Run the pure autoregulator over the generated slots.

    Builds one :class:`~app.services.autoregulation.AdjustableSlot` per chosen
    Exercise — keyed by its **slot muscle** (so the per-muscle Recovery, the
    Principle volume bounds, and the per-muscle deload-depth target apply
    correctly) — and adjusts the day. ``early_deload`` cuts the day to deload depth
    (a fatigue-triggered early deload). The slots come straight from the generator
    (none user-edited here: this is the engine's own proposal, and the start path
    lets the user's later edits win by simply overwriting the instantiated Sets,
    per #11's design).
    """
    slots = [
        AdjustableSlot(
            key=str(ex.exercise_id),
            muscle=muscle,
            sets=ex.target_sets,
            reps=ex.target_reps,
            weight_kg=ex.target_weight_kg,
            sets_floor=bounds.get(muscle, (1, ex.target_sets))[0],
            sets_ceiling=bounds.get(muscle, (1, ex.target_sets))[1],
            user_edited=False,
            deload_sets=deload_targets.get(muscle),
        )
        for ex, muscle in zip(chosen, slot_muscles)
    ]
    return autoregulate_day(
        slots, readiness=readiness, recovery=recovery, early_deload=early_deload
    )


def _apply_adjustment(
    chosen: list[RecommendedExercise], result: AdjustmentResult
) -> list[RecommendedExercise]:
    """Map the autoregulator's adjusted set counts back onto the proposal.

    Only ``target_sets`` changes (autoregulation is a volume lever — reps/weight
    stay with Progression). Order is preserved (the slots were built in proposal
    order), so a positional zip is exact.
    """
    if not result.slots:
        return chosen
    out: list[RecommendedExercise] = []
    for ex, slot in zip(chosen, result.slots):
        if slot.sets == ex.target_sets:
            out.append(ex)
        else:
            out.append(replace(ex, target_sets=slot.sets))
    return out
