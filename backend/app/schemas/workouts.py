"""Pydantic schemas for workout endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RoutePoint(BaseModel):
    time: datetime
    latitude: float
    longitude: float
    altitude_m: float | None = None

    model_config = {"from_attributes": True}


class WorkoutSummary(BaseModel):
    id: uuid.UUID
    activity_type: str
    time: datetime
    end_time: datetime | None = None
    duration_sec: float | None = None
    total_distance_m: float | None = None
    total_energy_kj: float | None = None

    model_config = {"from_attributes": True}


class WorkoutDetail(WorkoutSummary):
    metadata: dict | None = None
    route_points: list[RoutePoint] = []
