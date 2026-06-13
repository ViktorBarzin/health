"""Pydantic schemas for the Nutrition (Food catalog + Diary) endpoints.

Vocabulary (CONTEXT.md): a **Food** carries per-serving macros; a **Diary Entry**
is a Food logged with a ``quantity`` (number of servings) to one **Meal** of one
day. The day/per-meal totals are computed by the pure
:mod:`app.services.nutrition` core.

Quantity is the number of servings of the Food; an entry's macros are the Food's
per-serving macros × quantity (surfaced on :class:`DiaryEntryRead` so the client
needn't re-derive them).
"""

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from app.models.diary_entry import Meal


class FoodRead(BaseModel):
    """One catalog Food as returned to the client (per-serving macros)."""

    id: uuid.UUID
    name: str
    brand: str | None = None
    serving_size: float
    serving_unit: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    is_custom: bool
    source: str

    model_config = {"from_attributes": True}


class MacroTotalsRead(BaseModel):
    """A bundle of summed macros (mirrors services.nutrition.MacroTotals)."""

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class DiaryEntryCreate(BaseModel):
    """Log a Food to a Meal of a day. ``quantity`` is the number of servings."""

    food_id: uuid.UUID
    entry_date: dt.date
    meal: Meal
    quantity: float = Field(default=1.0, gt=0, le=10000)
    model_config = {"extra": "forbid"}


class DiaryEntryUpdate(BaseModel):
    """Edit a Diary Entry. Every field optional — only the sent ones change.

    The Food may be swapped, the entry moved to another Meal or day, or the
    quantity changed.
    """

    food_id: uuid.UUID | None = None
    entry_date: dt.date | None = None
    meal: Meal | None = None
    quantity: float | None = Field(default=None, gt=0, le=10000)
    model_config = {"extra": "forbid"}


class DiaryEntryRead(BaseModel):
    """One Diary Entry, with its computed (per-serving × quantity) macros.

    Built from the ORM ``DiaryEntry`` (+ its loaded ``food``). The Food's name,
    serving and per-serving macros come along so a list row is self-contained,
    and the entry's own scaled macros are surfaced so the client needn't multiply.
    """

    id: uuid.UUID
    food_id: uuid.UUID
    food_name: str
    brand: str | None = None
    entry_date: dt.date
    meal: Meal
    quantity: float
    serving_size: float
    serving_unit: str
    # The entry's macros = the Food's per-serving macros × quantity.
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: object) -> object:
        """Derive food fields + the scaled macros when validating off the ORM."""
        if isinstance(data, dict):
            return data
        food = data.food
        q = data.quantity
        return {
            "id": data.id,
            "food_id": data.food_id,
            "food_name": food.name,
            "brand": food.brand,
            "entry_date": data.entry_date,
            "meal": data.meal,
            "quantity": q,
            "serving_size": food.serving_size,
            "serving_unit": food.serving_unit,
            "calories": round(food.calories * q, 1),
            "protein_g": round(food.protein_g * q, 1),
            "carbs_g": round(food.carbs_g * q, 1),
            "fat_g": round(food.fat_g * q, 1),
        }


class MealSection(BaseModel):
    """One Meal's entries plus its subtotal, for the day view."""

    meal: Meal
    entries: list[DiaryEntryRead]
    totals: MacroTotalsRead


class DiaryDayRead(BaseModel):
    """A whole day's diary: the four Meal sections and the day total.

    The day view binds to this directly — every Meal slot is present (zeroed when
    empty), and ``total`` is the summed-once day total from the pure core.
    """

    entry_date: dt.date
    meals: list[MealSection]
    total: MacroTotalsRead


class DiaryDaySummary(BaseModel):
    """One day's totals for the history view (no per-entry detail)."""

    entry_date: dt.date
    total: MacroTotalsRead


# --------------------------------------------------------------------------- #
# Custom Foods (#22)
# --------------------------------------------------------------------------- #


class FoodCreate(BaseModel):
    """Create a custom (private) Food owned by the caller.

    Macros are **per serving** (one serving = ``serving_size`` of ``serving_unit``),
    matching the catalog convention. The created Food is ``source='custom'`` and
    private to the caller, usable in the diary like any Food.
    """

    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=200)
    serving_size: float = Field(gt=0, le=100000)
    serving_unit: str = Field(min_length=1, max_length=40)
    calories: float = Field(ge=0, le=100000)
    protein_g: float = Field(ge=0, le=100000)
    carbs_g: float = Field(ge=0, le=100000)
    fat_g: float = Field(ge=0, le=100000)
    model_config = {"extra": "forbid"}


class FoodUpdate(BaseModel):
    """Edit one of the caller's own custom Foods (only sent fields change).

    Editing a custom Food recomputes any Recipe that uses it as an ingredient (so
    a Recipe's stored macros stay correct). Only ``source='custom'`` Foods are
    editable — shared (generic/OFF) and recipe-backed Foods are not.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=200)
    serving_size: float | None = Field(default=None, gt=0, le=100000)
    serving_unit: str | None = Field(default=None, min_length=1, max_length=40)
    calories: float | None = Field(default=None, ge=0, le=100000)
    protein_g: float | None = Field(default=None, ge=0, le=100000)
    carbs_g: float | None = Field(default=None, ge=0, le=100000)
    fat_g: float | None = Field(default=None, ge=0, le=100000)
    model_config = {"extra": "forbid"}


# --------------------------------------------------------------------------- #
# Recipes (#22) — a user-defined Food composed of other Foods
# --------------------------------------------------------------------------- #


class RecipeIngredientInput(BaseModel):
    """One ingredient in a Recipe: a Food id and a quantity (number of servings)."""

    food_id: uuid.UUID
    quantity: float = Field(gt=0, le=10000)
    model_config = {"extra": "forbid"}


class RecipeCreate(BaseModel):
    """Create a Recipe: a name, a yield (servings the recipe makes), ingredients.

    Per-serving macros are **computed** from the ingredient Foods (Σ ÷ yield) — not
    supplied. At least one ingredient is required.
    """

    name: str = Field(min_length=1, max_length=200)
    yield_servings: float = Field(gt=0, le=10000)
    ingredients: list[RecipeIngredientInput] = Field(min_length=1)
    model_config = {"extra": "forbid"}


class RecipeUpdate(BaseModel):
    """Replace a Recipe's name/yield/ingredients (recomputes macros)."""

    name: str = Field(min_length=1, max_length=200)
    yield_servings: float = Field(gt=0, le=10000)
    ingredients: list[RecipeIngredientInput] = Field(min_length=1)
    model_config = {"extra": "forbid"}


class RecipeIngredientRead(BaseModel):
    """One ingredient in a Recipe detail: the Food + the quantity used."""

    food_id: uuid.UUID
    food_name: str
    quantity: float
    serving_size: float
    serving_unit: str
    # The ingredient's contribution at its quantity (per-serving macros × quantity).
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class RecipeRead(BaseModel):
    """A Recipe: its backing Food (id + computed per-serving macros) + ingredients.

    ``food_id`` is the id to log to the diary — a Recipe is loggable exactly like a
    Food. The macros here are the Recipe's computed **per-serving** values.
    """

    id: uuid.UUID
    food_id: uuid.UUID
    name: str
    yield_servings: float
    # The computed per-serving macros (stored on the backing Food).
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    ingredients: list[RecipeIngredientRead]
