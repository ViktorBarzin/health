"""Activity ring API routes."""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.activity_summary import ActivitySummary
from app.models.user import User

router = APIRouter()


class ActivityRingDay(BaseModel):
    date: dt.date
    active_energy_burned_kj: float | None = None
    active_energy_goal_kj: float | None = None
    exercise_minutes: float | None = None
    exercise_goal_minutes: float | None = None
    stand_hours: int | None = None
    stand_goal_hours: int | None = None

    model_config = {"from_attributes": True}


@router.get("/rings", response_model=list[ActivityRingDay])
async def get_activity_rings(
    start: dt.date = Query(default_factory=lambda: dt.date.today() - dt.timedelta(days=30)),
    end: dt.date = Query(default_factory=dt.date.today),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityRingDay]:
    """Return activity ring data (energy, exercise, stand) for a date range."""
    stmt = (
        select(ActivitySummary)
        .where(
            ActivitySummary.user_id == user.id,
            ActivitySummary.date >= start,
            ActivitySummary.date <= end,
        )
        .order_by(ActivitySummary.date)
    )
    result = await db.execute(stmt)
    summaries = result.scalars().all()
    return [ActivityRingDay.model_validate(s) for s in summaries]
