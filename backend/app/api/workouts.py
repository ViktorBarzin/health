"""Workout API routes."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.workout import Workout
from app.models.workout_route_point import WorkoutRoutePoint
from app.schemas.workouts import RoutePoint, WorkoutDetail, WorkoutSummary

router = APIRouter()


@router.get("/", response_model=list[WorkoutSummary])
async def list_workouts(
    activity_type: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WorkoutSummary]:
    """List workouts for the current user, optionally filtered by activity type and date range."""
    filters = [Workout.user_id == user.id]
    if activity_type is not None:
        filters.append(Workout.activity_type == activity_type)
    if start is not None:
        filters.append(Workout.time >= start)
    if end is not None:
        filters.append(Workout.time <= end)

    stmt = (
        select(Workout)
        .options(defer(Workout.metadata_))
        .where(*filters)
        .order_by(Workout.time.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    workouts = result.scalars().all()
    return [WorkoutSummary.model_validate(w) for w in workouts]


@router.get("/{workout_id}", response_model=WorkoutDetail)
async def get_workout(
    workout_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkoutDetail:
    """Get workout detail including route points."""
    stmt = select(Workout).where(
        Workout.id == workout_id,
        Workout.user_id == user.id,
    )
    result = await db.execute(stmt)
    workout = result.scalar_one_or_none()
    if workout is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workout not found",
        )

    # Fetch route points
    route_stmt = (
        select(WorkoutRoutePoint)
        .where(WorkoutRoutePoint.workout_id == workout_id)
        .order_by(WorkoutRoutePoint.time)
    )
    route_result = await db.execute(route_stmt)
    route_points = route_result.scalars().all()

    return WorkoutDetail(
        id=workout.id,
        activity_type=workout.activity_type,
        time=workout.time,
        end_time=workout.end_time,
        duration_sec=workout.duration_sec,
        total_distance_m=workout.total_distance_m,
        total_energy_kj=workout.total_energy_kj,
        metadata=workout.metadata_,
        route_points=[RoutePoint.model_validate(rp) for rp in route_points],
    )
