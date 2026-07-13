"""Exercise library API routes.

The shared catalog the logger, importer, and engine all reference. A user
browses the global library (``user_id IS NULL``) unioned with their own custom
Exercises; they can create custom (private) Exercises and read any single one
they're allowed to see. Global rows are read-only here — they're managed by the
seed (:mod:`app.services.seed_exercises`).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.exercise_pref import DEFAULT_REST_SECONDS, ExercisePref
from app.models.user import User
from app.schemas.exercises import (
    AlternativeRead,
    ExclusionRead,
    ExerciseCreate,
    ExerciseDetail,
    ExerciseSummary,
    MuscleOption,
    RestPrefRead,
    RestPrefUpdate,
)
from app.services.swap import DEFAULT_ALTERNATIVES
from app.services.swap_query import alternatives_for_exercise

router = APIRouter()


def build_browse_query(
    user_id: int,
    *,
    search: str | None = None,
    muscle: Muscle | None = None,
    equipment: str | None = None,
) -> Select:
    """Build the browse query: global ∪ this user's own, with optional filters.

    Visibility rule (CONTEXT.md: the library is shared, custom Exercises are
    private): a user sees every global row plus only their own custom rows, never
    another user's. Filtering by ``muscle`` matches either a primary or secondary
    mapping via an EXISTS subquery so it stays a single GROUP-BY-able dimension.
    """
    stmt = select(Exercise).where(
        or_(Exercise.user_id.is_(None), Exercise.user_id == user_id)
    )
    if search:
        stmt = stmt.where(Exercise.name.ilike(f"%{search.strip()}%"))
    if equipment:
        stmt = stmt.where(Exercise.equipment == equipment)
    if muscle is not None:
        stmt = stmt.where(
            select(ExerciseMuscle.id)
            .where(
                ExerciseMuscle.exercise_id == Exercise.id,
                ExerciseMuscle.muscle == muscle,
            )
            .exists()
        )
    return stmt.order_by(Exercise.name)


@router.get("/", response_model=list[ExerciseSummary])
async def list_exercises(
    search: str | None = Query(default=None),
    muscle: Muscle | None = Query(default=None),
    equipment: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExerciseSummary]:
    """Browse the library (global + the caller's custom), searchable/filterable."""
    stmt = build_browse_query(
        user.id, search=search, muscle=muscle, equipment=equipment
    ).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return [ExerciseSummary.model_validate(ex) for ex in result.scalars().all()]


@router.get("/muscles", response_model=list[MuscleOption])
async def list_muscles() -> list[MuscleOption]:
    """The typed muscle dimension, for filter dropdowns and the create form."""
    return [MuscleOption(value=m.value, label=m.value.title()) for m in Muscle]


@router.get("/equipment", response_model=list[str])
async def list_equipment(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Distinct, non-null equipment values across the caller's visible library."""
    stmt = (
        select(Exercise.equipment)
        .where(
            or_(Exercise.user_id.is_(None), Exercise.user_id == user.id),
            Exercise.equipment.isnot(None),
        )
        .distinct()
        .order_by(Exercise.equipment)
    )
    result = await db.execute(stmt)
    return [row for row in result.scalars().all()]


# NOTE: registered before the parametrized ``/{exercise_id}`` routes below so
# the literal path wins the match.
@router.get("/exclusions", response_model=list[ExclusionRead])
async def list_exclusions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExclusionRead]:
    """The caller's Exclusions — Exercises the engine must never recommend.

    The settings manager renders this list so every mark set from a SwapSheet
    stays reviewable and reversible (CONTEXT.md "Exclusion").
    """
    stmt = (
        select(Exercise.id, Exercise.name, Exercise.equipment)
        .join(ExercisePref, ExercisePref.exercise_id == Exercise.id)
        .where(
            ExercisePref.user_id == user.id,
            ExercisePref.excluded.is_(True),
        )
        .order_by(Exercise.name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        ExclusionRead(exercise_id=r.id, name=r.name, equipment=r.equipment)
        for r in rows
    ]


@router.post("/", response_model=ExerciseDetail, status_code=status.HTTP_201_CREATED)
async def create_exercise(
    payload: ExerciseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExerciseDetail:
    """Create a custom (private) Exercise owned by the caller."""
    exercise = Exercise(
        user_id=user.id,
        slug=_custom_slug(payload.name),
        name=payload.name,
        category=payload.category,
        equipment=payload.equipment,
        level=payload.level,
        mechanic=payload.mechanic,
        force=payload.force,
        instructions=payload.instructions,
        images=[],
        source="custom",
    )
    # Primary wins if a muscle is listed in both lists.
    seen: set[Muscle] = set()
    for m in payload.primary_muscles:
        if m not in seen:
            exercise.muscles.append(ExerciseMuscle(muscle=m, role=MuscleRole.primary))
            seen.add(m)
    for m in payload.secondary_muscles:
        if m not in seen:
            exercise.muscles.append(ExerciseMuscle(muscle=m, role=MuscleRole.secondary))
            seen.add(m)

    db.add(exercise)
    await db.flush()
    await db.refresh(exercise)
    return ExerciseDetail.model_validate(exercise)


@router.get("/{exercise_id}", response_model=ExerciseDetail)
async def get_exercise(
    exercise_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExerciseDetail:
    """Fetch one Exercise the caller may see (global or their own custom)."""
    stmt = select(Exercise).where(
        Exercise.id == exercise_id,
        or_(Exercise.user_id.is_(None), Exercise.user_id == user.id),
    )
    exercise = (await db.execute(stmt)).scalar_one_or_none()
    if exercise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found"
        )
    return ExerciseDetail.model_validate(exercise)


async def _assert_exercise_visible(
    db: AsyncSession, exercise_id: uuid.UUID, user: User
) -> None:
    """Raise 404 unless the Exercise exists and is visible (global or own)."""
    stmt = select(Exercise.id).where(
        Exercise.id == exercise_id,
        or_(Exercise.user_id.is_(None), Exercise.user_id == user.id),
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found"
        )


@router.get("/{exercise_id}/rest", response_model=RestPrefRead)
async def get_rest_pref(
    exercise_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RestPrefRead:
    """The caller's rest-timer default for an Exercise (with the global fallback).

    Per-user (CONTEXT.md: the library is shared, so a rest default can't live on
    the global Exercise row) — returns the user's override plus the effective
    value the timer should use.
    """
    await _assert_exercise_visible(db, exercise_id, user)
    pref = (
        await db.execute(
            select(ExercisePref).where(
                ExercisePref.user_id == user.id,
                ExercisePref.exercise_id == exercise_id,
            )
        )
    ).scalar_one_or_none()
    override = pref.default_rest_seconds if pref else None
    return RestPrefRead(
        exercise_id=exercise_id,
        default_rest_seconds=override,
        effective_rest_seconds=override
        if override is not None
        else DEFAULT_REST_SECONDS,
    )


@router.put("/{exercise_id}/rest", response_model=RestPrefRead)
async def set_rest_pref(
    exercise_id: uuid.UUID,
    payload: RestPrefUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RestPrefRead:
    """Set or clear the caller's rest-timer default for an Exercise.

    Upserts the per-user pref row (creating it on first set). A ``null`` value
    clears the override so the global default applies again.
    """
    await _assert_exercise_visible(db, exercise_id, user)
    pref = (
        await db.execute(
            select(ExercisePref).where(
                ExercisePref.user_id == user.id,
                ExercisePref.exercise_id == exercise_id,
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = ExercisePref(user_id=user.id, exercise_id=exercise_id)
        db.add(pref)
    pref.default_rest_seconds = payload.default_rest_seconds
    await db.flush()
    override = pref.default_rest_seconds
    return RestPrefRead(
        exercise_id=exercise_id,
        default_rest_seconds=override,
        effective_rest_seconds=override
        if override is not None
        else DEFAULT_REST_SECONDS,
    )


async def _pref_row(
    db: AsyncSession, user_id: int, exercise_id: uuid.UUID
) -> ExercisePref | None:
    return (
        await db.execute(
            select(ExercisePref).where(
                ExercisePref.user_id == user_id,
                ExercisePref.exercise_id == exercise_id,
            )
        )
    ).scalar_one_or_none()


@router.put("/{exercise_id}/exclusion", status_code=status.HTTP_204_NO_CONTENT)
async def set_exclusion(
    exercise_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Mark an Exercise "never recommend again" (idempotent).

    Upserts the per-(user, exercise) preferences row — the same row the rest
    pref lives on — so un-excluding later never loses an existing rest override.
    """
    await _assert_exercise_visible(db, exercise_id, user)
    pref = await _pref_row(db, user.id, exercise_id)
    if pref is None:
        pref = ExercisePref(user_id=user.id, exercise_id=exercise_id)
        db.add(pref)
    pref.excluded = True
    await db.flush()


@router.delete("/{exercise_id}/exclusion", status_code=status.HTTP_204_NO_CONTENT)
async def remove_exclusion(
    exercise_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Undo an Exclusion (idempotent — absent mark is already the goal state)."""
    await _assert_exercise_visible(db, exercise_id, user)
    pref = await _pref_row(db, user.id, exercise_id)
    if pref is not None and pref.excluded:
        pref.excluded = False
        await db.flush()


@router.get("/{exercise_id}/alternatives", response_model=list[AlternativeRead])
async def list_alternatives(
    exercise_id: uuid.UUID,
    exclude: str | None = Query(
        default=None,
        description="Comma-separated Exercise ids already in today's plan.",
    ),
    limit: int = Query(default=DEFAULT_ALTERNATIVES, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlternativeRead]:
    """Ranked Swap equivalents for an Exercise (CONTEXT.md "Swap").

    Same-primary-muscle movements the caller's Gym Profile can equip, minus
    Exclusions and anything in ``exclude``, ranked (muscle overlap → trained →
    freshness) and prescribed off each alternative's OWN history. The client
    prefetches these per visible Exercise so the SwapSheet opens instantly and
    survives a mid-Session signal drop.
    """
    blocked: set[uuid.UUID] = set()
    for raw in (exclude or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocked.add(uuid.UUID(raw))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid exercise id in exclude: {raw!r}",
            ) from exc

    now = datetime.now(timezone.utc)
    alternatives = await alternatives_for_exercise(
        db, user.id, exercise_id, now=now, blocked_ids=frozenset(blocked), limit=limit
    )
    if alternatives is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found"
        )
    return [
        AlternativeRead(
            exercise_id=a.exercise_id,
            name=a.name,
            equipment=a.equipment,
            target_reps=a.target_reps,
            target_weight_kg=a.target_weight_kg,
            is_starting_point=a.is_starting_point,
            has_history=a.has_history,
            primary_muscles=list(a.primary_muscles),
            secondary_muscles=list(a.secondary_muscles),
            shared_muscles=list(a.shared_muscles),
        )
        for a in alternatives
    ]


def _custom_slug(name: str) -> str:
    """A readable, mostly-unique natural key for a custom Exercise.

    Per-user uniqueness is enforced by ``uq_exercise_user_slug``; appending a
    short random suffix keeps a user's two same-named Exercises from colliding.
    """
    base = "-".join(name.lower().split())
    cleaned = "".join(c for c in base if c.isalnum() or c == "-").strip("-")
    return f"custom-{cleaned or 'exercise'}-{uuid.uuid4().hex[:8]}"
