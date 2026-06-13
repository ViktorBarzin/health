"""Principles query layer — the interface #13's generator and #14's UI call.

ADR-0004: the deterministic Program generator (#13) composes *only* from
Principles, so it asks this layer for the rules applicable to a user's
``(goal, experience)`` context and reads each rule's parameter ranges; the
receipts UI (#14) looks a single Principle up by key to show "why this number".

This module is the read side over the :class:`~app.models.principle.Principle`
table. Two operations:

* :func:`applicable_principles` — the Principles that apply to a
  ``(goal, experience)`` context, optionally narrowed to one category. The
  applicability rule (empty applicability list ⇒ "applies to all") is encoded in
  SQL here and mirrored by :meth:`Principle.applies_to`.
* :func:`principle_by_key` — one Principle by its stable ``key`` (or ``None``).

Citations are eager-loaded (the model's ``selectin`` relationship), so a caller
gets a Principle with its sources in one round trip.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.principle import (
    ExperienceLevel,
    Principle,
    PrincipleCategory,
    TrainingGoal,
)


def _matches_goal(goal: TrainingGoal):
    """SQL predicate: the rule's ``goals`` is empty (all) or contains ``goal``.

    ``[]`` means "applies to every Goal"; otherwise the JSONB array must contain
    the goal's value. ``jsonb @> '["bulk"]'`` is the containment check.
    """
    empty = Principle.goals == []
    contains = Principle.goals.cast(JSONB).contains([goal.value])
    return or_(empty, contains)


def _matches_experience(experience: ExperienceLevel):
    """SQL predicate: ``experience_levels`` is empty (all) or contains the level."""
    empty = Principle.experience_levels == []
    contains = Principle.experience_levels.cast(JSONB).contains([experience.value])
    return or_(empty, contains)


async def applicable_principles(
    db: AsyncSession,
    *,
    goal: TrainingGoal | None = None,
    experience: ExperienceLevel | None = None,
    category: PrincipleCategory | None = None,
) -> list[Principle]:
    """Return the Principles applicable to a ``(goal, experience)`` context.

    A Principle applies when its ``goals`` applicability is empty (universal) or
    contains ``goal``, *and* likewise for ``experience_levels`` — so a
    goal-specific rule (e.g. a protein target for bulking) is excluded for a
    cutting context, while a universal rule (e.g. progressive overload) always
    applies. ``None`` for a dimension does not filter on it. ``category`` narrows
    to a single training dimension when given. Ordered by category then key so the
    result is stable for the generator and the browse UI.
    """
    stmt = select(Principle)
    if goal is not None:
        stmt = stmt.where(_matches_goal(goal))
    if experience is not None:
        stmt = stmt.where(_matches_experience(experience))
    if category is not None:
        stmt = stmt.where(Principle.category == category)
    stmt = stmt.order_by(Principle.category, Principle.key)
    return list((await db.execute(stmt)).scalars().all())


async def principle_by_key(db: AsyncSession, key: str) -> Principle | None:
    """Look one Principle up by its stable ``key`` (``None`` if absent).

    The receipts UI's "why this number" tap resolves through here.
    """
    stmt = select(Principle).where(Principle.key == key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_principles(
    db: AsyncSession, *, category: PrincipleCategory | None = None
) -> list[Principle]:
    """All Principles (optionally one category), for the browse/list API.

    The unfiltered catalog view — distinct from :func:`applicable_principles`,
    which scopes to a user context.
    """
    stmt = select(Principle)
    if category is not None:
        stmt = stmt.where(Principle.category == category)
    stmt = stmt.order_by(Principle.category, Principle.key)
    return list((await db.execute(stmt)).scalars().all())
