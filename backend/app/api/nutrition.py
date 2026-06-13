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
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.diary_entry import DiaryEntry, Meal
from app.models.food import Food
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.schemas.nutrition import (
    BudgetRead,
    DiaryDayRead,
    DiaryDaySummary,
    DiaryEntryCreate,
    DiaryEntryRead,
    DiaryEntryUpdate,
    FoodCreate,
    FoodRead,
    FoodUpdate,
    MacroTotalsRead,
    MealSection,
    RecipeCreate,
    RecipeIngredientRead,
    RecipeRead,
    RecipeUpdate,
    WeightTrendRead,
)
from app.services.budget_query import budget_for_user
from app.services.nutrition import EntryMacros, MacroTotals, daily_totals
from app.services.off import is_valid_barcode
from app.services.off_lookup import lookup_barcode
from app.services.recipe import RecipeMacroError
from app.services.recipe_query import (
    RecipeIngredientInput,
    RecipeVisibilityError,
    create_recipe,
    delete_recipe,
    load_recipe_with_ingredients,
    recompute_recipes_using_food,
    update_recipe,
)

# A custom Food the user owns — the only kind a user may edit/delete (shared
# generic/OFF rows and recipe-backed Foods are managed by the system / the Recipe).
CUSTOM_SOURCE = "custom"

router = APIRouter()


def _visible_food_filter(user_id: int):
    """The catalog visibility rule: shared (NULL user_id) ∪ the caller's own."""
    return or_(Food.user_id.is_(None), Food.user_id == user_id)


def _custom_food_slug(name: str) -> str:
    """A readable, unique-per-user natural key for a custom Food.

    Mirrors the custom-Exercise slug; per-user uniqueness is enforced by
    ``uq_food_user_slug`` and the random suffix avoids same-name collisions.
    """
    cleaned = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return f"custom-{cleaned or 'food'}-{uuid.uuid4().hex[:8]}"


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
# Barcode → Open Food Facts → cached Food (#22)
# --------------------------------------------------------------------------- #


@router.get("/barcode/{code}", response_model=FoodRead)
async def resolve_barcode(
    code: str = Path(description="A retail barcode (EAN/UPC, digits only)."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FoodRead:
    """Resolve a scanned barcode to a Food via Open Food Facts (cache-first).

    The first scan of a barcode fetches OFF, maps the per-100g macros into a
    shared ``source='off'`` Food, and caches it; repeat scans hit the cache (no
    network). A barcode OFF doesn't know, or whose macros are incomplete, is a
    404 — the client falls back to manual entry / custom Food (never a garbage
    Food). Obvious junk (non-digit) input is rejected up front (422) without a
    network call.
    """
    if not is_valid_barcode(code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Not a valid barcode",
        )
    food = await lookup_barcode(db, code)
    if food is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No product found for this barcode",
        )
    return FoodRead.model_validate(food)


# --------------------------------------------------------------------------- #
# Custom Foods (#22) — a user's own private Food
# --------------------------------------------------------------------------- #


async def _get_own_custom_food(
    db: AsyncSession, food_id: uuid.UUID, user: User
) -> Food:
    """Load one of the caller's own custom Foods, or 404.

    Only ``source='custom'`` Foods owned by the caller are editable/deletable;
    shared (generic/OFF) and recipe-backed Foods are not the user's to mutate
    here, so they 404 (no existence leak, and recipe Foods are managed via the
    Recipe endpoints).
    """
    stmt = select(Food).where(
        Food.id == food_id,
        Food.user_id == user.id,
        Food.source == CUSTOM_SOURCE,
    )
    food = (await db.execute(stmt)).scalar_one_or_none()
    if food is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Custom food not found"
        )
    return food


@router.post(
    "/foods", response_model=FoodRead, status_code=status.HTTP_201_CREATED
)
async def create_custom_food(
    payload: FoodCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FoodRead:
    """Create a custom (private) Food owned by the caller (per-serving macros)."""
    brand = payload.brand.strip() if payload.brand and payload.brand.strip() else None
    food = Food(
        user_id=user.id,
        slug=_custom_food_slug(payload.name),
        name=payload.name,
        brand=brand,
        serving_size=payload.serving_size,
        serving_unit=payload.serving_unit,
        calories=payload.calories,
        protein_g=payload.protein_g,
        carbs_g=payload.carbs_g,
        fat_g=payload.fat_g,
        source=CUSTOM_SOURCE,
    )
    db.add(food)
    await db.flush()
    await db.refresh(food)
    return FoodRead.model_validate(food)


@router.patch("/foods/{food_id}", response_model=FoodRead)
async def update_custom_food(
    food_id: uuid.UUID,
    payload: FoodUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FoodRead:
    """Edit one of the caller's own custom Foods (only sent fields change).

    Editing a custom Food's macros recomputes any Recipe that uses it as an
    ingredient, so dependent Recipes' stored per-serving macros stay correct.
    """
    food = await _get_own_custom_food(db, food_id, user)
    fields = payload.model_dump(exclude_unset=True)
    for attr in (
        "name", "serving_size", "serving_unit",
        "calories", "protein_g", "carbs_g", "fat_g",
    ):
        if attr in fields and fields[attr] is not None:
            setattr(food, attr, fields[attr])
    if "brand" in fields:
        brand = fields["brand"]
        food.brand = brand.strip() if isinstance(brand, str) and brand.strip() else None

    await db.flush()
    # Compute-on-write fan-out: any Recipe using this Food recomputes its macros.
    await recompute_recipes_using_food(db, food.id)
    await db.refresh(food)
    return FoodRead.model_validate(food)


@router.delete("/foods/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_food(
    food_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one of the caller's own custom Foods.

    A Food still referenced by a Diary Entry or a Recipe ingredient can't be
    deleted (the RESTRICT FKs) — that surfaces as a 409 rather than a 500, so the
    client can tell the user to remove the references first.
    """
    food = await _get_own_custom_food(db, food_id, user)
    await db.delete(food)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This food is in use (a diary entry or recipe) and can't be deleted.",
        )


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


# --------------------------------------------------------------------------- #
# Budget (#23) — the Goal-driven, self-calibrating daily calorie/macro target
# --------------------------------------------------------------------------- #


@router.get("/budget", response_model=BudgetRead)
async def get_budget(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetRead:
    """Today's Budget for the caller: the Goal-driven target + the weight trend.

    The Budget is derived from the user's Goal (their active Program's goal, or
    ``maintain`` by default) and their measured energy expenditure — TDEE reconciled
    adaptively from logged intake against the de-noised weight trend
    (``method='adaptive'``), or a labelled bodyweight estimate when there isn't
    enough data to measure it (``method='estimated'``). With no bodyweight history
    at all it reports ``insufficient_data`` honestly rather than a fabricated
    number. All maths is in the pure cores (:mod:`app.services.budget`,
    :mod:`app.services.weight_trend`); this only injects request time.
    """
    now = dt.datetime.now(timezone.utc)
    result = await budget_for_user(db, user.id, now=now)
    budget, trend = result.budget, result.trend
    return BudgetRead(
        insufficient_data=budget.insufficient_data,
        method=budget.method,
        goal=result.goal,
        tdee_kcal=budget.tdee_kcal,
        target_kcal=budget.target_kcal,
        protein_g=budget.protein_g,
        carbs_g=budget.carbs_g,
        fat_g=budget.fat_g,
        target_rate_kg_per_week=budget.target_rate_kg_per_week,
        intake_days=budget.intake_days,
        trend=WeightTrendRead(
            insufficient_data=trend.insufficient_data,
            true_weight_kg=trend.true_weight_kg,
            rate_kg_per_week=trend.rate_kg_per_week,
            rate_pct_per_week=trend.rate_pct_per_week,
            n_samples=trend.n_samples,
        ),
    )


# --------------------------------------------------------------------------- #
# Recipes (#22) — a user-defined Food composed of other Foods
# --------------------------------------------------------------------------- #


def _recipe_read(recipe: Recipe, food: Food) -> RecipeRead:
    """Build the API view of a Recipe from its ORM row + backing Food.

    The Recipe's per-serving macros are read off the backing Food (computed at
    write time). Each ingredient row reports its contribution at its quantity
    (the ingredient Food's per-serving macros × quantity).
    """
    ingredients = [
        RecipeIngredientRead(
            food_id=ing.food_id,
            food_name=ing.food.name,
            quantity=ing.quantity,
            serving_size=ing.food.serving_size,
            serving_unit=ing.food.serving_unit,
            calories=ing.food.calories * ing.quantity,
            protein_g=ing.food.protein_g * ing.quantity,
            carbs_g=ing.food.carbs_g * ing.quantity,
            fat_g=ing.food.fat_g * ing.quantity,
        )
        for ing in recipe.ingredients
    ]
    # Macros are the exact stored per-serving values (the Food is the source of
    # truth); the client formats them for display (1dp), like FoodRead.
    return RecipeRead(
        id=recipe.id,
        food_id=recipe.food_id,
        name=food.name,
        yield_servings=recipe.yield_servings,
        calories=food.calories,
        protein_g=food.protein_g,
        carbs_g=food.carbs_g,
        fat_g=food.fat_g,
        ingredients=ingredients,
    )


async def _get_owned_recipe(
    db: AsyncSession, recipe_id: uuid.UUID, user: User
) -> Recipe:
    """Load a Recipe owned by the caller (ingredients + their Foods loaded), or 404."""
    recipe = await load_recipe_with_ingredients(db, recipe_id, user_id=user.id)
    if recipe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found"
        )
    return recipe


async def _recipe_food(db: AsyncSession, recipe: Recipe) -> Food:
    """The backing Food for a Recipe (holds the computed per-serving macros)."""
    return (
        await db.execute(select(Food).where(Food.id == recipe.food_id))
    ).scalar_one()


def _ingredient_inputs(payload) -> list[RecipeIngredientInput]:
    return [
        RecipeIngredientInput(food_id=i.food_id, quantity=i.quantity)
        for i in payload.ingredients
    ]


@router.get("/recipes", response_model=list[RecipeRead])
async def list_recipes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RecipeRead]:
    """List the caller's own Recipes (each with its computed macros + ingredients)."""
    recipes = (
        await db.execute(
            select(Recipe)
            .where(Recipe.user_id == user.id)
            .options(
                selectinload(Recipe.ingredients).selectinload(RecipeIngredient.food)
            )
            .order_by(Recipe.id)
        )
    ).scalars().all()
    if not recipes:
        return []
    foods = {
        f.id: f
        for f in (
            await db.execute(
                select(Food).where(Food.id.in_([r.food_id for r in recipes]))
            )
        ).scalars().all()
    }
    return [_recipe_read(r, foods[r.food_id]) for r in recipes]


@router.post(
    "/recipes", response_model=RecipeRead, status_code=status.HTTP_201_CREATED
)
async def create_recipe_endpoint(
    payload: RecipeCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecipeRead:
    """Create a Recipe: name + yield + ingredients → a loggable, computed Food.

    Per-serving macros are computed (Σ ingredient macros ÷ yield). An ingredient
    Food not visible to the caller is a 404 (no leak of another user's Food).
    """
    try:
        recipe = await create_recipe(
            db,
            user=user,
            name=payload.name,
            yield_servings=payload.yield_servings,
            ingredients=_ingredient_inputs(payload),
        )
    except RecipeVisibilityError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="An ingredient food was not found",
        )
    except RecipeMacroError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    # Reload so the ingredients' Foods are materialised for the response.
    loaded = await _get_owned_recipe(db, recipe.id, user)
    food = await _recipe_food(db, loaded)
    return _recipe_read(loaded, food)


@router.get("/recipes/{recipe_id}", response_model=RecipeRead)
async def get_recipe(
    recipe_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecipeRead:
    """Fetch one of the caller's Recipes."""
    recipe = await _get_owned_recipe(db, recipe_id, user)
    food = await _recipe_food(db, recipe)
    return _recipe_read(recipe, food)


@router.patch("/recipes/{recipe_id}", response_model=RecipeRead)
async def update_recipe_endpoint(
    recipe_id: uuid.UUID,
    payload: RecipeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecipeRead:
    """Replace a Recipe's name/yield/ingredients; recomputes its per-serving macros."""
    recipe = await _get_owned_recipe(db, recipe_id, user)
    try:
        await update_recipe(
            db,
            recipe=recipe,
            user=user,
            name=payload.name,
            yield_servings=payload.yield_servings,
            ingredients=_ingredient_inputs(payload),
        )
    except RecipeVisibilityError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="An ingredient food was not found",
        )
    except RecipeMacroError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    loaded = await _get_owned_recipe(db, recipe.id, user)
    food = await _recipe_food(db, loaded)
    return _recipe_read(loaded, food)


@router.delete("/recipes/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe_endpoint(
    recipe_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one of the caller's Recipes (its backing Food is removed too).

    If the Recipe's backing Food is still logged in the diary, the RESTRICT FK
    surfaces as a 409 rather than a 500 — remove the diary entries first.
    """
    recipe = await _get_owned_recipe(db, recipe_id, user)
    try:
        await delete_recipe(db, recipe)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This recipe is logged in your diary and can't be deleted.",
        )
