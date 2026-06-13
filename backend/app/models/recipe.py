"""Recipe models — a user-defined Food composed of other Foods (#22).

CONTEXT.md ("Recipe"): "A user-defined Food composed of other Foods, with
computed per-serving macros." A Recipe **is a Food** (a row in ``foods`` with
``source='recipe'``, owned by the user) plus the ingredient list that defines it.
Modelling it as a Food is the key simplification: it is loggable to the diary,
searchable, and totalled **exactly like any other Food**, with no Recipe-awareness
anywhere on the read path. The diary already references ``foods.id`` — a Recipe
needs nothing new there.

Two tables back the "composed of other Foods" part:

* ``recipes`` — one row per Recipe, 1:1 with its backing Food (``food_id``,
  UNIQUE). Holds the ``yield_servings`` (how many servings the whole Recipe makes)
  and ``user_id`` (the owner — denormalised from the Food for a clean per-user
  Export scope and FK). Deleting the Food cascades the Recipe away.
* ``recipe_ingredients`` — one row per ingredient: the ingredient ``food_id`` and
  the ``quantity`` (number of servings of that Food in the whole Recipe).

**Compute-on-write** (documented choice): when a Recipe is created or edited, the
pure :func:`app.services.recipe.compute_recipe_macros` recomputes the backing
Food's per-serving macros (Σ ingredient macros ÷ yield) and they are stored on the
Food. So the hot read path (diary, search, daily totals) stays a plain Food read,
and "stays correct if an ingredient is edited" is honoured by recomputing every
Recipe that uses an ingredient Food when that Food is edited (a bounded, explicit
fan-out — see :mod:`app.services.recipe_query`). The alternative (compute-on-read)
would push a join+sum into every Food read; compute-on-write keeps reads trivial.
"""

import uuid

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Recipe(Base):
    """A user-defined Recipe: the backing Food + yield + ingredient list."""

    __tablename__ = "recipes"
    __table_args__ = (
        # Browse "my recipes" by owner.
        Index("ix_recipes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The owner (CONTEXT.md: a Recipe is user-defined and private). Denormalised
    # from the backing Food so the Export (#19) scopes it on user_id directly.
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The backing Food (source='recipe'). 1:1 — a Food is at most one Recipe.
    # Deleting the Food removes the Recipe (CASCADE); the Recipe owns the Food's
    # lifecycle from the API's side (deleting a Recipe deletes its Food).
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("foods.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # How many servings the whole Recipe yields; the divisor in the macro compute.
    yield_servings: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RecipeIngredient.position",
    )


class RecipeIngredient(Base):
    """One ingredient of a Recipe: an ingredient Food at a quantity (servings)."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        Index("ix_recipe_ingredients_recipe_id", "recipe_id"),
        # Reverse lookup: which Recipes use this ingredient Food (so editing the
        # Food can recompute the affected Recipes).
        Index("ix_recipe_ingredients_food_id", "food_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The ingredient Food. RESTRICT: a Food used as an ingredient can't be deleted
    # out from under a Recipe (mirrors the diary's FK to foods).
    food_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("foods.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Number of servings of the ingredient Food used in the whole Recipe.
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Stable display order of ingredients within the Recipe.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    # Eager-load the ingredient Food so the macro recompute / detail view has its
    # per-serving macros without an N+1 (matches DiaryEntry→Food).
    food: Mapped["Food"] = relationship(lazy="selectin")  # noqa: F821


from app.models.food import Food  # noqa: E402,F401  (resolve relationship)
