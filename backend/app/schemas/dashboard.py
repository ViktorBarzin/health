"""Pydantic schemas for dashboard and import status endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    steps_today: float | None = None
    active_energy_today: float | None = None
    exercise_minutes_today: float | None = None
    stand_hours_today: int | None = None
    resting_hr: float | None = None
    hrv: float | None = None
    spo2: float | None = None
    sleep_hours_last_night: float | None = None


class ImportStatusResponse(BaseModel):
    batch_id: uuid.UUID
    status: str
    record_count: int
    filename: str
    imported_at: datetime

    model_config = {"from_attributes": True}
