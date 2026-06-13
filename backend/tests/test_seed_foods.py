"""Generic whole-foods seed contract.

The seed upserts the shared (global) Food catalog of common whole foods and must
be idempotent — re-running on every boot adds no duplicates, flows changed
fields, and never touches users' custom Foods (#22). The data is hand-authored
in code (like the Principles KB), keyed on a stable ``slug``.
"""

from sqlalchemy import func, select

from app.models.food import Food
from app.models.user import User
from app.services.seed_foods import (
    GENERIC_FOODS,
    SOURCE_NAME,
    FoodSeed,
    seed_foods,
)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


_FIXTURE = (
    FoodSeed(
        slug="chicken-breast-cooked",
        name="Chicken breast, cooked",
        serving_size=100,
        serving_unit="g",
        calories=165,
        protein_g=31,
        carbs_g=0,
        fat_g=3.6,
    ),
    FoodSeed(
        slug="egg-large",
        name="Egg, large",
        serving_size=1,
        serving_unit="egg",
        calories=72,
        protein_g=6.3,
        carbs_g=0.4,
        fat_g=4.8,
    ),
)


async def test_seed_inserts_global_foods(db_session) -> None:
    result = await seed_foods(db_session, _FIXTURE)

    assert result.inserted == 2
    assert result.updated == 0
    assert await _count(db_session, Food) == 2

    chicken = (
        await db_session.execute(
            select(Food).where(Food.slug == "chicken-breast-cooked")
        )
    ).scalar_one()
    assert chicken.user_id is None  # shared catalog row
    assert chicken.source == SOURCE_NAME
    assert chicken.is_custom is False
    assert chicken.serving_size == 100
    assert chicken.serving_unit == "g"
    assert chicken.calories == 165
    assert chicken.protein_g == 31


async def test_seed_is_idempotent_no_duplicates(db_session) -> None:
    first = await seed_foods(db_session, _FIXTURE)
    after_first = await _count(db_session, Food)

    second = await seed_foods(db_session, _FIXTURE)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 2
    assert await _count(db_session, Food) == after_first == 2


async def test_reseed_updates_changed_macros(db_session) -> None:
    await seed_foods(db_session, _FIXTURE)

    revised = (
        FoodSeed(
            slug="chicken-breast-cooked",
            name="Chicken breast, cooked",
            serving_size=100,
            serving_unit="g",
            calories=170,  # corrected
            protein_g=32,
            carbs_g=0,
            fat_g=3.6,
        ),
        _FIXTURE[1],
    )
    result = await seed_foods(db_session, revised)
    assert result.inserted == 0
    assert result.updated == 2

    chicken = (
        await db_session.execute(
            select(Food).where(Food.slug == "chicken-breast-cooked")
        )
    ).scalar_one()
    assert chicken.calories == 170
    assert chicken.protein_g == 32


async def test_seed_leaves_custom_foods_untouched(db_session) -> None:
    user = User(email="eater@example.com")
    db_session.add(user)
    await db_session.flush()

    custom = Food(
        slug="my-protein-shake",
        name="My Protein Shake",
        user_id=user.id,
        serving_size=1,
        serving_unit="scoop",
        calories=120,
        protein_g=24,
        carbs_g=3,
        fat_g=1,
        source="custom",
    )
    db_session.add(custom)
    await db_session.flush()

    result = await seed_foods(db_session, _FIXTURE)

    # Seed only manages shared rows; the custom one is neither updated nor counted.
    assert result.inserted == 2
    assert result.updated == 0
    still = (
        await db_session.execute(select(Food).where(Food.id == custom.id))
    ).scalar_one()
    assert still.user_id == user.id
    assert still.name == "My Protein Shake"
    assert await _count(db_session, Food) == 3  # 2 shared + 1 custom


# --------------------------------------------------------------------------- #
# The authored catalog content itself.
# --------------------------------------------------------------------------- #


async def test_real_catalog_seeds_a_sensible_starter_set(db_session) -> None:
    result = await seed_foods(db_session)  # the real GENERIC_FOODS
    assert result.inserted == len(GENERIC_FOODS)
    assert result.total == len(GENERIC_FOODS)
    # A sensible starter set of common whole foods.
    assert len(GENERIC_FOODS) >= 15

    # Idempotent on the real content too.
    again = await seed_foods(db_session)
    assert again.inserted == 0
    assert await _count(db_session, Food) == len(GENERIC_FOODS)


def test_authored_foods_have_valid_macros_and_unique_slugs() -> None:
    """Every generic Food carries sane per-serving macros and a unique slug."""
    slugs = [f.slug for f in GENERIC_FOODS]
    assert len(slugs) == len(set(slugs)), "duplicate slug in GENERIC_FOODS"
    for f in GENERIC_FOODS:
        assert f.name and f.slug and f.serving_unit
        assert f.serving_size > 0
        # Macros are non-negative.
        assert f.calories >= 0 and f.protein_g >= 0 and f.carbs_g >= 0 and f.fat_g >= 0
        # Calories are roughly consistent with the macronutrients (4/4/9 kcal/g),
        # within a generous tolerance for rounding and fibre/alcohol quirks.
        atwater = 4 * f.protein_g + 4 * f.carbs_g + 9 * f.fat_g
        assert abs(atwater - f.calories) <= max(40, 0.30 * f.calories + 1), (
            f"{f.slug}: stated {f.calories} kcal vs Atwater {atwater:.0f}"
        )
