import datetime as dt
import uuid

from sqlalchemy import Date, Float, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivitySummary(Base):
    __tablename__ = "activity_summaries"
    __table_args__ = (Index("ix_activity_summaries_batch_id", "batch_id"),)

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    active_energy_burned_kj: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    active_energy_goal_kj: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    exercise_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    exercise_goal_minutes: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    stand_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stand_goal_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
