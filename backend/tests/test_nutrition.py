"""Pure macro-totalling core — the MyFitnessPal summing logic.

CONTEXT.md ("Diary Entry"): "A Food logged with a quantity to one Meal of one
day." The daily/per-meal totals are Σ (Food macros × quantity) over the day's
entries. This logic lives in a PURE function (no DB, no clock) so the analytics
and Budget (#23) slices reuse the exact same definition rather than re-deriving
it.

Quantity semantics (documented decision): ``quantity`` is the **number of
servings** of the Food, so an entry's macros = the Food's per-serving macros ×
quantity. A Food whose serving is "100 g" logged at quantity 1.5 contributes the
150 g macro values; "1 egg" at quantity 2 contributes two eggs.
"""

import pytest

from app.models.diary_entry import Meal
from app.services.nutrition import (
    EntryMacros,
    MacroTotals,
    daily_totals,
    entry_macros,
)


def _entry(meal: Meal, *, kcal, p, c, f, qty) -> EntryMacros:
    """A lightweight value object: one Food's per-serving macros × quantity."""
    return EntryMacros(
        meal=meal,
        quantity=qty,
        calories=kcal,
        protein_g=p,
        carbs_g=c,
        fat_g=f,
    )


# --------------------------------------------------------------------------- #
# entry_macros: per-serving macros × quantity (the scaling rule)
# --------------------------------------------------------------------------- #


def test_entry_macros_scales_per_serving_by_quantity() -> None:
    # A Food "Chicken breast, 100 g": 165 kcal, 31 P, 0 C, 3.6 F per serving.
    scaled = entry_macros(
        quantity=1.5, calories=165, protein_g=31, carbs_g=0, fat_g=3.6
    )
    assert scaled.calories == pytest.approx(247.5)
    assert scaled.protein_g == pytest.approx(46.5)
    assert scaled.carbs_g == pytest.approx(0.0)
    assert scaled.fat_g == pytest.approx(5.4)


def test_entry_macros_whole_unit_food() -> None:
    # "Egg, large" (1 serving = 1 egg): 72 kcal, 6.3 P, 0.4 C, 4.8 F.
    two_eggs = entry_macros(
        quantity=2, calories=72, protein_g=6.3, carbs_g=0.4, fat_g=4.8
    )
    assert two_eggs.calories == pytest.approx(144)
    assert two_eggs.protein_g == pytest.approx(12.6)


def test_entry_macros_zero_quantity_is_zero() -> None:
    z = entry_macros(quantity=0, calories=200, protein_g=10, carbs_g=20, fat_g=5)
    assert (z.calories, z.protein_g, z.carbs_g, z.fat_g) == (0.0, 0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# daily_totals: per-day and per-meal sums
# --------------------------------------------------------------------------- #


def test_empty_day_totals_are_all_zero() -> None:
    totals = daily_totals([])
    assert totals.total == MacroTotals(0.0, 0.0, 0.0, 0.0)
    # Every meal present and zeroed, so a UI can render the four slots blank.
    assert set(totals.by_meal) == {Meal.breakfast, Meal.lunch, Meal.dinner, Meal.snack}
    for meal_totals in totals.by_meal.values():
        assert meal_totals == MacroTotals(0.0, 0.0, 0.0, 0.0)


def test_daily_total_sums_food_macros_times_quantity() -> None:
    entries = [
        # Breakfast: 2 eggs (72 kcal, 6.3P, 0.4C, 4.8F each) + 1 banana
        _entry(Meal.breakfast, kcal=72, p=6.3, c=0.4, f=4.8, qty=2),
        _entry(Meal.breakfast, kcal=105, p=1.3, c=27, f=0.4, qty=1),
        # Lunch: 1.5 servings of chicken (165 kcal/100g)
        _entry(Meal.lunch, kcal=165, p=31, c=0, f=3.6, qty=1.5),
    ]
    totals = daily_totals(entries)
    # Day calories: 144 + 105 + 247.5 = 496.5
    assert totals.total.calories == pytest.approx(496.5)
    # Day protein: 12.6 + 1.3 + 46.5 = 60.4
    assert totals.total.protein_g == pytest.approx(60.4)
    # Day carbs: 0.8 + 27 + 0 = 27.8
    assert totals.total.carbs_g == pytest.approx(27.8)
    # Day fat: 9.6 + 0.4 + 5.4 = 15.4
    assert totals.total.fat_g == pytest.approx(15.4)


def test_per_meal_breakdown_sums_within_each_meal() -> None:
    entries = [
        _entry(Meal.breakfast, kcal=72, p=6.3, c=0.4, f=4.8, qty=2),
        _entry(Meal.breakfast, kcal=105, p=1.3, c=27, f=0.4, qty=1),
        _entry(Meal.lunch, kcal=165, p=31, c=0, f=3.6, qty=1.5),
        _entry(Meal.dinner, kcal=200, p=10, c=20, f=8, qty=1),
    ]
    totals = daily_totals(entries)

    # Breakfast = 144 + 105 = 249 kcal, 13.9 P
    assert totals.by_meal[Meal.breakfast].calories == pytest.approx(249)
    assert totals.by_meal[Meal.breakfast].protein_g == pytest.approx(13.9)
    # Lunch = 247.5 kcal
    assert totals.by_meal[Meal.lunch].calories == pytest.approx(247.5)
    # Dinner = 200 kcal
    assert totals.by_meal[Meal.dinner].calories == pytest.approx(200)
    # Snack has no entries -> zero
    assert totals.by_meal[Meal.snack] == MacroTotals(0.0, 0.0, 0.0, 0.0)

    # The per-meal sums reconcile to the day total.
    meal_sum = sum(m.calories for m in totals.by_meal.values())
    assert meal_sum == pytest.approx(totals.total.calories)


def test_totals_are_rounded_to_one_decimal() -> None:
    # Quantities that produce long decimals must round cleanly for display.
    entries = [
        _entry(Meal.snack, kcal=165, p=31, c=0, f=3.6, qty=0.333),
    ]
    totals = daily_totals(entries)
    # 165 * 0.333 = 54.945 -> 54.9 (one decimal place)
    assert totals.total.calories == 54.9
    assert totals.by_meal[Meal.snack].calories == 54.9
    # 31 * 0.333 = 10.323 -> 10.3
    assert totals.total.protein_g == 10.3


def test_rounding_is_applied_to_the_sum_not_per_entry() -> None:
    # Three entries of 0.1 kcal each: rounding each to 1dp gives 0.1+0.1+0.1=0.3,
    # but the values here exercise that we sum first then round once.
    entries = [
        _entry(Meal.snack, kcal=0.04, p=0, c=0, f=0, qty=1),
        _entry(Meal.snack, kcal=0.04, p=0, c=0, f=0, qty=1),
        _entry(Meal.snack, kcal=0.04, p=0, c=0, f=0, qty=1),
    ]
    totals = daily_totals(entries)
    # Sum = 0.12 -> rounds to 0.1 (rounding per-entry would have given 0.0×3=0.0).
    assert totals.total.calories == 0.1
