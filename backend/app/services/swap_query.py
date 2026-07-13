"""Swap query layer — binds the pure ranking core to a user's data.

The DB glue for ``GET /api/exercises/{id}/alternatives`` (CONTEXT.md "Swap"),
mirroring :mod:`app.services.recommendation_query`: assemble the pool and the
user context, then run :func:`app.services.swap.rank_alternatives`.

Pool = library Exercises (global ∪ the user's own) sharing at least one PRIMARY
muscle with the target — the same primary-mover rule the Program slot filler
uses — minus the user's Exclusions (SQL-level, the shared
:func:`app.services.exclusion.not_excluded_clause`). Each pool member carries
the user's most-recent working Set for it (so the prescription is a real
Progression when history exists), and ranking sees the same per-muscle Recovery
map the freestyle generator reads.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise, ExerciseMuscle, MuscleRole
from app.services.exclusion import not_excluded_clause
from app.services.recommendation import ExerciseCandidate
from app.services.recommendation_query import (
    _gym_equipment,
    _recovery_map,
)
from app.services.program_recommendation import _latest_history
from app.services.swap import DEFAULT_ALTERNATIVES, RankedAlternative, rank_alternatives


async def _candidate_for(
    db: AsyncSession, user_id: int, exercise_id: uuid.UUID
) -> ExerciseCandidate | None:
    """Load one visible Exercise as a (history-less) candidate, or None."""
    stmt = select(Exercise).where(
        Exercise.id == exercise_id,
        or_(Exercise.user_id.is_(None), Exercise.user_id == user_id),
    )
    ex = (await db.execute(stmt)).scalar_one_or_none()
    if ex is None:
        return None
    return _to_candidate(ex)


def _to_candidate(ex: Exercise) -> ExerciseCandidate:
    prim = tuple(
        sorted(m.muscle.value for m in ex.muscles if m.role == MuscleRole.primary)
    )
    sec = tuple(
        sorted(m.muscle.value for m in ex.muscles if m.role == MuscleRole.secondary)
    )
    return ExerciseCandidate(
        exercise_id=ex.id,
        name=ex.name,
        equipment=ex.equipment,
        primary_muscles=prim,
        secondary_muscles=sec,
    )


async def _pool_sharing_primary(
    db: AsyncSession, user_id: int, primaries: tuple[str, ...]
) -> list[ExerciseCandidate]:
    """Visible, non-Excluded Exercises with any of ``primaries`` as a primary mover."""
    if not primaries:
        return []
    stmt = (
        select(Exercise)
        .join(ExerciseMuscle, ExerciseMuscle.exercise_id == Exercise.id)
        .where(
            ExerciseMuscle.muscle.in_(primaries),
            ExerciseMuscle.role == MuscleRole.primary,
            or_(Exercise.user_id.is_(None), Exercise.user_id == user_id),
            not_excluded_clause(user_id),
        )
        .order_by(Exercise.id)
    )
    exercises = (await db.execute(stmt)).scalars().unique().all()
    return [_to_candidate(ex) for ex in exercises]


async def alternatives_for_exercise(
    db: AsyncSession,
    user_id: int,
    exercise_id: uuid.UUID,
    *,
    now: dt.datetime,
    blocked_ids: frozenset[uuid.UUID] = frozenset(),
    limit: int = DEFAULT_ALTERNATIVES,
) -> list[RankedAlternative] | None:
    """Ranked Swap equivalents for one Exercise, or None if it isn't visible.

    ``blocked_ids`` carries the Exercises already in today's plan (the client's
    ``?exclude=``) so a Swap never offers something the Session already holds.
    """
    target = await _candidate_for(db, user_id, exercise_id)
    if target is None:
        return None

    pool = await _pool_sharing_primary(db, user_id, target.primary_muscles)
    history = await _latest_history(db, user_id, now=now)
    pool = [
        c if c.exercise_id not in history
        else ExerciseCandidate(
            exercise_id=c.exercise_id,
            name=c.name,
            equipment=c.equipment,
            primary_muscles=c.primary_muscles,
            secondary_muscles=c.secondary_muscles,
            history=(history[c.exercise_id],),
        )
        for c in pool
    ]
    recovery = await _recovery_map(db, user_id, now=now)
    equipment = await _gym_equipment(db, user_id)
    return rank_alternatives(
        target,
        pool,
        recovery=recovery,
        available_equipment=equipment,
        blocked_ids=blocked_ids,
        limit=limit,
    )
