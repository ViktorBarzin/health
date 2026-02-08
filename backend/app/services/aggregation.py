"""Time-series aggregation queries and dashboard helpers.

All functions accept an ``AsyncSession`` and return results directly -- they
do **not** manage transactions themselves.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from sqlalchemy import Date, Float, case, cast, distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_summary import ActivitySummary
from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.models.workout import Workout

# Valid resolutions accepted by ``date_trunc``
Resolution = Literal["minute", "hour", "day", "week", "month", "year"]

_VALID_RESOLUTIONS: set[str] = {
    "minute",
    "hour",
    "day",
    "week",
    "month",
    "year",
}


# ------------------------------------------------------------------
# Metric time-series
# ------------------------------------------------------------------


async def query_metric(
    session: AsyncSession,
    user_id: int,
    metric_type: str,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    resolution: Resolution = "day",
    aggregate: Literal["avg", "sum", "min", "max", "count"] = "avg",
) -> list[dict[str, Any]]:
    """Return an aggregated time-series for a single health metric.

    Parameters
    ----------
    session:
        Active async database session.
    user_id:
        Owning user's primary key.
    metric_type:
        The cleaned metric type (e.g. ``"StepCount"``).
    start / end:
        Optional time bounds (inclusive).
    resolution:
        PostgreSQL ``date_trunc`` bucket: minute, hour, day, week, month, year.
    aggregate:
        Aggregation function to apply within each bucket.

    Returns
    -------
    list[dict]
        Each dict has ``{"bucket": datetime, "value": float, "count": int}``.
    """
    if resolution not in _VALID_RESOLUTIONS:
        raise ValueError(
            f"Invalid resolution {resolution!r}; "
            f"must be one of {sorted(_VALID_RESOLUTIONS)}"
        )

    agg_fn = _agg_func(aggregate)

    bucket = func.date_trunc(resolution, HealthRecord.time).label("bucket")
    stmt = (
        select(
            bucket,
            agg_fn(HealthRecord.value).label("value"),
            func.count().label("count"),
        )
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric_type,
        )
        .group_by(bucket)
        .order_by(bucket)
    )

    if start is not None:
        stmt = stmt.where(HealthRecord.time >= start)
    if end is not None:
        stmt = stmt.where(HealthRecord.time <= end)

    result = await session.execute(stmt)
    return [
        {"bucket": row.bucket, "value": float(row.value) if row.value else 0.0, "count": row.count}
        for row in result.all()
    ]


# ------------------------------------------------------------------
# Available metrics
# ------------------------------------------------------------------


async def get_available_metrics(
    session: AsyncSession,
    user_id: int,
) -> list[dict[str, Any]]:
    """Return distinct health metric types with sample counts and units.

    Returns
    -------
    list[dict]
        ``[{"metric_type": str, "count": int, "unit": str, "latest": datetime}, ...]``
    """
    stmt = (
        select(
            HealthRecord.metric_type,
            func.count().label("count"),
            func.max(HealthRecord.unit).label("unit"),
            func.max(HealthRecord.time).label("latest"),
        )
        .where(HealthRecord.user_id == user_id)
        .group_by(HealthRecord.metric_type)
        .order_by(func.count().desc())
    )

    result = await session.execute(stmt)
    return [
        {
            "metric_type": row.metric_type,
            "count": row.count,
            "unit": row.unit,
            "latest": row.latest,
        }
        for row in result.all()
    ]


async def get_available_categories(
    session: AsyncSession,
    user_id: int,
) -> list[dict[str, Any]]:
    """Return distinct category types with counts.

    Returns
    -------
    list[dict]
        ``[{"category_type": str, "count": int, "latest": datetime}, ...]``
    """
    stmt = (
        select(
            CategoryRecord.category_type,
            func.count().label("count"),
            func.max(CategoryRecord.time).label("latest"),
        )
        .where(CategoryRecord.user_id == user_id)
        .group_by(CategoryRecord.category_type)
        .order_by(func.count().desc())
    )

    result = await session.execute(stmt)
    return [
        {
            "category_type": row.category_type,
            "count": row.count,
            "latest": row.latest,
        }
        for row in result.all()
    ]


# ------------------------------------------------------------------
# Dashboard summary
# ------------------------------------------------------------------


async def get_dashboard_summary(
    session: AsyncSession,
    user_id: int,
    target_date: dt.date | None = None,
) -> dict[str, Any]:
    """Build a summary of key metrics for a single day (defaults to today).

    Returns a dict with:
    - ``date``: the summarised date
    - ``steps``: total step count
    - ``active_energy_kj``: total active energy burned (kJ)
    - ``exercise_minutes``: exercise minutes from activity ring
    - ``stand_hours``: stand hours from activity ring
    - ``heart_rate_avg``: average heart rate
    - ``heart_rate_min``: minimum heart rate
    - ``heart_rate_max``: maximum heart rate
    - ``workouts``: number of workouts
    - ``activity_summary``: dict from ActivitySummary if available
    """
    if target_date is None:
        target_date = dt.date.today()

    day_start = dt.datetime.combine(
        target_date, dt.time.min, tzinfo=dt.timezone.utc
    )
    day_end = dt.datetime.combine(
        target_date, dt.time.max, tzinfo=dt.timezone.utc
    )

    summary: dict[str, Any] = {"date": target_date}

    # Steps
    steps_stmt = (
        select(func.sum(HealthRecord.value))
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == "StepCount",
            HealthRecord.time >= day_start,
            HealthRecord.time <= day_end,
        )
    )
    result = await session.execute(steps_stmt)
    summary["steps"] = result.scalar() or 0.0

    # Active energy (from HealthRecord)
    energy_stmt = (
        select(func.sum(HealthRecord.value))
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == "ActiveEnergyBurned",
            HealthRecord.time >= day_start,
            HealthRecord.time <= day_end,
        )
    )
    result = await session.execute(energy_stmt)
    summary["active_energy_kj"] = result.scalar() or 0.0

    # Heart rate stats
    hr_stmt = (
        select(
            func.avg(HealthRecord.value).label("avg"),
            func.min(HealthRecord.value).label("min"),
            func.max(HealthRecord.value).label("max"),
        )
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == "HeartRate",
            HealthRecord.time >= day_start,
            HealthRecord.time <= day_end,
        )
    )
    result = await session.execute(hr_stmt)
    row = result.one_or_none()
    if row and row.avg is not None:
        summary["heart_rate_avg"] = round(float(row.avg), 1)
        summary["heart_rate_min"] = float(row.min) if row.min else None
        summary["heart_rate_max"] = float(row.max) if row.max else None
    else:
        summary["heart_rate_avg"] = None
        summary["heart_rate_min"] = None
        summary["heart_rate_max"] = None

    # Workout count for the day
    workout_stmt = (
        select(func.count())
        .select_from(Workout)
        .where(
            Workout.user_id == user_id,
            Workout.time >= day_start,
            Workout.time <= day_end,
        )
    )
    result = await session.execute(workout_stmt)
    summary["workouts"] = result.scalar() or 0

    # Activity summary ring data
    activity_stmt = (
        select(ActivitySummary)
        .where(
            ActivitySummary.user_id == user_id,
            ActivitySummary.date == target_date,
        )
    )
    result = await session.execute(activity_stmt)
    activity = result.scalar_one_or_none()
    if activity:
        summary["activity_summary"] = {
            "active_energy_burned_kj": activity.active_energy_burned_kj,
            "active_energy_goal_kj": activity.active_energy_goal_kj,
            "exercise_minutes": activity.exercise_minutes,
            "exercise_goal_minutes": activity.exercise_goal_minutes,
            "stand_hours": activity.stand_hours,
            "stand_goal_hours": activity.stand_goal_hours,
        }
    else:
        summary["activity_summary"] = None

    return summary


# ------------------------------------------------------------------
# Category time-series
# ------------------------------------------------------------------


async def query_category(
    session: AsyncSession,
    user_id: int,
    category_type: str,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    resolution: Resolution = "day",
) -> list[dict[str, Any]]:
    """Return counts of category record values bucketed by time.

    Returns
    -------
    list[dict]
        ``[{"bucket": datetime, "value_label": str, "count": int}, ...]``
    """
    if resolution not in _VALID_RESOLUTIONS:
        raise ValueError(f"Invalid resolution {resolution!r}")

    bucket = func.date_trunc(resolution, CategoryRecord.time).label("bucket")
    stmt = (
        select(
            bucket,
            CategoryRecord.value_label,
            func.count().label("count"),
        )
        .where(
            CategoryRecord.user_id == user_id,
            CategoryRecord.category_type == category_type,
        )
        .group_by(bucket, CategoryRecord.value_label)
        .order_by(bucket)
    )

    if start is not None:
        stmt = stmt.where(CategoryRecord.time >= start)
    if end is not None:
        stmt = stmt.where(CategoryRecord.time <= end)

    result = await session.execute(stmt)
    return [
        {
            "bucket": row.bucket,
            "value_label": row.value_label,
            "count": row.count,
        }
        for row in result.all()
    ]


# ------------------------------------------------------------------
# Workout aggregation
# ------------------------------------------------------------------


async def get_workout_summary(
    session: AsyncSession,
    user_id: int,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Return workout counts and totals grouped by activity type.

    Returns
    -------
    list[dict]
        ``[{"activity_type": str, "count": int, "total_duration_sec": float,
            "total_distance_m": float, "total_energy_kj": float}, ...]``
    """
    stmt = (
        select(
            Workout.activity_type,
            func.count().label("count"),
            func.sum(Workout.duration_sec).label("total_duration_sec"),
            func.sum(Workout.total_distance_m).label("total_distance_m"),
            func.sum(Workout.total_energy_kj).label("total_energy_kj"),
        )
        .where(Workout.user_id == user_id)
        .group_by(Workout.activity_type)
        .order_by(func.count().desc())
    )

    if start is not None:
        stmt = stmt.where(Workout.time >= start)
    if end is not None:
        stmt = stmt.where(Workout.time <= end)

    result = await session.execute(stmt)
    return [
        {
            "activity_type": row.activity_type,
            "count": row.count,
            "total_duration_sec": float(row.total_duration_sec or 0),
            "total_distance_m": float(row.total_distance_m or 0),
            "total_energy_kj": float(row.total_energy_kj or 0),
        }
        for row in result.all()
    ]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _agg_func(name: str):
    """Return the SQLAlchemy aggregate function for the given name."""
    mapping = {
        "avg": func.avg,
        "sum": func.sum,
        "min": func.min,
        "max": func.max,
        "count": func.count,
    }
    fn = mapping.get(name.lower())
    if fn is None:
        raise ValueError(
            f"Unknown aggregate {name!r}; choose from {sorted(mapping)}"
        )
    return fn
