"""Per-user, per-Exercise preferences.

The rest timer's per-Exercise default rest duration (#7) is a USER preference,
not a property of the shared movement: the Exercise library is shared across
users (CONTEXT.md), so it must never be stored on the global ``exercises`` row —
one user setting their bench rest to 180 s would change it for everyone, breaking
the "fully isolated private accounts" rule. Instead it lives here, keyed by
(user, exercise), as a per-user override.

A small, extensible home for per-user-per-Exercise settings: today just
``default_rest_seconds`` (NULL → fall back to the app's global default); future
per-user knobs (#11) can join it without a new table.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The app-wide fallback rest, used when a user hasn't set a per-Exercise default.
DEFAULT_REST_SECONDS = 120


class ExercisePref(Base):
    """One user's preferences for one Exercise (global or their own custom)."""

    __tablename__ = "user_exercise_prefs"
    __table_args__ = (
        # One prefs row per (user, exercise).
        UniqueConstraint(
            "user_id", "exercise_id", name="uq_user_exercise_pref"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The rest timer's auto-start duration for this Exercise, in seconds. NULL =
    # the user hasn't overridden it → the app's global default applies.
    default_rest_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # Exclusion (CONTEXT.md): "never recommend this Exercise again". Filters every
    # generator path exactly like Gym Profile equipment; explicit only — never
    # inferred from Swap behaviour (ADR-0002 determinism).
    excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
