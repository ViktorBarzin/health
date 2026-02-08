"""Dashboard API routes."""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.activity_summary import ActivitySummary
from app.models.health_record import HealthRecord
from app.models.user import User
from app.schemas.dashboard import DashboardSummary

router = APIRouter()


async def _latest_metric(
    db: AsyncSession,
    user_id: int,
    metric_type: str,
    since: datetime | None = None,
) -> float | None:
    """Fetch the most recent value for a metric type, optionally since a datetime."""
    filters = [
        HealthRecord.user_id == user_id,
        HealthRecord.metric_type == metric_type,
    ]
    if since is not None:
        filters.append(HealthRecord.time >= since)

    stmt = (
        select(HealthRecord.value)
        .where(*filters)
        .order_by(HealthRecord.time.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row


async def _sum_metric_today(
    db: AsyncSession,
    user_id: int,
    metric_type: str,
    today_start: datetime,
) -> float | None:
    """Sum all values for a metric type since today_start."""
    stmt = (
        select(func.sum(HealthRecord.value))
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric_type,
            HealthRecord.time >= today_start,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    """Return a summary of today's key health metrics."""
    today = date.today()
    today_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    yesterday_start = datetime.combine(today, time.min, tzinfo=timezone.utc)

    # Get today's activity summary if available
    activity_stmt = select(ActivitySummary).where(
        ActivitySummary.user_id == user.id,
        ActivitySummary.date == today,
    )
    activity_result = await db.execute(activity_stmt)
    activity = activity_result.scalar_one_or_none()

    # Aggregate today's metrics from health records
    steps = await _sum_metric_today(db, user.id, "StepCount", today_start)
    active_energy = await _sum_metric_today(
        db, user.id, "ActiveEnergyBurned", today_start
    )

    # Latest single-value metrics (no time constraint for resting HR, HRV, SpO2)
    resting_hr = await _latest_metric(db, user.id, "RestingHeartRate")
    hrv = await _latest_metric(db, user.id, "HeartRateVariabilitySDNN")
    spo2 = await _latest_metric(db, user.id, "OxygenSaturation")

    # Sleep: look for last night's sleep analysis
    sleep = await _latest_metric(db, user.id, "SleepAnalysis", since=yesterday_start)

    return DashboardSummary(
        steps_today=steps,
        active_energy_today=active_energy,
        exercise_minutes_today=(
            activity.exercise_minutes if activity else None
        ),
        stand_hours_today=(
            activity.stand_hours if activity else None
        ),
        resting_hr=resting_hr,
        hrv=hrv,
        spo2=spo2,
        sleep_hours_last_night=sleep,
    )
