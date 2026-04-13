"""Health metrics API routes."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.models.user import User
from app.schemas.metrics import (
    MetricAvailable,
    MetricDataPoint,
    MetricResponse,
    MetricStats,
    Resolution,
)

router = APIRouter()

_CUMULATIVE_METRICS = {
    "ActiveEnergyBurned",
    "AppleExerciseTime",
    "AppleStandTime",
    "BasalEnergyBurned",
    "DietaryCaffeine",
    "DietaryCarbohydrates",
    "DietaryEnergyConsumed",
    "DietaryFatTotal",
    "DietaryProtein",
    "DietaryWater",
    "DistanceCycling",
    "DistanceSwimming",
    "DistanceWalkingRunning",
    "FlightsClimbed",
    "SixMinuteWalkTestDistance",
    "StepCount",
}
_SLEEP_CATEGORY = "SleepAnalysis"
_SLEEP_ASLEEP_PATTERN = "%Asleep%"


def _ensure_utc(dt_val: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt_val.tzinfo is None:
        return dt_val.replace(tzinfo=timezone.utc)
    return dt_val


def _end_of_day(dt_val: datetime) -> datetime:
    """Adjust a midnight datetime to end-of-day so the full day is included."""
    dt_val = _ensure_utc(dt_val)
    if dt_val.hour == 0 and dt_val.minute == 0 and dt_val.second == 0:
        return dt_val + timedelta(days=1)
    return dt_val


def _build_stats(values: list[float]) -> MetricStats:
    if not values:
        return MetricStats()
    total = sum(values)
    return MetricStats(
        avg=round(total / len(values), 4),
        min=round(min(values), 4),
        max=round(max(values), 4),
        total=round(total, 4),
        count=len(values),
    )


def _apply_trend(stats: MetricStats, data: list[MetricDataPoint]) -> MetricStats:
    if len(data) < 2:
        return stats

    mid = len(data) // 2
    if mid == 0 or len(data) == mid:
        return stats

    first_half_avg = sum(d.value for d in data[:mid]) / mid
    second_half_avg = sum(d.value for d in data[mid:]) / (len(data) - mid)
    if first_half_avg != 0:
        stats.trend_pct = round(
            ((second_half_avg - first_half_avg) / first_half_avg) * 100, 2
        )
    return stats


def _bucket_interval(resolution: Resolution) -> str:
    return {
        Resolution.day: "day",
        Resolution.week: "week",
        Resolution.month: "month",
    }[resolution]


async def _list_health_metrics(
    user_id: int,
    db: AsyncSession,
) -> list[MetricAvailable]:
    stmt = (
        select(
            HealthRecord.metric_type,
            func.max(HealthRecord.unit).label("unit"),
            func.count().label("count"),
            func.max(HealthRecord.time).label("latest_time"),
        )
        .where(HealthRecord.user_id == user_id)
        .group_by(HealthRecord.metric_type)
        .order_by(HealthRecord.metric_type)
    )
    result = await db.execute(stmt)
    return [
        MetricAvailable(
            metric_type=row.metric_type,
            unit=row.unit or "",
            count=row.count,
            latest_time=row.latest_time,
        )
        for row in result.all()
    ]


async def _list_category_metrics(
    user_id: int,
    db: AsyncSession,
) -> list[MetricAvailable]:
    stmt = (
        select(
            CategoryRecord.category_type,
            func.count().label("count"),
            func.max(func.coalesce(CategoryRecord.end_time, CategoryRecord.time)).label(
                "latest_time"
            ),
        )
        .where(CategoryRecord.user_id == user_id)
        .group_by(CategoryRecord.category_type)
        .order_by(CategoryRecord.category_type)
    )
    result = await db.execute(stmt)
    return [
        MetricAvailable(
            metric_type=row.category_type,
            unit="hr" if row.category_type == _SLEEP_CATEGORY else "count",
            count=row.count,
            latest_time=row.latest_time,
        )
        for row in result.all()
    ]


async def _health_metric_exists(
    user_id: int,
    metric_type: str,
    db: AsyncSession,
) -> bool:
    stmt = (
        select(HealthRecord.metric_type)
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric_type,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _fetch_health_metric(
    user_id: int,
    metric_type: str,
    start: datetime | None,
    end: datetime | None,
    resolution: Resolution,
    limit: int,
    db: AsyncSession,
) -> MetricResponse:
    base_filter = [
        HealthRecord.user_id == user_id,
        HealthRecord.metric_type == metric_type,
    ]
    if start is not None:
        base_filter.append(HealthRecord.time >= _ensure_utc(start))
    if end is not None:
        base_filter.append(HealthRecord.time <= _end_of_day(end))

    if resolution == Resolution.raw:
        stmt = (
            select(HealthRecord.time, HealthRecord.value)
            .where(*base_filter)
            .order_by(HealthRecord.time)
            .limit(limit)
        )
        result = await db.execute(stmt)
        data = [MetricDataPoint(time=row.time, value=row.value) for row in result.all()]
        stats = _build_stats([point.value for point in data])
        return MetricResponse(data=data, stats=_apply_trend(stats, data))

    interval = _bucket_interval(resolution)
    bucket = func.date_trunc(interval, HealthRecord.time).label("bucket")
    aggregate_fn = (
        func.sum if metric_type in _CUMULATIVE_METRICS else func.avg
    )
    stmt = (
        select(
            bucket,
            aggregate_fn(HealthRecord.value).label("bucket_value"),
            func.min(HealthRecord.value).label("min_value"),
            func.max(HealthRecord.value).label("max_value"),
            func.count().label("cnt"),
        )
        .where(*base_filter)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    result = await db.execute(stmt)
    rows = result.all()
    data = [
        MetricDataPoint(
            time=row.bucket,
            value=round(row.bucket_value, 4),
            min=round(row.min_value, 4),
            max=round(row.max_value, 4),
        )
        for row in rows
    ]
    stats = _build_stats([point.value for point in data])
    if rows:
        stats.count = sum(row.cnt for row in rows)
    return MetricResponse(data=data, stats=_apply_trend(stats, data))


async def _fetch_sleep_metric(
    user_id: int,
    start: datetime | None,
    end: datetime | None,
    resolution: Resolution,
    limit: int,
    db: AsyncSession,
) -> MetricResponse:
    anchor_time = func.coalesce(CategoryRecord.end_time, CategoryRecord.time)
    duration_hours = (
        func.extract("epoch", anchor_time - CategoryRecord.time) / 3600.0
    )
    filters = [
        CategoryRecord.user_id == user_id,
        CategoryRecord.category_type == _SLEEP_CATEGORY,
        CategoryRecord.value.like(_SLEEP_ASLEEP_PATTERN),
        CategoryRecord.end_time.is_not(None),
    ]
    if start is not None:
        filters.append(CategoryRecord.time >= _ensure_utc(start))
    if end is not None:
        filters.append(anchor_time <= _end_of_day(end))

    if resolution == Resolution.raw:
        stmt = (
            select(anchor_time.label("time"), duration_hours.label("value"))
            .where(*filters)
            .order_by(anchor_time)
            .limit(limit)
        )
        result = await db.execute(stmt)
        data = [
            MetricDataPoint(time=row.time, value=round(row.value, 4))
            for row in result.all()
        ]
        stats = _build_stats([point.value for point in data])
        return MetricResponse(data=data, stats=_apply_trend(stats, data))

    interval = _bucket_interval(resolution)
    bucket = func.date_trunc(interval, anchor_time).label("bucket")
    stmt = (
        select(
            bucket,
            func.sum(duration_hours).label("bucket_value"),
            func.min(duration_hours).label("min_value"),
            func.max(duration_hours).label("max_value"),
            func.count().label("cnt"),
        )
        .where(*filters)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    result = await db.execute(stmt)
    rows = result.all()
    data = [
        MetricDataPoint(
            time=row.bucket,
            value=round(row.bucket_value, 4),
            min=round(row.min_value, 4),
            max=round(row.max_value, 4),
        )
        for row in rows
    ]
    stats = _build_stats([point.value for point in data])
    if rows:
        stats.count = sum(row.cnt for row in rows)
    return MetricResponse(data=data, stats=_apply_trend(stats, data))


async def _fetch_category_metric(
    user_id: int,
    category_type: str,
    start: datetime | None,
    end: datetime | None,
    resolution: Resolution,
    limit: int,
    db: AsyncSession,
) -> MetricResponse:
    anchor_time = func.coalesce(CategoryRecord.end_time, CategoryRecord.time)
    filters = [
        CategoryRecord.user_id == user_id,
        CategoryRecord.category_type == category_type,
    ]
    if start is not None:
        filters.append(CategoryRecord.time >= _ensure_utc(start))
    if end is not None:
        filters.append(anchor_time <= _end_of_day(end))

    if resolution == Resolution.raw:
        stmt = (
            select(anchor_time.label("time"))
            .where(*filters)
            .order_by(anchor_time)
            .limit(limit)
        )
        result = await db.execute(stmt)
        data = [MetricDataPoint(time=row.time, value=1.0) for row in result.all()]
        stats = _build_stats([point.value for point in data])
        return MetricResponse(data=data, stats=_apply_trend(stats, data))

    interval = _bucket_interval(resolution)
    bucket = func.date_trunc(interval, anchor_time).label("bucket")
    stmt = (
        select(bucket, func.count().label("bucket_value"))
        .where(*filters)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    result = await db.execute(stmt)
    rows = result.all()
    data = [
        MetricDataPoint(
            time=row.bucket,
            value=float(row.bucket_value),
            min=float(row.bucket_value),
            max=float(row.bucket_value),
        )
        for row in rows
    ]
    stats = _build_stats([point.value for point in data])
    if rows:
        stats.count = int(sum(row.bucket_value for row in rows))
    return MetricResponse(data=data, stats=_apply_trend(stats, data))


@router.get("/available", response_model=list[MetricAvailable])
async def list_available_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MetricAvailable]:
    """List distinct metric and category types for the current user."""
    health_metrics = await _list_health_metrics(user.id, db)
    category_metrics = await _list_category_metrics(user.id, db)
    combined = {metric.metric_type: metric for metric in health_metrics}
    for metric in category_metrics:
        combined.setdefault(metric.metric_type, metric)
    return [combined[key] for key in sorted(combined)]


@router.get("/{metric_type}", response_model=MetricResponse)
async def get_metric_data(
    metric_type: str,
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    resolution: Resolution = Query(default=Resolution.day),
    limit: int = Query(default=10_000, ge=1, le=100_000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MetricResponse:
    """Query quantity or category records for a specific metric type."""
    if await _health_metric_exists(user.id, metric_type, db):
        return await _fetch_health_metric(
            user.id, metric_type, start, end, resolution, limit, db
        )

    if metric_type == _SLEEP_CATEGORY:
        return await _fetch_sleep_metric(
            user.id, start, end, resolution, limit, db
        )

    return await _fetch_category_metric(
        user.id, metric_type, start, end, resolution, limit, db
    )
