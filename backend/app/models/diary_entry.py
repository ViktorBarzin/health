"""Diary Entry model — a Food logged with a quantity to one Meal of one day.

Vocabulary (CONTEXT.md, strictly observed):

* **Diary Entry**: "A Food logged with a quantity to one Meal of one day."
  (_Avoid_: log, food log entry.) Private to its user.
* **Meal**: "One of the four daily slots a Diary Entry lands in: breakfast,
  lunch, dinner, snack." A native Postgres enum — a typed dimension the per-meal
  totals ``GROUP BY``, not free text (the same idiom as ``set_type``/``muscle``).

Quantity semantics (documented decision): ``quantity`` is the **number of
servings** of the referenced Food. An entry's macros are the Food's per-serving
macros × ``quantity`` (see :mod:`app.services.nutrition`). So a Food whose
serving is "100 g" logged at quantity 1.5 contributes the 150 g macro values, and
"Egg, large" at quantity 2 contributes two eggs. This keeps the Food the single
source of macro/unit truth; the entry only scales it — simpler and more general
than storing grams, and it makes whole-unit foods first-class.

The entry is an entity table with a UUID PK (matching ``training_sessions`` etc.)
— individually addressable for edit/delete. ``entry_date`` is a plain DATE: a
Diary Entry belongs to a *day* and a Meal, not to a wall-clock instant.
"""

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Meal(str, enum.Enum):
    """The four daily Meal slots a Diary Entry lands in (CONTEXT.md "Meal").

    A typed dimension, not free text, so per-meal totals can ``GROUP BY`` it.
    """

    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


# SQLAlchemy Enum type. ``values_callable`` stores the enum *values* as the DB
# labels (consistent with the muscle/set_type enums). ``create_type`` defaults to
# True so metadata-driven ``create_all`` (the test suite) provisions the Postgres
# type; the Alembic migration creates it explicitly with ``create_type=False``.
_MEAL_ENUM = SAEnum(
    Meal,
    name="meal",
    values_callable=lambda e: [m.value for m in e],
)


class DiaryEntry(Base):
    """One Food logged with a quantity to one Meal of one day, for one user."""

    __tablename__ = "diary_entries"
    __table_args__ = (
        # The common read: "this user's entries for a given day" (the day view),
        # newest meals grouped. Leading user_id + entry_date is the day-view path.
        Index("ix_diary_entries_user_date", "user_id", "entry_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The Food logged. RESTRICT: a Food in use can't be hard-deleted out from
    # under an entry (the seed never deletes; custom-Food deletes are #22's
    # concern and would re-point or refuse there).
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("foods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # The day this entry belongs to (not a timestamp — a Diary Entry is day+meal).
    entry_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    meal: Mapped[Meal] = mapped_column(_MEAL_ENUM, nullable=False)
    # Number of servings of the Food (see module docstring for the semantics).
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Tie-break for ordering entries logged into the same meal on the same day.
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Eager-load the Food so an entry's macros (per-serving × quantity) and name
    # are available without an N+1; matches the Set→Exercise selectin pattern.
    food: Mapped["Food"] = relationship(lazy="selectin")  # noqa: F821


from app.models.food import Food  # noqa: E402,F401  (resolve relationship)
