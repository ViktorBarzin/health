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
