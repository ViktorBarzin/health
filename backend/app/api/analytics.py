"""Training-analytics API — Recovery, per-muscle weekly volume, e1RM trends (#10).

Three read-only, per-user views computed from logged Sets (no new storage):

* ``GET /api/analytics/recovery`` — every catalog muscle's current Recovery score
  (0–100; untrained muscles filled at 100) for the SVG body-map heatmap;
* ``GET /api/analytics/volume`` — per-muscle set count + volume-load over a
  trailing window of ``weeks`` weeks (the volume side of the heatmap);
* ``GET /api/analytics/e1rm-trend`` — the estimated-1RM series for one Exercise.

All are scoped to ``get_current_user`` and read existing aggregates over the
``training_sets`` ⋈ ``exercise_muscles`` join; the heavy maths lives in the pure
cores these call. ``now`` is taken at request time for the trailing windows.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.exercise import Exercise, Muscle
from app.models.user import User
from app.schemas.analytics import (
    E1rmPoint,
    E1rmTrendResponse,
    MuscleRecovery,
    MuscleVolume,
    RecoveryResponse,
    TrainedExercise,
    VolumeResponse,
)
from app.services.analytics import (
    e1rm_trend_for_user,
    recovery_for_user,
    trained_exercises_for_user,
)
from app.services.muscle_volume import weekly_muscle_volume
from app.services.recovery import DEFAULT_HALF_LIFE_HOURS

router = APIRouter()

# Fully-recovered score for a muscle with no recent training load.
_FULL_RECOVERY = 100.0


@router.get("/recovery", response_model=RecoveryResponse)
async def get_recovery(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecoveryResponse:
    """Per-muscle Recovery (freshness) for the caller, as of now.

    Returns one entry for **every** catalog muscle so the body-map can colour the
    whole figure: muscles with recent load carry their computed score, untrained
    muscles are filled at 100 (fully fresh). Sorted by recovery ascending so the
    most-fatigued muscles head the list.
    """
    now = datetime.now(timezone.utc)
    scored = await recovery_for_user(db, user.id, now=now)
    muscles = [
        MuscleRecovery(
            muscle=m.value,
            recovery=round(scored.get(m.value, _FULL_RECOVERY), 1),
        )
        for m in Muscle
    ]
    muscles.sort(key=lambda mr: (mr.recovery, mr.muscle))
    return RecoveryResponse(
        as_of=now,
        half_life_hours=DEFAULT_HALF_LIFE_HOURS,
        muscles=muscles,
    )


@router.get("/volume", response_model=VolumeResponse)
async def get_volume(
    weeks: int = Query(default=4, ge=1, le=52),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VolumeResponse:
    """Per-muscle set count + volume-load over the trailing ``weeks`` weeks.

    Grouped by (muscle, role) off ``exercise_muscles``, normal Sets only (the
    CONTEXT.md exclusion, owned by :mod:`app.services.volume`). Heaviest-hit
    muscles first.
    """
    now = datetime.now(timezone.utc)
    rows = await weekly_muscle_volume(db, user.id, now=now, weeks=weeks)
    return VolumeResponse(
        weeks=weeks,
        muscles=[
            MuscleVolume(
                muscle=r.muscle,
                role=r.role,
                set_count=r.set_count,
                volume_load=round(r.volume_load, 1),
            )
            for r in rows
        ],
    )


@router.get("/e1rm-trend", response_model=E1rmTrendResponse)
async def get_e1rm_trend(
    exercise_id: uuid.UUID = Query(description="The Exercise to trend e1RM for."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> E1rmTrendResponse:
    """Estimated-1RM trend for one Exercise: one point per normal Set, oldest first.

    404s if the Exercise isn't visible to the caller (mirrors the Set-logging
    visibility rule: global ∪ own), so the endpoint never confirms another user's
    private Exercise exists.
    """
    visible = (
        await db.execute(
            select(Exercise.id).where(
                Exercise.id == exercise_id,
                (Exercise.user_id.is_(None)) | (Exercise.user_id == user.id),
            )
        )
    ).scalar_one_or_none()
    if visible is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found"
        )

    points = await e1rm_trend_for_user(db, user.id, exercise_id)
    best = max((e for _, e in points), default=None)
    return E1rmTrendResponse(
        exercise_id=exercise_id,
        points=[
            E1rmPoint(time=t, e1rm=round(e, 1)) for t, e in points
        ],
        best_e1rm=round(best, 1) if best is not None else None,
    )


@router.get("/exercises", response_model=list[TrainedExercise])
async def list_trained_exercises(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrainedExercise]:
    """Exercises the caller has logged normal Sets for — the e1RM-trend picker.

    Only Exercises with PR-eligible history, so the trend selector lists what the
    user has actually trained instead of the full catalog. Alphabetical.
    """
    rows = await trained_exercises_for_user(db, user.id)
    return [TrainedExercise(id=eid, name=name) for eid, name in rows]
