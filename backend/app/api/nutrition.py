"""Nutrition API — the Food catalog + Diary (the MyFitnessPal core).

A **Food** carries per-serving macros; a **Diary Entry** is a Food logged with a
``quantity`` (number of servings) to one **Meal** of one day. Everything in the
diary is scoped to ``get_current_user`` — a user only ever sees or mutates their
own Diary Entries. The Food catalog is shared (global ∪ the caller's own custom
Foods, the latter arriving in #22), exactly like the Exercise library.

Daily and per-meal totals are computed by the **pure** :mod:`app.services.nutrition`
core (Σ Food per-serving macros × quantity), kept separate from the DB so the
analytics/Budget (#23) slices reuse the same definition.

Out of scope here (#22/#23): barcode scanning, the Open Food Facts integration,
user-created custom Foods and Recipes, and the Budget. The Food model leaves room
for them (nullable ``user_id`` + ``source`` + ``off_id``).
"""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.diary_entry import DiaryEntry, Meal
from app.models.food import Food
from app.models.user import User
from app.schemas.nutrition import (
    DiaryDayRead,
    DiaryDaySummary,
    DiaryEntryCreate,
    DiaryEntryRead,
    DiaryEntryUpdate,
    FoodRead,
    MacroTotalsRead,
    MealSection,
)
from app.services.nutrition import EntryMacros, MacroTotals, daily_totals

router = APIRouter()


def _visible_food_filter(user_id: int):
    """The catalog visibility rule: shared (NULL user_id) ∪ the caller's own."""
    return or_(Food.user_id.is_(None), Food.user_id == user_id)


# --------------------------------------------------------------------------- #
# Food catalog
# --------------------------------------------------------------------------- #


@router.get("/foods", response_model=list[FoodRead])
async def search_foods(
    search: str | None = Query(default=None, description="Case-insensitive name match."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FoodRead]:
    """Search the Food catalog (shared ∪ the caller's own), by name."""
    stmt = select(Food).where(_visible_food_filter(user.id))
    if search and search.strip():
        stmt = stmt.where(Food.name.ilike(f"%{search.strip()}%"))
    stmt = stmt.order_by(Food.name).limit(limit).offset(offset)
    foods = (await db.execute(stmt)).scalars().all()
    return [FoodRead.model_validate(f) for f in foods]


@router.get("/foods/{food_id}", response_model=FoodRead)
async def get_food(
    food_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FoodRead:
    """Fetch one Food the caller may see (shared or their own custom)."""
    food = await _get_visible_food(db, food_id, user)
    return FoodRead.model_validate(food)


async def _get_visible_food(
    db: AsyncSession, food_id: uuid.UUID, user: User
) -> Food:
    """Load a Food visible to the caller, or raise 404 (no existence leak)."""
    stmt = select(Food).where(Food.id == food_id, _visible_food_filter(user.id))
    food = (await db.execute(stmt)).scalar_one_or_none()
    if food is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Food not found"
        )
    return food


# --------------------------------------------------------------------------- #
# Diary Entry CRUD
# --------------------------------------------------------------------------- #


async def _get_owned_entry(
    db: AsyncSession, entry_id: uuid.UUID, user: User
) -> DiaryEntry:
    """Load a Diary Entry owned by the caller, or 404 (no existence leak)."""
    stmt = select(DiaryEntry).where(
        DiaryEntry.id == entry_id, DiaryEntry.user_id == user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Diary entry not found"
        )
    return entry


@router.post(
    "/entries", response_model=DiaryEntryRead, status_code=status.HTTP_201_CREATED
)
async def create_entry(
    payload: DiaryEntryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiaryEntryRead:
    """Log a Food (with a quantity) to a Meal of a day for the caller.

    The Food must be visible to the caller (shared or their own custom) — logging
    another user's private Food is a 404, not a leak.
    """
    await _get_visible_food(db, payload.food_id, user)
    entry = DiaryEntry(
        user_id=user.id,
        food_id=payload.food_id,
        entry_date=payload.entry_date,
        meal=payload.meal,
        quantity=payload.quantity,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry, attribute_names=["food"])
    return DiaryEntryRead.model_validate(entry)


@router.patch("/entries/{entry_id}", response_model=DiaryEntryRead)
async def update_entry(
    entry_id: uuid.UUID,
    payload: DiaryEntryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiaryEntryRead:
    """Edit a Diary Entry: swap the Food, move Meal/day, or change quantity.

    Only fields present in the request change. A new Food must be visible to the
    caller.
    """
    entry = await _get_owned_entry(db, entry_id, user)
    fields = payload.model_dump(exclude_unset=True)

    if "food_id" in fields and fields["food_id"] is not None:
        await _get_visible_food(db, fields["food_id"], user)
        entry.food_id = fields["food_id"]
    if "entry_date" in fields and fields["entry_date"] is not None:
        entry.entry_date = fields["entry_date"]
    if "meal" in fields and fields["meal"] is not None:
        entry.meal = fields["meal"]
    if "quantity" in fields and fields["quantity"] is not None:
        entry.quantity = fields["quantity"]

    await db.flush()
    await db.refresh(entry, attribute_names=["food"])
    return DiaryEntryRead.model_validate(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one of the caller's Diary Entries."""
    entry = await _get_owned_entry(db, entry_id, user)
    await db.delete(entry)
    await db.flush()


# --------------------------------------------------------------------------- #
# Day view + history (totals via the pure core)
# --------------------------------------------------------------------------- #


def _entry_macros(entry: DiaryEntry) -> EntryMacros:
    """Build the pure-core input from an ORM entry (+ its loaded Food)."""
    food = entry.food
    return EntryMacros(
        meal=entry.meal,
        quantity=entry.quantity,
        calories=food.calories,
        protein_g=food.protein_g,
        carbs_g=food.carbs_g,
        fat_g=food.fat_g,
    )


def _macros_read(totals: MacroTotals) -> MacroTotalsRead:
    return MacroTotalsRead(
        calories=totals.calories,
        protein_g=totals.protein_g,
        carbs_g=totals.carbs_g,
        fat_g=totals.fat_g,
    )


@router.get("/diary", response_model=DiaryDayRead)
async def get_diary_day(
    date: dt.date | None = Query(
        default=None, description="The day to view (defaults to today)."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiaryDayRead:
    """The caller's diary for one day: the four Meal sections + the day total.

    Per-meal and day totals come from the pure :mod:`app.services.nutrition` core.
    Every Meal slot is present (zeroed when empty) so the day view renders all
    four sections.
    """
    day = date or dt.date.today()
    stmt = (
        select(DiaryEntry)
        .where(DiaryEntry.user_id == user.id, DiaryEntry.entry_date == day)
        .order_by(DiaryEntry.created_at)
    )
    entries = list((await db.execute(stmt)).scalars().all())

    totals = daily_totals(_entry_macros(e) for e in entries)
    entries_by_meal: dict[Meal, list[DiaryEntry]] = {m: [] for m in Meal}
    for e in entries:
        entries_by_meal[e.meal].append(e)

    sections = [
        MealSection(
            meal=meal,
            entries=[DiaryEntryRead.model_validate(e) for e in entries_by_meal[meal]],
            totals=_macros_read(totals.by_meal[meal]),
        )
        for meal in Meal
    ]
    return DiaryDayRead(
        entry_date=day, meals=sections, total=_macros_read(totals.total)
    )


@router.get("/history", response_model=list[DiaryDaySummary])
async def get_history(
    start: dt.date = Query(description="First day of the range (inclusive)."),
    end: dt.date = Query(description="Last day of the range (inclusive)."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DiaryDaySummary]:
    """Per-day macro totals over a date range, for the history charts.

    Only days with at least one entry appear, each with its own summed total
    (via the pure core). Scoped to the caller.
    """
    stmt = (
        select(DiaryEntry)
        .where(
            DiaryEntry.user_id == user.id,
            DiaryEntry.entry_date >= start,
            DiaryEntry.entry_date <= end,
        )
        .order_by(DiaryEntry.entry_date)
    )
    entries = list((await db.execute(stmt)).scalars().all())

    by_day: dict[dt.date, list[DiaryEntry]] = {}
    for e in entries:
        by_day.setdefault(e.entry_date, []).append(e)

    return [
        DiaryDaySummary(
            entry_date=day,
            total=_macros_read(daily_totals(_entry_macros(e) for e in day_entries).total),
        )
        for day, day_entries in sorted(by_day.items())
    ]
