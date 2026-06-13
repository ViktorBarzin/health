"""Pure Recipe macro computation — Σ ingredients ÷ yield (#22).

CONTEXT.md ("Recipe"): "A user-defined Food composed of other Foods, with
computed per-serving macros." A Recipe's per-serving macros are the sum of its
ingredient Foods' macros (each at its logged quantity) divided by the number of
servings the whole Recipe yields:

    per-serving macro = Σ (ingredient.per_serving_macro × ingredient.quantity) / yield

This module is the **single, pure definition** of that arithmetic (no DB, no I/O)
— the same discipline as :mod:`app.services.nutrition` (the diary sum) and
:mod:`app.services.volume` (training). The query layer reads the ingredient Foods
into :class:`IngredientMacros` value objects, calls :func:`compute_recipe_macros`,
and writes the result onto the Recipe's backing Food (compute-on-write — see
:mod:`app.services.recipe_query`), so every downstream read (search, the diary,
daily totals) is a plain Food read and needs no Recipe awareness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class RecipeMacroError(ValueError):
    """Raised when a Recipe's macros can't be computed (bad yield / no ingredients)."""


@dataclass(frozen=True)
class IngredientMacros:
    """One ingredient's contribution: its quantity and the Food's per-serving macros.

    ``quantity`` is the number of servings of the ingredient Food used in the
    whole Recipe (same "number of servings" semantics as a Diary Entry).
    """

    quantity: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class RecipeMacros:
    """The computed **per-serving** macros of a Recipe."""

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


def compute_recipe_macros(
    ingredients: Sequence[IngredientMacros], *, yield_servings: float
) -> RecipeMacros:
    """Compute a Recipe's per-serving macros: Σ (ingredient macros) ÷ yield.

    Raises :class:`RecipeMacroError` if ``yield_servings`` is not positive or
    there are no ingredients — both are nonsensical inputs the API forbids, and
    dividing by a non-positive yield would produce garbage rather than an honest
    "can't compute".
    """
    if yield_servings <= 0:
        raise RecipeMacroError("yield_servings must be positive")
    if not ingredients:
        raise RecipeMacroError("a Recipe needs at least one ingredient")

    calories = protein = carbs = fat = 0.0
    for ing in ingredients:
        calories += ing.calories * ing.quantity
        protein += ing.protein_g * ing.quantity
        carbs += ing.carbs_g * ing.quantity
        fat += ing.fat_g * ing.quantity

    return RecipeMacros(
        calories=calories / yield_servings,
        protein_g=protein / yield_servings,
        carbs_g=carbs / yield_servings,
        fat_g=fat / yield_servings,
    )
