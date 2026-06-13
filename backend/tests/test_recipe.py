"""Pure Recipe macro computation (no DB, no I/O).

CONTEXT.md ("Recipe"): "A user-defined Food composed of other Foods, with
computed per-serving macros." The per-serving macros of a Recipe are:

    Σ (ingredient per-serving macros × ingredient quantity)  ÷  yield servings

i.e. total the macros of all the ingredient Foods at their logged quantities,
then divide by how many servings the whole Recipe makes. This module is the
single PURE definition of that sum (mirrors ``services/nutrition.py`` for the
diary and ``services/volume.py`` for training); the DB/query layer feeds it
``IngredientMacros`` value objects and persists the result onto the Recipe's Food.
"""

import pytest

from app.services.recipe import (
    IngredientMacros,
    RecipeMacroError,
    compute_recipe_macros,
)


def _ing(quantity, calories, protein_g, carbs_g, fat_g):
    return IngredientMacros(
        quantity=quantity,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
    )


def test_sum_ingredients_divided_by_yield() -> None:
    # Recipe makes 4 servings from: 2× chicken (165/31/0/3.6 per serving) + 1.5×
    # rice (130/2.7/28/0.3). Totals: kcal 330+195=525; protein 62+4.05=66.05;
    # carbs 0+42=42; fat 7.2+0.45=7.65. Per serving = /4.
    macros = compute_recipe_macros(
        [
            _ing(2, 165, 31.0, 0.0, 3.6),
            _ing(1.5, 130, 2.7, 28.0, 0.3),
        ],
        yield_servings=4,
    )
    assert macros.calories == pytest.approx(525 / 4)
    assert macros.protein_g == pytest.approx(66.05 / 4)
    assert macros.carbs_g == pytest.approx(42.0 / 4)
    assert macros.fat_g == pytest.approx(7.65 / 4)


def test_single_ingredient_single_serving_is_identity() -> None:
    macros = compute_recipe_macros([_ing(1, 200, 10, 20, 5)], yield_servings=1)
    assert macros.calories == 200
    assert macros.protein_g == 10
    assert macros.carbs_g == 20
    assert macros.fat_g == 5


def test_one_serving_yields_the_full_total() -> None:
    # yield=1 → the per-serving macros are the whole recipe (edge case).
    macros = compute_recipe_macros(
        [_ing(2, 100, 5, 10, 2), _ing(1, 50, 1, 8, 0)],
        yield_servings=1,
    )
    assert macros.calories == 250  # 200 + 50
    assert macros.protein_g == 11  # 10 + 1


def test_editing_an_ingredient_changes_the_result() -> None:
    # The computation is a pure function of its inputs, so a changed ingredient
    # (the query layer re-reads the edited Food) yields different macros — this is
    # how "stays correct if an ingredient is edited" is honoured.
    before = compute_recipe_macros([_ing(1, 100, 10, 0, 0)], yield_servings=1)
    after = compute_recipe_macros([_ing(1, 150, 12, 0, 0)], yield_servings=1)
    assert before.calories == 100
    assert after.calories == 150
    assert after.protein_g == 12


def test_zero_yield_rejected() -> None:
    with pytest.raises(RecipeMacroError):
        compute_recipe_macros([_ing(1, 100, 10, 0, 0)], yield_servings=0)


def test_negative_yield_rejected() -> None:
    with pytest.raises(RecipeMacroError):
        compute_recipe_macros([_ing(1, 100, 10, 0, 0)], yield_servings=-2)


def test_no_ingredients_rejected() -> None:
    # A Recipe with no ingredients has no macros to compute — reject (the API
    # requires at least one ingredient).
    with pytest.raises(RecipeMacroError):
        compute_recipe_macros([], yield_servings=2)


def test_fractional_yield_allowed() -> None:
    # A non-integer yield is valid (e.g. a recipe that makes 2.5 servings).
    macros = compute_recipe_macros([_ing(1, 250, 0, 0, 0)], yield_servings=2.5)
    assert macros.calories == 100
