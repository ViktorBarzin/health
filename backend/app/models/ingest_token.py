"""Per-user ingest tokens (M7, ADR-0012) — the push Connector's credential.

The iOS Shortcut authenticates to ``POST /api/ingest/apple`` with a bearer
token the user minted in Settings. Only a SHA-256 hash is stored — the
plaintext is shown exactly once at creation (a DB leak reveals nothing
usable), mirroring the fail-safe posture of the Connection credential cipher.
``prefix`` (the first characters of the plaintext) is kept so the list UI can
say *which* token a row is without storing the secret; ``last_used_at`` powers
the "last synced" display and doubles as the liveness check for the whole
auto-sync pipeline.
"""

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IngestToken(Base):
    """One revocable push-ingest credential of one user."""

    __tablename__ = "ingest_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
