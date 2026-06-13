"""Recipe DB glue — create/edit/delete + compute-on-write (#22).

A **Recipe** is a Food (``source='recipe'``) composed of other Foods. This module
is the persistence layer between the API and the pure
:func:`app.services.recipe.compute_recipe_macros` core:

* :func:`create_recipe` — writes the backing Food (source='recipe', owned by the
  user) + the ingredient rows, and stores the **computed** per-serving macros on
  the Food. Ingredient Foods must be visible to the owner (global ∪ own), else
  :class:`RecipeVisibilityError` (no logging another user's private Food).
* :func:`update_recipe` — replaces the name/yield/ingredients and recomputes.
* :func:`delete_recipe` — removes the Recipe; the backing Food cascades away.
* :func:`recompute_recipes_using_food` — the **compute-on-write fan-out**: when an
  ingredient Food is edited, every Recipe that uses it is recomputed so its stored
  macros stay correct (the CONTEXT.md "stays correct if an ingredient is edited"
  rule). Bounded and explicit — cheaper than pushing a join+sum into every Food
  read (compute-on-read), which is why this slice chose compute-on-write.

Because a Recipe IS a Food, everything downstream (catalog search, the diary,
daily totals, Export) treats it as an ordinary Food with no Recipe-awareness.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.food import Food
from app.models.recipe import Recipe, RecipeIngredient
from app.models.user import User
from app.services.recipe import IngredientMacros, compute_recipe_macros

# A Recipe's backing Food has a one-serving unit: "1 serving" of the Recipe, whose
# macros are the computed per-serving values. Logging quantity 2 = two servings.
RECIPE_SOURCE = "recipe"
_RECIPE_SERVING_SIZE = 1.0
_RECIPE_SERVING_UNIT = "serving"


class RecipeVisibilityError(ValueError):
    """Raised when a Recipe references a Food the owner can't see (no leak)."""


@dataclass(frozen=True)
class RecipeIngredientInput:
    """One requested ingredient: a Food id and a quantity (servings of it)."""

    food_id: uuid.UUID
    quantity: float


def _recipe_slug(name: str) -> str:
    """A readable, unique-per-user natural key for a Recipe's backing Food.

    Mirrors the custom-Exercise slug: ``recipe-<name>-<rand>``. Per-user
    uniqueness is enforced by ``uq_food_user_slug``; the random suffix avoids a
    collision when a user makes two recipes with the same name.
    """
    cleaned = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return f"recipe-{cleaned or 'recipe'}-{uuid.uuid4().hex[:8]}"


async def _load_visible_ingredient_foods(
    db: AsyncSession, user: User, ingredients: list[RecipeIngredientInput]
) -> dict[uuid.UUID, Food]:
    """Load the ingredient Foods, asserting each is visible to the owner.

    Visible = shared (``user_id IS NULL``) ∪ the user's own — the same rule as the
    diary/catalog. A referenced Food that isn't visible raises
    :class:`RecipeVisibilityError`.
    """
    ids = [ing.food_id for ing in ingredients]
    if not ids:
        return {}
    stmt = select(Food).where(
        Food.id.in_(ids),
        or_(Food.user_id.is_(None), Food.user_id == user.id),
    )
    found = {f.id: f for f in (await db.execute(stmt)).scalars().all()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise RecipeVisibilityError(f"ingredient Food not found: {missing[0]}")
    return found


def _ingredient_macros(
    ingredients: list[RecipeIngredientInput], foods: dict[uuid.UUID, Food]
) -> list[IngredientMacros]:
    """Build the pure-core inputs from the requested ingredients + their Foods."""
    return [
        IngredientMacros(
            quantity=ing.quantity,
            calories=foods[ing.food_id].calories,
            protein_g=foods[ing.food_id].protein_g,
            carbs_g=foods[ing.food_id].carbs_g,
            fat_g=foods[ing.food_id].fat_g,
        )
        for ing in ingredients
    ]


def _apply_macros_to_food(food: Food, ingredients, foods, *, yield_servings) -> None:
    """Compute and store the Recipe's per-serving macros on its backing Food."""
    macros = compute_recipe_macros(
        _ingredient_macros(ingredients, foods), yield_servings=yield_servings
    )
    food.calories = macros.calories
    food.protein_g = macros.protein_g
    food.carbs_g = macros.carbs_g
    food.fat_g = macros.fat_g


async def create_recipe(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    yield_servings: float,
    ingredients: list[RecipeIngredientInput],
) -> Recipe:
    """Create a Recipe: its backing Food + ingredients + computed macros.

    Raises :class:`RecipeVisibilityError` if an ingredient Food isn't visible to
    the owner, and :class:`app.services.recipe.RecipeMacroError` on a bad yield /
    no ingredients (the API validates first, so these are belt-and-suspenders).
    """
    foods = await _load_visible_ingredient_foods(db, user, ingredients)

    food = Food(
        user_id=user.id,
        slug=_recipe_slug(name),
        name=name,
        brand=None,
        serving_size=_RECIPE_SERVING_SIZE,
        serving_unit=_RECIPE_SERVING_UNIT,
        calories=0.0,
        protein_g=0.0,
        carbs_g=0.0,
        fat_g=0.0,
        source=RECIPE_SOURCE,
        off_id=None,
    )
    _apply_macros_to_food(food, ingredients, foods, yield_servings=yield_servings)
    db.add(food)
    await db.flush()

    recipe = Recipe(user_id=user.id, food_id=food.id, yield_servings=yield_servings)
    for position, ing in enumerate(ingredients):
        recipe.ingredients.append(
            RecipeIngredient(food_id=ing.food_id, quantity=ing.quantity, position=position)
        )
    db.add(recipe)
    await db.flush()
    return recipe


async def update_recipe(
    db: AsyncSession,
    *,
    recipe: Recipe,
    user: User,
    name: str,
    yield_servings: float,
    ingredients: list[RecipeIngredientInput],
) -> Recipe:
    """Replace a Recipe's name/yield/ingredients and recompute its Food's macros."""
    foods = await _load_visible_ingredient_foods(db, user, ingredients)

    food = (
        await db.execute(select(Food).where(Food.id == recipe.food_id))
    ).scalar_one()
    food.name = name
    recipe.yield_servings = yield_servings

    # Replace the ingredient set wholesale (delete-orphan handles removals).
    recipe.ingredients.clear()
    for position, ing in enumerate(ingredients):
        recipe.ingredients.append(
            RecipeIngredient(food_id=ing.food_id, quantity=ing.quantity, position=position)
        )

    _apply_macros_to_food(food, ingredients, foods, yield_servings=yield_servings)
    await db.flush()
    return recipe


async def delete_recipe(db: AsyncSession, recipe: Recipe) -> None:
    """Delete a Recipe and its backing Food (ingredient rows cascade).

    The backing Food is deleted too (the Recipe owns its lifecycle). If the
    backing Food is referenced by a Diary Entry, the entry's RESTRICT FK will
    raise — the API turns that into a clear 409 rather than silently breaking a
    logged day.
    """
    food_id = recipe.food_id
    await db.delete(recipe)
    await db.flush()
    food = (await db.execute(select(Food).where(Food.id == food_id))).scalar_one_or_none()
    if food is not None:
        await db.delete(food)
        await db.flush()


async def recompute_recipes_using_food(db: AsyncSession, food_id: uuid.UUID) -> int:
    """Recompute every Recipe that uses ``food_id`` as an ingredient; return count.

    The compute-on-write fan-out: called after an ingredient Food's macros change
    (a custom-Food edit) so dependent Recipes' stored macros stay correct. Returns
    how many Recipes were recomputed.
    """
    recipe_ids = (
        await db.execute(
            select(RecipeIngredient.recipe_id)
            .where(RecipeIngredient.food_id == food_id)
            .distinct()
        )
    ).scalars().all()
    if not recipe_ids:
        return 0

    recipes = (
        await db.execute(select(Recipe).where(Recipe.id.in_(recipe_ids)))
    ).scalars().all()

    for recipe in recipes:
        # Reload with ingredients+foods eagerly materialised (the recipe may have
        # been created earlier in this same session, where the freshly-appended
        # ingredient rows have no loaded ``food``).
        loaded = await load_recipe_with_ingredients(db, recipe.id)
        assert loaded is not None  # we just selected it by id
        foods = {ing.food_id: ing.food for ing in loaded.ingredients}
        inputs = [
            RecipeIngredientInput(food_id=ing.food_id, quantity=ing.quantity)
            for ing in loaded.ingredients
        ]
        food = (
            await db.execute(select(Food).where(Food.id == loaded.food_id))
        ).scalar_one()
        _apply_macros_to_food(
            food, inputs, foods, yield_servings=loaded.yield_servings
        )
    await db.flush()
    return len(recipes)


async def load_recipe_with_ingredients(
    db: AsyncSession, recipe_id: uuid.UUID, *, user_id: int | None = None
) -> Recipe | None:
    """Load one Recipe with its ingredients AND their Foods materialised.

    Uses ``selectinload`` + ``populate_existing`` so the relationship is read from
    the DB even for a Recipe just created/edited in this session (whose in-memory
    ingredient rows have no loaded ``food`` yet — the lazy='selectin' relationship
    only fires on a query load, not on freshly-constructed objects). Optionally
    scoped to ``user_id`` (the owner). Returns None if not found / not owned.
    """
    stmt = (
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(selectinload(Recipe.ingredients).selectinload(RecipeIngredient.food))
        .execution_options(populate_existing=True)
    )
    if user_id is not None:
        stmt = stmt.where(Recipe.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()
