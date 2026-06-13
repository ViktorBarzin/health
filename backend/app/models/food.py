"""Food catalog model — the per-serving macro source (CONTEXT.md "Food").

CONTEXT.md ("Food"): "An entry in the food catalog with per-serving macros —
from the Open Food Facts cache, the generic whole-foods seed, or user-created."

The table mirrors the Exercise library's shared+custom design so the three
provenances slot into one table:

* ``user_id IS NULL`` is a **shared** Food — the generic whole-foods seed
  (idempotent upsert keyed on ``slug``), and later the Open Food Facts cache
  (#22). A row with a non-NULL ``user_id`` is that user's private custom Food
  (#22). A user's catalog view is global ∪ their own — exactly the Exercise rule.
* ``source`` records the provenance (``generic`` / ``off`` / ``custom``); the
  generic seed writes ``generic``. ``off_id`` (the Open Food Facts barcode) and
  ``brand`` are nullable now and populated by the OFF integration in #22.

Macros are stored **per serving**: one serving is ``serving_size`` of
``serving_unit`` (e.g. 100 "g", or 1 "egg"), and ``calories`` / ``protein_g`` /
``carbs_g`` / ``fat_g`` are the macros for that one serving. A Diary Entry scales
these by its ``quantity`` (number of servings) — see :mod:`app.services.nutrition`
and :mod:`app.models.diary_entry`. Keeping macros per-serving (not per-gram)
makes whole-unit foods ("1 egg", "1 slice") first-class without a density model.

Two partial unique indexes key the natural key ``slug`` separately per namespace
(global vs each user), because Postgres treats NULLs as distinct in a plain
composite unique — the same idiom the Exercise table uses.
"""

import uuid

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Food(Base):
    """One catalog Food with per-serving macros. Shared (seed/OFF) or custom."""

    __tablename__ = "foods"
    __table_args__ = (
        # Idempotency / natural-key uniqueness, split by namespace because a
        # plain UNIQUE(user_id, slug) would let duplicate global rows in (NULLs
        # compare distinct). Shared catalog (generic seed + OFF cache):
        Index(
            "uq_food_global_slug",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        # Per-user custom namespace (#22):
        Index(
            "uq_food_user_slug",
            "user_id",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # Catalog browse: a user fetches global ∪ their own.
        Index("ix_foods_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = shared catalog Food (generic seed / OFF cache); non-NULL = a user's
    # private custom Food (#22).
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Stable natural key: seed slug for generic rows, name-derived for custom.
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Optional brand (e.g. for OFF/custom packaged foods); generic foods have none.
    brand: Mapped[str | None] = mapped_column(String, nullable=True)

    # One serving = ``serving_size`` of ``serving_unit`` (e.g. 100 "g", 1 "egg").
    serving_size: Mapped[float] = mapped_column(Float, nullable=False)
    serving_unit: Mapped[str] = mapped_column(String, nullable=False)

    # Macros for ONE serving. A Diary Entry scales these by its quantity.
    calories: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g: Mapped[float] = mapped_column(Float, nullable=False)

    # Provenance: 'generic' for the whole-foods seed, 'off' for an Open Food Facts
    # cache row (#22), 'custom' for a user-created Food (#22).
    source: Mapped[str] = mapped_column(
        String, nullable=False, server_default="custom"
    )
    # Open Food Facts barcode/id, populated by the OFF integration (#22).
    off_id: Mapped[str | None] = mapped_column(String, nullable=True)

    @property
    def is_custom(self) -> bool:
        """True for a user's private Food, False for the shared catalog."""
        return self.user_id is not None
