"""Gym Profile model — a user's available equipment.

CONTEXT.md ("Gym Profile"): "A user's set of available equipment; constrains
which Exercises a Recommendation may select." Consumed by the plate calculator
now (the bar + plate denominations) and by the freestyle Recommendation engine
(#11) later (the equipment list, aligned with the Exercise library's
``equipment`` values so the generator can filter by it).

Shape decisions:

* **One row per user** (``user_id`` UNIQUE) — a Gym Profile is a singleton the
  user edits in Settings, get-or-created on first read (mirroring how
  ``get_current_user`` get-or-creates the User).
* The plate inventory is two **JSONB lists of floats**: ``bar_weights_kg`` (the
  bar(s) they own — multiple, since a gym may have a 20 kg and a 15 kg bar) and
  ``plate_weights_kg`` (the plate denominations they own). They are short, read
  whole and written whole, and the plate calculator wants them as arrays — a
  normalized plates table would be over-engineering (YAGNI), so JSONB lists.
* ``equipment`` is a **JSONB list of strings** drawn from the same vocabulary as
  ``exercises.equipment`` (barbell, dumbbell, machine, cable, …) so #11 can
  constrain Exercise selection by what the user has. Free text rather than an
  enum because the dataset's ``equipment`` column is itself free text and custom
  Exercises aren't constrained to a fixed set.

Sensible defaults (a standard metric commercial gym) are baked in so a brand-new
user gets a working plate calculator immediately without configuring anything.
"""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# A standard metric commercial-gym loadout — the defaults a new Gym Profile gets.
DEFAULT_BAR_WEIGHTS_KG: list[float] = [20.0]
DEFAULT_PLATE_WEIGHTS_KG: list[float] = [1.25, 2.5, 5.0, 10.0, 15.0, 20.0, 25.0]
# Equipment kinds, aligned with the free-exercise-db ``equipment`` vocabulary the
# Exercise library uses (so #11 can intersect this list with an Exercise's need).
DEFAULT_EQUIPMENT: list[str] = [
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "kettlebells",
    "bands",
    "body only",
]


class GymProfile(Base):
    """A user's available gym equipment (singleton per user)."""

    __tablename__ = "gym_profiles"
    __table_args__ = (
        # One Gym Profile per user (get-or-created on first read).
        UniqueConstraint("user_id", name="uq_gym_profile_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The bar(s) the user owns, in kg (a list — a gym may have several).
    bar_weights_kg: Mapped[list[float]] = mapped_column(
        JSONB, nullable=False, default=lambda: list(DEFAULT_BAR_WEIGHTS_KG)
    )
    # The plate denominations the user owns, in kg (each available in pairs).
    plate_weights_kg: Mapped[list[float]] = mapped_column(
        JSONB, nullable=False, default=lambda: list(DEFAULT_PLATE_WEIGHTS_KG)
    )
    # General equipment kinds available, aligned with exercises.equipment values.
    equipment: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=lambda: list(DEFAULT_EQUIPMENT)
    )
