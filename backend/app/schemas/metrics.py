"""Pydantic schemas for health metric endpoints."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Resolution(str, Enum):
    raw = "raw"
    day = "day"
    week = "week"
    month = "month"


class MetricAvailable(BaseModel):
    metric_type: str
    unit: str
    count: int
    latest_time: datetime | None = None

    model_config = {"from_attributes": True}


class MetricDataPoint(BaseModel):
    time: datetime
    value: float
    min: float | None = None
    max: float | None = None


class MetricStats(BaseModel):
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    count: int = 0
    trend_pct: float | None = None


class MetricResponse(BaseModel):
    data: list[MetricDataPoint]
    stats: MetricStats
