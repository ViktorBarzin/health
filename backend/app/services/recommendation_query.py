"""Recommendation query layer — binds the freestyle generator to a user's data.

The DB-touching glue for the freestyle Recommendation endpoint (#11), mirroring
:mod:`app.services.analytics`: the maths lives in the pure cores
(:mod:`app.services.recommendation`, :mod:`app.services.progression`,
:mod:`app.services.recovery`); this module only fetches the right rows and feeds
them in, then (on *start*) instantiates the proposed Session.

Candidate population
====================
The freestyle generator proposes from the Exercises the user **has trained**
(those with PR-eligible *normal* Set history), the same population the e1RM-trend
picker uses (:func:`app.services.analytics.trained_exercises_for_user`). Two
reasons, both deliberate:

* Progression *is* "the per-exercise next-target logic derived from that
  exercise's Set history" (CONTEXT.md) — every prescription is then a real
  progression off real history, not a weight-0 guess for an Exercise the user
  has never touched;
* it keeps generation fast and fully deterministic over a bounded set.

Proposing brand-new Exercises (cold-start variety) is a Program-layer / LLM-layer
concern (#13/#14); the deterministic freestyle core sticks to training history
(the task's "training-history-only" guard). If the user has logged nothing, the
proposal is empty and the UI guides them to log first.

The "now" used for Recovery is injected by the caller (the route passes request
time) so the binding stays as deterministic as the cores it feeds.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise, ExerciseMuscle, MuscleRole
from app.models.gym_profile import DEFAULT_EQUIPMENT, GymProfile
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.adjust import (
    Adjustment,
    AdjustmentBounds,
    AdjustProvider,
    apply_adjustment,
    validate_adjustment,
)
from app.services.adjust_agent import propose_adjustment
from app.services.recommendation import (
    DEFAULT_EXERCISE_COUNT,
    DEFAULT_SETS_PER_EXERCISE,
    ExerciseCandidate,
    Recommendation,
    generate_recommendation,
)
from app.services.progression import SetPerformance
from app.services.recovery import muscle_recovery, MuscleSetLoad
from app.services.effort import rpe_to_rir
from app.services.autoregulation import early_deload_triggered
from app.services.program_query import active_program
from app.services.program_recommendation import (
    ProgramRecommendation,
    recommend_from_program,
)
from app.services.readiness_query import readiness_for_user, recent_daily_readiness

# Recovery is scored over the same trailing window the analytics layer uses (a
# few half-lives is plenty); candidate history is read over a wider window so a
# user who trains a lift infrequently still gets a progression off their last
# session.
_RECOVERY_WINDOW = dt.timedelta(weeks=4)
_HISTORY_WINDOW = dt.timedelta(weeks=12)


async def _gym_equipment(db: AsyncSession, user_id: int) -> list[str]:
    """The user's Gym Profile equipment list (defaults if they have no profile).

    The Gym Profile is a get-or-created singleton; for a *read* path we don't
    materialise a row, we just fall back to the standard metric-gym defaults so a
    brand-new user still gets a sensible equipment-filtered proposal.
    """
    equipment = (
        await db.execute(
            select(GymProfile.equipment).where(GymProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    return list(equipment) if equipment is not None else list(DEFAULT_EQUIPMENT)


async def _recovery_map(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> dict[str, float]:
    """Per-muscle Recovery (0–100) for the user, reusing the Recovery core.

    Same shape as :func:`app.services.analytics.recovery_for_user` (duplicated
    minimally rather than imported to keep the windows independent).
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


async def _candidates(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> list[ExerciseCandidate]:
    """Build a candidate per Exercise the user has trained, newest history first.

    One query pulls every normal Set in the history window for the user joined to
    its Exercise; we keep the most-recent working Set per Exercise (the one
    Progression reads) and attach the Exercise's muscle mapping. Ordered by
    Exercise id so the candidate list — and thus the whole proposal — is stable.
    """
    window_start = now - _HISTORY_WINDOW
    stmt = (
        select(
            Exercise.id,
            Exercise.name,
            Exercise.equipment,
            TrainingSession.started_at,
            TrainingSet.order_index,
            TrainingSet.weight_kg,
            TrainingSet.reps,
            TrainingSet.rpe,
        )
        .select_from(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .join(Exercise, Exercise.id == TrainingSet.exercise_id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.set_type == SetType.normal,
            TrainingSession.started_at >= window_start,
            TrainingSet.weight_kg > 0,
            TrainingSet.reps > 0,
        )
        # Newest first; within a Session the later (higher order_index) working
        # set is the freshest signal of where the lift currently is.
        .order_by(
            TrainingSession.started_at.desc(),
            TrainingSet.order_index.desc(),
        )
    )
    rows = (await db.execute(stmt)).all()

    # Keep the single most-recent working Set per Exercise (rows are newest-first,
    # so the first row seen for an id wins).
    latest: dict[uuid.UUID, SetPerformance] = {}
    meta: dict[uuid.UUID, tuple[str, str | None]] = {}
    for r in rows:
        if r.id in latest:
            continue
        latest[r.id] = SetPerformance(
            weight_kg=r.weight_kg, reps=r.reps, rir=rpe_to_rir(r.rpe)
        )
        meta[r.id] = (r.name, r.equipment)

    if not latest:
        return []

    # Fetch muscle mappings for exactly the trained Exercises in one query.
    muscle_rows = (
        await db.execute(
            select(ExerciseMuscle.exercise_id, ExerciseMuscle.muscle, ExerciseMuscle.role)
            .where(ExerciseMuscle.exercise_id.in_(latest.keys()))
        )
    ).all()
    primaries: dict[uuid.UUID, list[str]] = {}
    secondaries: dict[uuid.UUID, list[str]] = {}
    for mr in muscle_rows:
        muscle = mr.muscle.value if hasattr(mr.muscle, "value") else str(mr.muscle)
        bucket = primaries if mr.role == MuscleRole.primary else secondaries
        bucket.setdefault(mr.exercise_id, []).append(muscle)

    candidates = [
        ExerciseCandidate(
            exercise_id=eid,
            name=meta[eid][0],
            equipment=meta[eid][1],
            primary_muscles=tuple(sorted(primaries.get(eid, []))),
            secondary_muscles=tuple(sorted(secondaries.get(eid, []))),
            history=(latest[eid],),
        )
        for eid in latest
    ]
    # Stable order independent of dict/DB ordering.
    candidates.sort(key=lambda c: c.exercise_id.int)
    return candidates


async def recommend_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    exercise_count: int = DEFAULT_EXERCISE_COUNT,
    sets_per_exercise: int = DEFAULT_SETS_PER_EXERCISE,
) -> Recommendation:
    """Generate today's freestyle Recommendation for a user.

    Assembles the user's trained-Exercise candidates, their per-muscle Recovery,
    and their Gym Profile equipment, then runs the pure deterministic generator.
    ``now`` is injected so a fixed DB state yields a fixed proposal.
    """
    candidates = await _candidates(db, user_id, now=now)
    recovery = await _recovery_map(db, user_id, now=now)
    equipment = await _gym_equipment(db, user_id)
    return generate_recommendation(
        candidates,
        recovery=recovery,
        available_equipment=equipment,
        exercise_count=exercise_count,
        sets_per_exercise=sets_per_exercise,
    )


# Sustained-low-readiness window for the fatigue-triggered early Deload (#14):
# the autoregulator looks back over the last week of daily Readiness.
_DELOAD_LOOKBACK_DAYS = 7


async def recommend_today(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> tuple[Recommendation, ProgramRecommendation | None]:
    """Today's Recommendation, drawn from the active Program if one exists.

    The unified "today" entry point (#13/#14): when the user has an **active
    Program**, today's proposal is the Program's prescription for the next due
    training day, **autoregulated** on today's biometric **Readiness** and the
    user's per-muscle **Recovery** (trim/keep within Principle bounds, with a
    reason) and flagged for an **early Deload** if Readiness has been persistently
    low (:func:`app.services.autoregulation.early_deload_triggered`); the
    :class:`ProgramRecommendation` context (day name, week, deload flag,
    autoregulation reason) is returned alongside it. Otherwise it falls back to
    the **freestyle** generator and the second element is ``None``. ``now`` is
    injected for determinism.
    """
    program = await active_program(db, user_id)
    if program is not None:
        readiness = await readiness_for_user(db, user_id, now=now)
        recent = await recent_daily_readiness(
            db, user_id, now=now, days=_DELOAD_LOOKBACK_DAYS
        )
        early_deload = early_deload_triggered(recent)
        program_rec = await recommend_from_program(
            db,
            user_id,
            program,
            now=now,
            readiness=readiness.score,
            early_deload=early_deload,
        )
        return program_rec.recommendation, program_rec
    freestyle = await recommend_for_user(db, user_id, now=now)
    return freestyle, None


async def instantiate_session(
    db: AsyncSession,
    user_id: int,
    recommendation: Recommendation,
    *,
    started_at: dt.datetime | None = None,
) -> TrainingSession:
    """Create a Session pre-filled with the proposal's target Sets.

    Each prescribed Exercise becomes ``target_sets`` consecutive normal Sets at
    the proposed weight × reps (no Effort — the user logs that as they go). Sets
    are appended in proposal order with a gap-free 0-based ``order_index``,
    exactly as the live logger would create them, so the existing logging UI
    drives them unchanged and the user's edits simply overwrite the targets
    (user edits always win — there is no separate "prescribed" state to honour).

    Returns the flushed Session with its Sets loaded.
    """
    session = TrainingSession(user_id=user_id)
    if started_at is not None:
        session.started_at = started_at
    db.add(session)
    await db.flush()

    order_index = 0
    for item in recommendation.exercises:
        for _ in range(item.target_sets):
            db.add(
                TrainingSet(
                    session_id=session.id,
                    exercise_id=item.exercise_id,
                    order_index=order_index,
                    weight_kg=item.target_weight_kg,
                    reps=item.target_reps,
                    rpe=None,
                    set_type=SetType.normal,
                )
            )
            order_index += 1
    await db.flush()
    await db.refresh(session, attribute_names=["sets"])
    return session


# The conversational adjust trims volume to at most a per-slot floor of one
# working set — the autoregulation/Program floors already shaped the base
# prescription; this user-initiated nudge stays inside the bounded volume scale.
_ADJUST_SETS_FLOOR = 1


@dataclass(frozen=True)
class AdjustResult:
    """A conversational-adjust outcome: the re-shaped proposal + what was applied.

    ``recommendation`` is the new (editable) proposal; ``adjustment`` is the
    *validated* :class:`~app.services.adjust.Adjustment` actually applied (clamped
    to bounds); ``note`` is the human explanation to show. ``program`` carries the
    active-Program context when the base proposal came from a Program (so the UI
    keeps its header), else ``None``.
    """

    recommendation: Recommendation
    adjustment: Adjustment
    note: str
    program: ProgramRecommendation | None


async def _equipment_by_exercise(
    db: AsyncSession, recommendation: Recommendation
) -> dict[uuid.UUID, str | None]:
    """Map each proposed Exercise to its required equipment (for exclusion)."""
    ids = [e.exercise_id for e in recommendation.exercises]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Exercise.id, Exercise.equipment).where(Exercise.id.in_(ids))
        )
    ).all()
    return {r.id: r.equipment for r in rows}


async def adjust_today(
    db: AsyncSession,
    user_id: int,
    request: str,
    *,
    now: dt.datetime,
    provider: AdjustProvider,
) -> AdjustResult:
    """Re-shape today's Recommendation from a conversational request (#14).

    The full ADR-0002 loop: generate today's proposal (Program-drawn or
    freestyle), ask the ``provider`` to **propose** a structured adjustment from
    the user's free text, **validate** it against the bounds (clamped — the engine
    decides), then **apply** it to produce a new editable proposal. The provider
    may be the deterministic default or the gated LLM; either way only the
    validated adjustment is applied, and starting the result instantiates Sets the
    user freely overwrites (their edits win). ``now`` is injected for determinism.
    """
    base, program_rec = await recommend_today(db, user_id, now=now)
    equipment = await _gym_equipment(db, user_id)

    proposed = await propose_adjustment(provider, request, equipment=equipment)
    bounds = AdjustmentBounds(available_equipment=equipment)
    validated = validate_adjustment(proposed, bounds)

    equip_map = await _equipment_by_exercise(db, base)
    adjusted = apply_adjustment(
        base,
        validated,
        sets_floor=_ADJUST_SETS_FLOOR,
        equipment_by_exercise=equip_map,
    )
    return AdjustResult(
        recommendation=adjusted,
        adjustment=validated,
        note=validated.note,
        program=program_rec,
    )
