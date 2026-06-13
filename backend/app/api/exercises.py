"""Exercise library API routes.

The shared catalog the logger, importer, and engine all reference. A user
browses the global library (``user_id IS NULL``) unioned with their own custom
Exercises; they can create custom (private) Exercises and read any single one
they're allowed to see. Global rows are read-only here — they're managed by the
seed (:mod:`app.services.seed_exercises`).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.user import User
from app.schemas.exercises import (
    ExerciseCreate,
    ExerciseDetail,
    ExerciseSummary,
    MuscleOption,
)

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


def _custom_slug(name: str) -> str:
    """A readable, mostly-unique natural key for a custom Exercise.

    Per-user uniqueness is enforced by ``uq_exercise_user_slug``; appending a
    short random suffix keeps a user's two same-named Exercises from colliding.
    """
    base = "-".join(name.lower().split())
    cleaned = "".join(c for c in base if c.isalnum() or c == "-").strip("-")
    return f"custom-{cleaned or 'exercise'}-{uuid.uuid4().hex[:8]}"
