"""Recipe DB glue: create/edit/delete + compute-on-write + ingredient-edit recompute.

DB-backed (real Postgres). A Recipe is a Food (``source='recipe'``) plus an
ingredient list; its per-serving macros are computed (Σ ingredient macros ÷ yield)
and **stored on the backing Food** at write time. These tests pin:

* creating a Recipe writes a ``source='recipe'`` Food owned by the user with the
  computed per-serving macros, and the ingredient rows;
* a Recipe is loggable to the diary exactly like a Food (its Food id is a normal
  Food id) — covered end-to-end in the API test, here we assert the Food exists;
* editing the Recipe (yield / ingredients) recomputes and re-stores the macros;
* editing an **ingredient Food** recomputes every Recipe that uses it
  (compute-on-write fan-out — the "stays correct if an ingredient is edited" rule);
* ingredient Foods must be visible to the owner (no logging another user's Food);
* deleting a Recipe removes its backing Food and ingredient rows.
"""

import pytest
from sqlalchemy import func, select

from app.models.food import Food
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.services.recipe_query import (
    RecipeIngredientInput,
    RecipeVisibilityError,
    create_recipe,
    delete_recipe,
    recompute_recipes_using_food,
    update_recipe,
)


async def _user(db, email):
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _food(db, name, *, user_id=None, calories=100, protein_g=10, carbs_g=5, fat_g=2):
    import uuid

    f = Food(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        serving_size=100,
        serving_unit="g",
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        source="generic" if user_id is None else "custom",
    )
    db.add(f)
    await db.flush()
    return f


async def test_create_recipe_writes_food_with_computed_macros(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    chicken = await _food(db_session, "Chicken", calories=165, protein_g=31, carbs_g=0, fat_g=3.6)
    rice = await _food(db_session, "Rice", calories=130, protein_g=2.7, carbs_g=28, fat_g=0.3)

    recipe = await create_recipe(
        db_session,
        user=alice,
        name="Chicken & Rice Bowl",
        yield_servings=4,
        ingredients=[
            RecipeIngredientInput(food_id=chicken.id, quantity=2),
            RecipeIngredientInput(food_id=rice.id, quantity=1.5),
        ],
    )
    await db_session.flush()

    food = (await db_session.execute(select(Food).where(Food.id == recipe.food_id))).scalar_one()
    assert food.source == "recipe"
    assert food.user_id == alice.id
    assert food.name == "Chicken & Rice Bowl"
    # Totals: kcal 330+195=525 /4; protein 62+4.05=66.05 /4.
    assert food.calories == pytest.approx(525 / 4)
    assert food.protein_g == pytest.approx(66.05 / 4)
    # One serving of a Recipe is "1 serving".
    assert food.serving_size == 1
    assert food.serving_unit == "serving"

    # Two ingredient rows persisted.
    n = (await db_session.execute(
        select(func.count()).select_from(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
    )).scalar()
    assert n == 2


async def test_recipe_requires_visible_ingredients(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    bobs_food = await _food(db_session, "Bob's Secret", user_id=bob.id)

    with pytest.raises(RecipeVisibilityError):
        await create_recipe(
            db_session,
            user=alice,
            name="Stolen Recipe",
            yield_servings=1,
            ingredients=[RecipeIngredientInput(food_id=bobs_food.id, quantity=1)],
        )


async def test_recipe_can_use_shared_and_own_foods(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    shared = await _food(db_session, "Shared Oats")
    mine = await _food(db_session, "My Protein Powder", user_id=alice.id, calories=120, protein_g=24, carbs_g=3, fat_g=1)

    recipe = await create_recipe(
        db_session,
        user=alice,
        name="Overnight Oats",
        yield_servings=1,
        ingredients=[
            RecipeIngredientInput(food_id=shared.id, quantity=1),
            RecipeIngredientInput(food_id=mine.id, quantity=1),
        ],
    )
    await db_session.flush()
    food = (await db_session.execute(select(Food).where(Food.id == recipe.food_id))).scalar_one()
    assert food.calories == 220  # 100 + 120, yield 1


async def test_update_recipe_recomputes_macros(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    a = await _food(db_session, "A", calories=100, protein_g=10, carbs_g=0, fat_g=0)
    b = await _food(db_session, "B", calories=200, protein_g=20, carbs_g=0, fat_g=0)
    recipe = await create_recipe(
        db_session, user=alice, name="R", yield_servings=1,
        ingredients=[RecipeIngredientInput(food_id=a.id, quantity=1)],
    )
    await db_session.flush()

    # Change yield to 2 and add ingredient b → totals (100+200)=300 /2 = 150.
    await update_recipe(
        db_session, recipe=recipe, user=alice, name="R2", yield_servings=2,
        ingredients=[
            RecipeIngredientInput(food_id=a.id, quantity=1),
            RecipeIngredientInput(food_id=b.id, quantity=1),
        ],
    )
    await db_session.flush()
    food = (await db_session.execute(select(Food).where(Food.id == recipe.food_id))).scalar_one()
    assert food.name == "R2"
    assert food.calories == 150
    assert food.protein_g == 15  # (10+20)/2


async def test_editing_ingredient_food_recomputes_dependent_recipes(db_session) -> None:
    # The cardinal "stays correct if an ingredient is edited" rule via the
    # compute-on-write fan-out: edit the ingredient Food, recompute its Recipes.
    alice = await _user(db_session, "alice@example.com")
    ing = await _food(db_session, "Flour", calories=100, protein_g=3, carbs_g=20, fat_g=1)
    recipe = await create_recipe(
        db_session, user=alice, name="Bread", yield_servings=2,
        ingredients=[RecipeIngredientInput(food_id=ing.id, quantity=4)],
    )
    await db_session.flush()
    food = (await db_session.execute(select(Food).where(Food.id == recipe.food_id))).scalar_one()
    assert food.calories == 200  # 100*4 / 2

    # The ingredient Food's macros change (e.g. a correction).
    ing.calories = 150
    await db_session.flush()
    n = await recompute_recipes_using_food(db_session, ing.id)
    await db_session.flush()
    assert n == 1
    await db_session.refresh(food)
    assert food.calories == 300  # 150*4 / 2 — reflects the edit


async def test_delete_recipe_removes_food_and_ingredients(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    a = await _food(db_session, "A")
    recipe = await create_recipe(
        db_session, user=alice, name="R", yield_servings=1,
        ingredients=[RecipeIngredientInput(food_id=a.id, quantity=1)],
    )
    await db_session.flush()
    food_id = recipe.food_id

    await delete_recipe(db_session, recipe)
    await db_session.flush()

    # Recipe, its backing Food, and ingredient rows are gone; the ingredient Food
    # 'A' survives (RESTRICT only blocks deleting an in-use Food, not the Recipe).
    assert (await db_session.execute(select(Food).where(Food.id == food_id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(Recipe).where(Recipe.id == recipe.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(Food).where(Food.id == a.id))).scalar_one_or_none() is not None
