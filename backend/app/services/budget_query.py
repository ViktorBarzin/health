"""Budget query layer — binds the pure Budget + weight-trend cores to a user (#23).

The DB-touching glue for the Budget (#23, ADR-0004), mirroring
:mod:`app.services.readiness_query`: all the maths lives in the pure cores
(:mod:`app.services.weight_trend`, :mod:`app.services.budget`); this module only
fetches the right rows, reduces them to the cores' injected inputs, and runs them.
``now`` is injected by the caller (the route passes request time) so the binding
is as deterministic as the cores.

What it reduces, and from where
===============================
* **Weight trend** — ``health_records`` BodyMass rows (``metric_type='BodyMass'``)
  over the trend window, **normalised to kilograms** (Apple stores the user's
  device unit — kg or lb — raw; the energy/distance parsers convert at ingest but
  body mass is left raw, so we convert here). Fed to
  :func:`app.services.weight_trend.compute_weight_trend`.
* **Intake** — the user's logged **Diary Entries** over the same window, summed
  per day by the **pure** :func:`app.services.nutrition.daily_totals` (the single
  definition of a day's calories, reused — never re-derived), then averaged over
  the days that actually have entries. We reconcile *logged calorie intake*
  against the weight trend — deliberately the diary, not the watch's
  ``ActiveEnergyBurned`` (which is an independent estimate, and stored in kJ).
* **Protein rule** — the seeded ``protein-intake`` Principle's
  ``protein_g_per_kg_per_day`` range (Morton 2018), via
  :mod:`app.services.principles_query`. Missing ⇒ the core's fallback band.
* **Goal** — the user's **active Program**'s goal (the single Goal object driving
  both Program and Budget, ADR-0004). No active Program ⇒ ``maintain`` (a safe,
  neutral default — hold weight until the user sets a Goal via a Program).

The intake window and the trend window are both
:data:`_WINDOW_DAYS` (28 days) so the energy-balance reconciliation compares
intake and weight change over the *same* period.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diary_entry import DiaryEntry
from app.models.food import Food
from app.models.health_record import HealthRecord
from app.models.principle import TrainingGoal
from app.services.budget import (
    Budget,
    BudgetInputs,
    ProteinRule,
    TrendInput,
    compute_budget,
)
from app.services.nutrition import EntryMacros, daily_totals
from app.services.principles_query import principle_by_key
from app.services.program_query import active_program
from app.services.weight_trend import WeightSample, WeightTrend, compute_weight_trend

#: BodyMass metric (the cleaned Apple Health quantity-type name; the prefix is
#: stripped at ingest, e.g. ``HKQuantityTypeIdentifierBodyMass`` → ``BodyMass``).
_BODY_MASS_METRIC = "BodyMass"

#: The Principle key carrying the protein g/kg/day range (seeded, Morton 2018).
_PROTEIN_PRINCIPLE_KEY = "protein-intake"
_PROTEIN_PARAM = "protein_g_per_kg_per_day"

#: Trend + intake window — 28 days (4 weeks): long enough to average out a week's
#: water/food noise and to accumulate a measurable weight change, short enough to
#: reflect the *current* regime. Matches the Readiness baseline window.
_WINDOW_DAYS = 28

#: Pounds → kilograms (the exact factor the Fitbod parser uses).
_LB_TO_KG = 0.45359237


def _to_kg(value: float, unit: str | None) -> float:
    """Normalise a body-mass reading to kilograms by its stored unit.

    Apple records body mass in the device's unit; we store it raw with that unit.
    ``lb``/``lbs``/``pound(s)`` convert; anything else (``kg``, or absent) is taken
    as kilograms already — the dominant case, and a safe default.
    """
    if unit is None:
        return value
    u = unit.strip().lower()
    if u in ("lb", "lbs", "pound", "pounds"):
        return value * _LB_TO_KG
    return value


async def _weight_samples(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> list[WeightSample]:
    """The user's BodyMass readings over the window, normalised to kg.

    One sample per stored reading (the trend smoother does its own time-aware
    de-noising, so we don't pre-aggregate to daily here — it copes with multiple
    same-day weigh-ins and irregular spacing). Ascending by time.
    """
    window_start = now - dt.timedelta(days=_WINDOW_DAYS)
    stmt = (
        select(HealthRecord.time, HealthRecord.value, HealthRecord.unit)
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == _BODY_MASS_METRIC,
            HealthRecord.time >= window_start,
            HealthRecord.time <= now,
        )
        .order_by(HealthRecord.time)
    )
    rows = (await db.execute(stmt)).all()
    return [WeightSample(at=r.time, value=_to_kg(float(r.value), r.unit)) for r in rows]


async def _avg_intake(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> tuple[float | None, int]:
    """Mean logged calories/day over the window + the number of days with entries.

    Sums each day's Diary Entries with the **pure** ``daily_totals`` (reusing the
    canonical macro-totalling definition), then averages over the days that have
    any entry — a sparsely-logged stretch isn't diluted by counting empty days as
    zero-calorie. Returns ``(None, 0)`` when there's no logged intake in the window.
    """
    window_start_date = (now - dt.timedelta(days=_WINDOW_DAYS)).date()
    today = now.date()
    stmt = (
        select(DiaryEntry, Food)
        .join(Food, DiaryEntry.food_id == Food.id)
        .where(
            DiaryEntry.user_id == user_id,
            DiaryEntry.entry_date >= window_start_date,
            DiaryEntry.entry_date <= today,
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None, 0

    by_day: dict[dt.date, list[EntryMacros]] = {}
    for entry, food in rows:
        by_day.setdefault(entry.entry_date, []).append(
            EntryMacros(
                meal=entry.meal,
                quantity=entry.quantity,
                calories=food.calories,
                protein_g=food.protein_g,
                carbs_g=food.carbs_g,
                fat_g=food.fat_g,
            )
        )

    day_calories = [daily_totals(macros).total.calories for macros in by_day.values()]
    avg = sum(day_calories) / len(day_calories)
    return avg, len(day_calories)


async def _protein_rule(db: AsyncSession) -> ProteinRule | None:
    """The protein Principle's g/kg range as a :class:`ProteinRule`, or ``None``.

    Reads the seeded ``protein-intake`` Principle's
    ``protein_g_per_kg_per_day`` param. ``None`` (Principle absent / param
    malformed) lets the Budget core apply its evidence-based fallback band.
    """
    principle = await principle_by_key(db, _PROTEIN_PRINCIPLE_KEY)
    if principle is None:
        return None
    param = (principle.params or {}).get(_PROTEIN_PARAM)
    if not isinstance(param, dict):
        return None
    lo = param.get("min")
    hi = param.get("max")
    if lo is None or hi is None:
        return None
    return ProteinRule(g_per_kg_min=float(lo), g_per_kg_max=float(hi))


async def _goal(db: AsyncSession, user_id: int) -> str:
    """The user's current Goal — their active Program's goal, else ``maintain``.

    ADR-0004: one Goal object drives both Program and Budget, so the Budget reads
    the active Program's ``goal`` rather than introducing a second goal concept. No
    active Program ⇒ ``maintain`` (hold weight) until the user picks a Goal.
    """
    program = await active_program(db, user_id)
    if program is None:
        return TrainingGoal.maintain.value
    return program.goal


@dataclass(frozen=True)
class BudgetResult:
    """A user's Budget plus the context the API surfaces alongside it.

    Bundles the pure :class:`~app.services.budget.Budget`, the de-noised
    :class:`~app.services.weight_trend.WeightTrend` it was calibrated on (so the UI
    can show Budget *and* trend together, with the trend's own ``n_samples`` /
    ``rate_pct_per_week``), and the ``goal`` it was built for.
    """

    budget: Budget
    trend: WeightTrend
    goal: str


async def weight_trend_for_user(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> WeightTrend:
    """The user's de-noised weight trend over the window (the pure core's result)."""
    samples = await _weight_samples(db, user_id, now=now)
    return compute_weight_trend(samples, now=now, window_days=_WINDOW_DAYS)


async def budget_for_user(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> BudgetResult:
    """Today's Budget for a user — fetch intake/weight/goal/protein, run the core.

    ``now`` is injected so a fixed DB state yields a fixed Budget. Returns a
    :class:`BudgetResult` bundling the pure Budget (an ``insufficient_data`` result
    when the user has no bodyweight history, a labelled ``estimated`` one when they
    lack the intake-or-trend needed to *measure* TDEE), the weight trend it rode,
    and the Goal it was built for.
    """
    trend = await weight_trend_for_user(db, user_id, now=now)
    avg_intake, intake_days = await _avg_intake(db, user_id, now=now)
    protein_rule = await _protein_rule(db)
    goal = await _goal(db, user_id)

    inputs = BudgetInputs(
        goal=goal,
        avg_intake_kcal=avg_intake,
        intake_days=intake_days,
        trend=TrendInput(
            true_weight_kg=trend.true_weight_kg,
            rate_kg_per_week=trend.rate_kg_per_week,
        )
        if not trend.insufficient_data
        else None,
        protein_rule=protein_rule,
    )
    return BudgetResult(budget=compute_budget(inputs), trend=trend, goal=goal)
