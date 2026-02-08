import datetime as dt

from sqlalchemy import Date, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivitySummary(Base):
    __tablename__ = "activity_summaries"

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
