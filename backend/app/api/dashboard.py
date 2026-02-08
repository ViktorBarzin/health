"""Dashboard API routes."""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.activity_summary import ActivitySummary
from app.models.health_record import HealthRecord
from app.models.user import User
from app.schemas.dashboard import DashboardSummary

router = APIRouter()

# Metric types that need SUM aggregation
_SUM_METRICS = ["StepCount", "ActiveEnergyBurned"]
# Metric types that need the latest (most recent) value
_LATEST_METRICS = [
    "RestingHeartRate",
    "HeartRateVariabilitySDNN",
    "OxygenSaturation",
    "SleepAnalysis",
]


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    """Return a summary of key health metrics.

    Without date parameters returns today's data.
    With start/end returns aggregated data for the given range.
    """
    if start is None:
        today = date.today()
        range_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    else:
        range_start = start

    range_end = end  # None means unbounded upper

    # Get activity summary for the range
    activity_filters = [ActivitySummary.user_id == user.id]
    if start is not None:
        activity_filters.append(ActivitySummary.date >= start.date())
    else:
        activity_filters.append(ActivitySummary.date == date.today())
    if range_end is not None:
        activity_filters.append(ActivitySummary.date <= range_end.date())

    activity_stmt = select(
        func.sum(ActivitySummary.exercise_minutes),
        func.sum(ActivitySummary.stand_hours),
    ).where(*activity_filters)
    activity_result = await db.execute(activity_stmt)
    activity_row = activity_result.one()
    exercise_minutes = activity_row[0]
    stand_hours = activity_row[1]

    # -- Combined SUM query for StepCount + ActiveEnergyBurned (1 query) ----
    time_filters: list = [
        HealthRecord.user_id == user.id,
        HealthRecord.metric_type.in_(_SUM_METRICS),
        HealthRecord.time >= range_start,
    ]
    if range_end is not None:
        time_filters.append(HealthRecord.time <= range_end)

    sums_stmt = select(
        func.sum(
            case(
                (HealthRecord.metric_type == "StepCount", HealthRecord.value),
                else_=None,
            )
        ).label("steps"),
        func.sum(
            case(
                (HealthRecord.metric_type == "ActiveEnergyBurned", HealthRecord.value),
                else_=None,
            )
        ).label("energy"),
    ).where(*time_filters)

    sums_result = await db.execute(sums_stmt)
    sums_row = sums_result.one()
    steps = sums_row.steps
    active_energy = sums_row.energy

    # -- Combined DISTINCT ON query for latest values (1 query) -------------
    latest_filters: list = [
        HealthRecord.user_id == user.id,
        HealthRecord.metric_type.in_(_LATEST_METRICS),
        HealthRecord.time >= range_start,
    ]
    if range_end is not None:
        latest_filters.append(HealthRecord.time <= range_end)

    latest_stmt = (
        select(HealthRecord.metric_type, HealthRecord.value)
        .distinct(HealthRecord.metric_type)
        .where(*latest_filters)
        .order_by(HealthRecord.metric_type, HealthRecord.time.desc())
    )
    latest_result = await db.execute(latest_stmt)
    latest_map = {row.metric_type: row.value for row in latest_result.all()}

    return DashboardSummary(
        steps_today=steps,
        active_energy_today=active_energy,
        exercise_minutes_today=exercise_minutes,
        stand_hours_today=stand_hours,
        resting_hr=latest_map.get("RestingHeartRate"),
        hrv=latest_map.get("HeartRateVariabilitySDNN"),
        spo2=latest_map.get("OxygenSaturation"),
        sleep_hours_last_night=latest_map.get("SleepAnalysis"),
    )
