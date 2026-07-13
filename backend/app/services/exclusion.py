"""Exclusion filter — the per-user "never recommend this Exercise" mark.

CONTEXT.md ("Exclusion"): constrains generation exactly like the Gym Profile
does — a hard filter, applied identically by every path that selects Exercises
(freestyle candidates, Program slot filling, Swap alternatives). One clause,
defined once, so the paths can't drift.

The mark lives on :class:`~app.models.exercise_pref.ExercisePref` (the existing
per-(user, exercise) preferences row) as ``excluded`` — set from the SwapSheet,
reversible in settings, and deliberately explicit-only: the engine never infers
dislike from Swap behaviour (ADR-0002 keeps every filter explainable).
"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.models.exercise_pref import ExercisePref


def not_excluded_clause(user_id: int):
    """A WHERE clause selecting Exercises the user has NOT Excluded.

    Correlates against the enclosing query's ``Exercise`` — append it to any
    select that yields Exercise rows, exactly where the Gym Profile equipment
    filter applies its own rule.
    """
    return ~exists(
        select(ExercisePref.id).where(
            ExercisePref.user_id == user_id,
            ExercisePref.exercise_id == Exercise.id,
            ExercisePref.excluded.is_(True),
        )
    )


async def excluded_exercise_ids(db: AsyncSession, user_id: int) -> frozenset:
    """The user's Excluded Exercise ids — for paths that filter in Python."""
    rows = (
        await db.execute(
            select(ExercisePref.exercise_id).where(
                ExercisePref.user_id == user_id,
                ExercisePref.excluded.is_(True),
            )
        )
    ).scalars()
    return frozenset(rows)
