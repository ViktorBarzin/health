"""Seed the shared Food catalog with a starter set of generic whole foods.

CONTEXT.md ("Food"): "An entry in the food catalog with per-serving macros — from
the Open Food Facts cache, the generic whole-foods seed, or user-created." This
module is the **generic whole-foods seed** — a small, hand-authored set of common
foods (chicken, egg, rice, banana, …) so a brand-new user can start logging a
Diary Entry immediately, before the Open Food Facts integration and barcode
search land in #22.

Like the Principles KB (and unlike the ~870-row vendored Exercise dataset), this
is a small hand-authored list, so it lives in code as :data:`GENERIC_FOODS`
rather than a vendored data file. Macros are **per serving** (one serving =
``serving_size`` of ``serving_unit``); reasonable reference values for common
foods, kept internally consistent with the Atwater factors (4/4/9 kcal per g of
protein/carb/fat) within rounding — the seed test guards that.

Seeding is idempotent: it upserts each Food keyed on its stable ``slug`` among
shared rows (``user_id IS NULL``), so re-running on every boot adds nothing
duplicated and flows corrections through. Custom (user-owned) Foods are never
touched. Invoked from ``entrypoint.sh`` after ``alembic upgrade head``, and
runnable manually via ``python -m app.services.seed_foods``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.food import Food

SOURCE_NAME = "generic"


@dataclass(frozen=True)
class FoodSeed:
    """One authored generic Food with its per-serving macros."""

    slug: str
    name: str
    serving_size: float
    serving_unit: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class SeedResult:
    """Outcome of one seed run, for logging and tests."""

    inserted: int
    updated: int
    total: int


# A sensible starter set of common whole foods. Per-serving macros are rounded
# reference values (USDA-style) kept Atwater-consistent (see module docstring +
# the seed test). Slugs are stable natural keys; "100g" foods use a 100 g
# serving, whole-unit foods use their natural unit ("egg", "slice", "medium").
GENERIC_FOODS: tuple[FoodSeed, ...] = (
    # --- Proteins ---
    FoodSeed("chicken-breast-cooked", "Chicken breast, cooked", 100, "g", 165, 31.0, 0.0, 3.6),
    FoodSeed("egg-large", "Egg, large", 1, "egg", 72, 6.3, 0.4, 4.8),
    FoodSeed("salmon-cooked", "Salmon, cooked", 100, "g", 206, 22.0, 0.0, 13.0),
    FoodSeed("ground-beef-85-cooked", "Ground beef, 85% lean, cooked", 100, "g", 250, 26.0, 0.0, 15.0),
    FoodSeed("canned-tuna-water", "Tuna, canned in water, drained", 100, "g", 116, 26.0, 0.0, 1.0),
    FoodSeed("greek-yogurt-nonfat", "Greek yogurt, nonfat, plain", 170, "g", 100, 17.0, 6.0, 0.7),
    FoodSeed("tofu-firm", "Tofu, firm", 100, "g", 144, 17.0, 3.0, 9.0),
    # --- Carbs / grains ---
    FoodSeed("white-rice-cooked", "White rice, cooked", 100, "g", 130, 2.7, 28.0, 0.3),
    FoodSeed("brown-rice-cooked", "Brown rice, cooked", 100, "g", 123, 2.7, 26.0, 1.0),
    FoodSeed("oats-rolled-dry", "Rolled oats, dry", 40, "g", 150, 5.0, 27.0, 2.5),
    FoodSeed("bread-whole-wheat", "Whole wheat bread", 1, "slice", 80, 4.0, 14.0, 1.1),
    FoodSeed("pasta-cooked", "Pasta, cooked", 100, "g", 158, 5.8, 31.0, 0.9),
    FoodSeed("potato-baked", "Potato, baked, with skin", 1, "medium", 161, 4.3, 37.0, 0.2),
    FoodSeed("sweet-potato-baked", "Sweet potato, baked", 1, "medium", 112, 2.0, 26.0, 0.1),
    # --- Fruit & veg ---
    FoodSeed("banana", "Banana", 1, "medium", 105, 1.3, 27.0, 0.4),
    FoodSeed("apple", "Apple", 1, "medium", 95, 0.5, 25.0, 0.3),
    FoodSeed("blueberries", "Blueberries", 100, "g", 57, 0.7, 14.0, 0.3),
    FoodSeed("broccoli-cooked", "Broccoli, cooked", 100, "g", 35, 2.4, 7.0, 0.4),
    FoodSeed("spinach-raw", "Spinach, raw", 100, "g", 23, 2.9, 3.6, 0.4),
    FoodSeed("avocado", "Avocado", 100, "g", 160, 2.0, 9.0, 15.0),
    # --- Fats / nuts / dairy ---
    FoodSeed("almonds", "Almonds", 28, "g", 164, 6.0, 6.0, 14.0),
    FoodSeed("peanut-butter", "Peanut butter", 32, "g", 188, 8.0, 6.0, 16.0),
    FoodSeed("olive-oil", "Olive oil", 1, "tbsp", 119, 0.0, 0.0, 13.5),
    FoodSeed("whole-milk", "Whole milk", 240, "ml", 149, 7.7, 12.0, 8.0),
    FoodSeed("cheddar-cheese", "Cheddar cheese", 28, "g", 113, 7.0, 0.4, 9.0),
)


def _apply_fields(food: Food, seed: FoodSeed) -> None:
    """Copy the scalar fields from a seed onto a shared Food row."""
    food.name = seed.name
    food.serving_size = seed.serving_size
    food.serving_unit = seed.serving_unit
    food.calories = seed.calories
    food.protein_g = seed.protein_g
    food.carbs_g = seed.carbs_g
    food.fat_g = seed.fat_g
    food.source = SOURCE_NAME
    food.brand = None
    food.off_id = None


async def seed_foods(
    session: AsyncSession, foods: tuple[FoodSeed, ...] | None = None
) -> SeedResult:
    """Upsert the shared generic Food catalog; return the tally.

    Keys on each Food's stable ``slug`` among shared rows (``user_id IS NULL``).
    Custom (non-NULL ``user_id``) Foods are never touched. Idempotent: a re-run
    updates existing rows in place and inserts nothing duplicated.
    """
    rows = foods if foods is not None else GENERIC_FOODS

    # One query for all existing shared rows keyed by slug — no per-record trip.
    result = await session.execute(select(Food).where(Food.user_id.is_(None)))
    by_slug: dict[str, Food] = {f.slug: f for f in result.scalars().all()}

    inserted = updated = 0
    for seed in rows:
        food = by_slug.get(seed.slug)
        if food is None:
            food = Food(slug=seed.slug, user_id=None)
            session.add(food)
            by_slug[seed.slug] = food
            inserted += 1
        else:
            updated += 1
        _apply_fields(food, seed)

    await session.commit()
    return SeedResult(inserted=inserted, updated=updated, total=len(rows))


async def _main() -> None:
    async with async_session() as session:
        result = await seed_foods(session)
    print(
        f"Seeded generic Food catalog: {result.inserted} inserted, "
        f"{result.updated} updated, {result.total} total."
    )


if __name__ == "__main__":
    asyncio.run(_main())
