"""Pure macro-totalling — the canonical "sum a day's Diary Entries" definition.

CONTEXT.md ("Diary Entry"): "A Food logged with a quantity to one Meal of one
day." A day's totals are Σ (Food per-serving macros × quantity) over its entries,
broken down per Meal and summed for the day.

This module is **pure**: no DB, no clock, no I/O. It operates on lightweight
:class:`EntryMacros` value objects the API/query layer builds from ORM rows, so
the analytics and Budget (#23) slices reuse this exact definition rather than
re-deriving (and risking diverging from) it — the same discipline as
:mod:`app.services.volume` for training.

Quantity semantics (documented decision): ``quantity`` is the **number of
servings** of the Food, so an entry contributes the Food's per-serving macros ×
quantity. Totals are rounded to one decimal place **once, after summing** (not
per entry) so display values are clean without accumulating rounding error.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.models.diary_entry import Meal

# Macros are reported to one decimal place — enough for grams/kcal on a phone,
# and rounded after summing so per-entry rounding never compounds.
_ROUND_DP = 1


@dataclass(frozen=True)
class MacroTotals:
    """A bundle of summed macros (calories + the three macronutrients, grams)."""

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class EntryMacros:
    """One Diary Entry's inputs to the sum: its Meal, quantity, and the Food's
    per-serving macros. The query layer builds these from ``DiaryEntry`` + its
    ``Food``; the pure core never touches the ORM."""

    meal: Meal
    quantity: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class DailyTotals:
    """A day's totals: the per-Meal breakdown and the whole-day sum.

    ``by_meal`` always carries all four Meal slots (zeroed when empty) so a day
    view can render the four sections without missing-key handling.
    """

    by_meal: dict[Meal, MacroTotals]
    total: MacroTotals


def entry_macros(
    *,
    quantity: float,
    calories: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
) -> MacroTotals:
    """Scale a Food's per-serving macros by ``quantity`` (number of servings).

    The single definition of "what one Diary Entry contributes". Not rounded
    here — :func:`daily_totals` rounds once after summing.
    """
    return MacroTotals(
        calories=calories * quantity,
        protein_g=protein_g * quantity,
        carbs_g=carbs_g * quantity,
        fat_g=fat_g * quantity,
    )


def _round(totals: MacroTotals) -> MacroTotals:
    return MacroTotals(
        calories=round(totals.calories, _ROUND_DP),
        protein_g=round(totals.protein_g, _ROUND_DP),
        carbs_g=round(totals.carbs_g, _ROUND_DP),
        fat_g=round(totals.fat_g, _ROUND_DP),
    )


def daily_totals(entries: Iterable[EntryMacros]) -> DailyTotals:
    """Sum a day's Diary Entries into per-Meal and whole-day macro totals.

    Each entry contributes its Food's per-serving macros × quantity. Sums are
    accumulated unrounded, then rounded once to one decimal place — so the
    per-Meal sums always reconcile to the day total (modulo a 0.1 display
    rounding), and per-entry rounding never compounds. An empty day yields all
    zeros with every Meal slot present.
    """
    # Start every Meal at zero so the breakdown always has the four slots.
    raw_by_meal: dict[Meal, list[float]] = {
        meal: [0.0, 0.0, 0.0, 0.0] for meal in Meal
    }
    raw_total = [0.0, 0.0, 0.0, 0.0]

    for e in entries:
        contrib = entry_macros(
            quantity=e.quantity,
            calories=e.calories,
            protein_g=e.protein_g,
            carbs_g=e.carbs_g,
            fat_g=e.fat_g,
        )
        bucket = raw_by_meal[e.meal]
        bucket[0] += contrib.calories
        bucket[1] += contrib.protein_g
        bucket[2] += contrib.carbs_g
        bucket[3] += contrib.fat_g
        raw_total[0] += contrib.calories
        raw_total[1] += contrib.protein_g
        raw_total[2] += contrib.carbs_g
        raw_total[3] += contrib.fat_g

    by_meal = {
        meal: _round(MacroTotals(c, p, cb, f))
        for meal, (c, p, cb, f) in raw_by_meal.items()
    }
    total = _round(MacroTotals(*raw_total))
    return DailyTotals(by_meal=by_meal, total=total)
