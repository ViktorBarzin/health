import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HealthRecord(Base):
    __tablename__ = "health_records"
    __table_args__ = (
        Index("ix_health_records_user_metric_time", "user_id", "metric_type", "time"),
        Index("ix_health_records_batch_id", "batch_id"),
        UniqueConstraint(
            "user_id",
            "metric_type",
            "time",
            "value",
            "source_id",
            name="uq_health_record_dedup",
        ),
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    metric_type: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("data_sources.id"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
