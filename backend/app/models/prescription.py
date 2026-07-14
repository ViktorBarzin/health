"""Prescription — the immutable snapshot of what a started Recommendation said.

CONTEXT.md ("Prescription"; ADR-0011): editing or logging never rewrites it; it
exists so performed work can be measured against planned work (Adherence).
Written once by ``instantiate_session`` for every start path; Sessions started
empty/manually have no row and are simply unmeasured.

``slots`` is the ordered JSONB list ``[{exercise_id, muscle?, target_sets,
target_reps, target_weight_kg}]`` — exactly what the user was shown at start.
"""

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PrescriptionSource(str, enum.Enum):
    """Which start path produced the snapshot (all engine-generated)."""

    program = "program"
    freestyle = "freestyle"
    adjusted = "adjusted"
    explicit = "explicit"  # WYSIWYG start: swapped/shaped/overridden previews


class Prescription(Base):
    """One started Session's planned slots, frozen at instantiation time."""

    __tablename__ = "prescriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The Program context when the proposal was Program-drawn; SET NULL keeps the
    # adherence history meaningful even if a Program row is ever deleted.
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="SET NULL"),
        nullable=True,
    )
    program_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[PrescriptionSource] = mapped_column(
        Enum(PrescriptionSource, name="prescription_source", native_enum=True),
        nullable=False,
    )
    slots: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
