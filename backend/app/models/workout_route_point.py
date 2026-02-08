import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkoutRoutePoint(Base):
    __tablename__ = "workout_route_points"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    workout_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workouts.id"), primary_key=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
