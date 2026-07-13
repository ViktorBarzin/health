"""Web Push storage (ADR-0010): subscriptions + the pending rest-timer schedule.

``push_subscriptions`` — one row per browser PushManager subscription (a user
can hold several: phone PWA, desktop). The endpoint is the natural key — a
re-subscribe upserts the crypto keys rather than duplicating. Nothing here is
secret in the credential sense (the endpoint+keys only let US send to that
browser), but they're still per-user scoped everywhere.

``push_timers`` — the server-side rest-timer schedule: at ``fire_at`` the
poller sends the stored notification to every subscription the user has.
**One pending timer per user** (user_id is the PK): logging the next set or
adjusting the countdown simply replaces the row, skipping deletes it. Rows are
claimed (deleted) inside the delivery transaction with SKIP LOCKED, so any
number of app replicas can run the poller without double-sending.
"""

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PushSubscription(Base):
    """One browser push subscription (endpoint + encryption keys) of one user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The push-service URL for this browser — unique: re-subscribing upserts.
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PushTimer(Base):
    """The user's single pending rest-timer push (replaced on every schedule)."""

    __tablename__ = "push_timers"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    fire_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(String(200), nullable=False)
    # The in-app path the notification tap opens (e.g. /sessions/<id>).
    url: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
