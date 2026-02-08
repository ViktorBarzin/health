import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CategoryRecord(Base):
    __tablename__ = "category_records"
    __table_args__ = (
        Index("ix_category_records_batch_id", "batch_id"),
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    category_type: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    value_label: Mapped[str | None] = mapped_column(String, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("data_sources.id"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
