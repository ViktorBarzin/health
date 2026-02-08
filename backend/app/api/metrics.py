"""Health metrics API routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
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


@router.get("/available", response_model=list[MetricAvailable])
async def list_available_metrics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MetricAvailable]:
    """List distinct metric types with count and unit for the current user."""
    stmt = (
        select(
            HealthRecord.metric_type,
            HealthRecord.unit,
            func.count().label("count"),
            func.max(HealthRecord.time).label("latest_time"),
        )
        .where(HealthRecord.user_id == user.id)
        .group_by(HealthRecord.metric_type, HealthRecord.unit)
        .order_by(HealthRecord.metric_type)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        MetricAvailable(
            metric_type=row.metric_type,
            unit=row.unit,
            count=row.count,
            latest_time=row.latest_time,
        )
        for row in rows
    ]


@router.get("/{metric_type}", response_model=MetricResponse)
async def get_metric_data(
    metric_type: str,
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    resolution: Resolution = Query(default=Resolution.day),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MetricResponse:
    """Query health records for a specific metric type with optional aggregation."""
    base_filter = [
        HealthRecord.user_id == user.id,
        HealthRecord.metric_type == metric_type,
    ]
    if start is not None:
        base_filter.append(HealthRecord.time >= start)
    if end is not None:
        base_filter.append(HealthRecord.time <= end)

    if resolution == Resolution.raw:
        stmt = (
            select(HealthRecord.time, HealthRecord.value)
            .where(*base_filter)
            .order_by(HealthRecord.time)
        )
        result = await db.execute(stmt)
        rows = result.all()
        data = [
            MetricDataPoint(time=row.time, value=row.value)
            for row in rows
        ]
    else:
        # Map resolution to date_trunc interval
        trunc_map = {
            Resolution.day: "day",
            Resolution.week: "week",
            Resolution.month: "month",
        }
        interval = trunc_map[resolution]

        bucket = func.date_trunc(interval, HealthRecord.time).label("bucket")
        stmt = (
            select(
                bucket,
                func.avg(HealthRecord.value).label("avg_value"),
                func.min(HealthRecord.value).label("min_value"),
                func.max(HealthRecord.value).label("max_value"),
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
                value=round(row.avg_value, 4),
                min=round(row.min_value, 4),
                max=round(row.max_value, 4),
            )
            for row in rows
        ]

    # Compute overall stats
    stats_stmt = (
        select(
            func.avg(HealthRecord.value).label("avg"),
            func.min(HealthRecord.value).label("min"),
            func.max(HealthRecord.value).label("max"),
            func.count().label("count"),
        )
        .where(*base_filter)
    )
    stats_result = await db.execute(stats_stmt)
    stats_row = stats_result.one()

    stats = MetricStats(
        avg=round(stats_row.avg, 4) if stats_row.avg is not None else None,
        min=round(stats_row.min, 4) if stats_row.min is not None else None,
        max=round(stats_row.max, 4) if stats_row.max is not None else None,
        count=stats_row.count,
    )

    # Compute trend percentage (compare last half vs first half of data)
    if len(data) >= 2:
        mid = len(data) // 2
        first_half_avg = sum(d.value for d in data[:mid]) / mid
        second_half_avg = sum(d.value for d in data[mid:]) / (len(data) - mid)
        if first_half_avg != 0:
            stats.trend_pct = round(
                ((second_half_avg - first_half_avg) / first_half_avg) * 100, 2
            )

    return MetricResponse(data=data, stats=stats)
