"""Budget calculator — adaptive TDEE + goal-driven calorie/macro target (#23, ADR-0004).

CONTEXT.md ("Budget"): "The daily calorie/macro target derived from the user's
Goal and their measured energy expenditure, self-calibrating against the observed
weight trend — never a static formula." ("Goal": bulk / cut / maintain / strength
— "a single object parameterizing both the active Program and the Budget".)

Like :mod:`app.services.readiness` / :mod:`app.services.weight_trend` this is a
**pure** module — no DB, no clock, no I/O. The reduced inputs (average intake over
a window, the smoothed weight trend, the protein Principle's g/kg range, the Goal)
are injected by the query layer (:mod:`app.services.budget_query`); the maths here
is deterministic and unit-tested in isolation.

The model
=========
**1. Adaptive maintenance (TDEE) from energy balance.** Rather than guess
maintenance from a static Harris-Benedict / Mifflin formula, we *measure* it from
the user's own data. Over the intake window the user ate ``avg_intake`` kcal/day
and their de-noised "true weight" changed at ``rate`` kg/week (from the
weight-trend smoother). A surplus or deficit manifests as weight change at about
:data:`KCAL_PER_KG` kcal per kg of bodyweight, so::

    TDEE = avg_intake − rate_kg_per_week * KCAL_PER_KG / 7

(eating above maintenance ⇒ weight rises ⇒ measured TDEE is *below* intake, and
vice-versa). This is **self-calibrating**: each recompute re-measures TDEE from
the latest trend, so if the weight is moving faster or slower than the goal wants,
the recovered TDEE — and the target built on it — shifts to correct it.

**2. Goal-driven target.** ``target = TDEE + goal_delta``. The delta is set to
drive the Goal's intended *rate* of weight change (:data:`_GOAL_TARGET_RATE_PCT`,
in %bodyweight/week), converted to a daily kcal delta the same way (rate → kg/week
→ kcal via ``KCAL_PER_KG``):

* **bulk** → a modest surplus targeting ~0.25-0.5 %BW/week gain;
* **cut** → a deficit targeting a sensible loss (~0.5-1 %BW/week);
* **maintain** → maintenance (zero delta);
* **strength** → ~maintenance / a slight surplus (smaller than a bulk).

Expressing the delta as a *target rate* (not a fixed kcal number) is what keeps it
honest end-to-end: the target chases a rate, TDEE is measured, so the calorie
number self-adjusts as the body responds.

**3. Macros.** Protein is the priority macro: ``protein_g/kg * true_weight`` using
a value within the injected Principle's g/kg range (goal-aware — a cut and
strength push to the top of the range to spare lean mass, a bulk sits a touch
lower; :data:`_PROTEIN_GOAL_FRACTION`). Fat is set to :data:`_FAT_KCAL_FRACTION`
of the calorie target (a floor for hormonal health), and carbohydrate takes the
remaining calories. Each macro converts at Atwater factors
(:data:`_KCAL_PER_G`), so the three reconstruct the calorie target.

Insufficient data — a labelled fallback, never a confident wrong number
=======================================================================
Measuring TDEE needs **both** an intake history *and* a weight *trend* (a rate).
When either is missing:

* **bodyweight known** → a bodyweight-based formula estimate
  (:data:`_KCAL_PER_KG_MAINTENANCE` kcal/kg/day), flagged ``method="estimated"``
  so the UI can say "estimate — log a couple of weeks to calibrate". The Goal
  delta still applies, so the estimate is goal-aware.
* **no bodyweight at all** → ``insufficient_data`` with null numbers. We cannot
  even estimate, so we say so rather than fabricate.

All constants live at the top — the single place to retune the Budget.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Tunable model constants — the single place to retune the Budget. See the module
# docstring for the reasoning behind each default.
# --------------------------------------------------------------------------- #

#: Energy density of bodyweight change — the classic ~7700 kcal per kg (≈3500
#: kcal/lb) figure. The constant that ties weight change to energy balance, used
#: both to back TDEE out of the observed trend and to size the goal delta. A
#: simplification (real tissue is a fat/lean/water mix) but the standard,
#: defensible first-order figure for energy-balance budgeting.
KCAL_PER_KG: float = 7700.0

#: Per-Goal target *rate* of weight change, in %bodyweight/week. The Budget sizes
#: its surplus/deficit to drive these rates (ADR-0004: a bulk targets
#: ~0.25-0.5 %BW/week). Positive = gain, negative = loss.
_GOAL_TARGET_RATE_PCT: dict[str, float] = {
    "bulk": 0.375,      # midpoint of the 0.25-0.5 %BW/week bulk band
    "cut": -0.75,       # ~0.5-1 %BW/week loss — sustainable, lean-mass-sparing
    "maintain": 0.0,    # hold weight
    "strength": 0.15,   # near-maintenance, a slight surplus to support strength
}

#: Where in the protein Principle's [min, max] g/kg range each Goal sits. A cut and
#: strength go to the top (more protein spares lean mass in a deficit / supports
#: strength work); a bulk sits a little lower (ample energy already); maintain at
#: the low end. 0.0 ⇒ the range minimum, 1.0 ⇒ the maximum.
_PROTEIN_GOAL_FRACTION: dict[str, float] = {
    "bulk": 0.4,
    "cut": 1.0,
    "maintain": 0.0,
    "strength": 1.0,
}

#: Fallback protein g/kg range when no Principle is injected — the same
#: evidence-based 1.6-2.2 g/kg/day band the seeded Principle carries, so the
#: Budget still gives a sane protein target if the KB lookup misses.
_FALLBACK_PROTEIN_MIN: float = 1.6
_FALLBACK_PROTEIN_MAX: float = 2.2

#: Fraction of the calorie target allocated to fat (a floor for hormonal health);
#: carbohydrate takes the rest. 0.25 = 25% of calories from fat, a middle-of-the-
#: road split that leaves ample carbohydrate for training.
_FAT_KCAL_FRACTION: float = 0.25

#: Atwater factors — kcal per gram of each macronutrient.
_KCAL_PER_G_PROTEIN: float = 4.0
_KCAL_PER_G_CARB: float = 4.0
_KCAL_PER_G_FAT: float = 9.0

#: Bodyweight-based maintenance estimate (kcal/kg/day) for the labelled fallback
#: when energy balance can't be measured. ~31 kcal/kg is a moderate-activity
#: rule-of-thumb (sedentary ~26-28, very active ~35+); deliberately a coarse
#: estimate, surfaced as ``method="estimated"`` so it is never mistaken for a
#: measured TDEE.
_KCAL_PER_KG_MAINTENANCE: float = 31.0

#: Days per week — the rates are per week.
_DAYS_PER_WEEK: float = 7.0


@dataclass(frozen=True)
class ProteinRule:
    """The protein Principle's g/kg/day range (from ``protein-intake``, Morton 2018).

    The query layer reads the seeded Principle's ``protein_g_per_kg_per_day`` param
    and builds this; the core picks a Goal-appropriate point within ``[min, max]``.
    """

    g_per_kg_min: float
    g_per_kg_max: float


@dataclass(frozen=True)
class TrendInput:
    """The reduced weight-trend signal the Budget consumes.

    Built from :class:`app.services.weight_trend.WeightTrend`: the current de-noised
    ``true_weight_kg`` and the ``rate_kg_per_week`` (``None`` when the trend has a
    weight but not enough data for a rate — then TDEE can't be measured).
    """

    true_weight_kg: float | None
    rate_kg_per_week: float | None


@dataclass(frozen=True)
class BudgetInputs:
    """Everything the Budget core needs, pre-reduced by the query layer.

    * ``goal`` — the user's Goal (a :class:`TrainingGoal` value: bulk/cut/maintain/
      strength), the single object driving Program and Budget (ADR-0004).
    * ``avg_intake_kcal`` — mean logged calorie intake/day over the window (from the
      pure nutrition ``daily_totals``), or ``None`` if there's no intake history.
    * ``intake_days`` — how many days that average covers (for the confidence hint).
    * ``trend`` — the smoothed weight trend, or ``None`` if no bodyweight at all.
    * ``protein_rule`` — the protein Principle's g/kg range, or ``None`` (fallback).
    """

    goal: str
    avg_intake_kcal: float | None
    intake_days: int
    trend: TrendInput | None
    protein_rule: ProteinRule | None


@dataclass(frozen=True)
class Budget:
    """The computed daily Budget.

    ``insufficient_data`` is true (every number ``None``) when there isn't even a
    bodyweight to estimate from. Otherwise ``method`` is ``"adaptive"`` (TDEE
    measured from energy balance) or ``"estimated"`` (a labelled bodyweight
    formula fallback). ``tdee_kcal`` is maintenance; ``target_kcal`` the
    goal-adjusted calorie target; ``protein_g``/``carbs_g``/``fat_g`` the macro
    targets. ``target_rate_kg_per_week`` is the weight change the target is sized
    to drive (for the UI: "aiming for +0.3 kg/week"). ``true_weight_kg`` and
    ``rate_kg_per_week`` echo the current trend so the UI shows both Budget and
    trend together.
    """

    insufficient_data: bool
    method: str | None
    tdee_kcal: float | None
    target_kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    target_rate_kg_per_week: float | None
    true_weight_kg: float | None
    rate_kg_per_week: float | None
    intake_days: int = 0


_INSUFFICIENT = Budget(
    insufficient_data=True,
    method=None,
    tdee_kcal=None,
    target_kcal=None,
    protein_g=None,
    carbs_g=None,
    fat_g=None,
    target_rate_kg_per_week=None,
    true_weight_kg=None,
    rate_kg_per_week=None,
)


def _rate_to_kcal_per_day(rate_kg_per_week: float) -> float:
    """A weight-change rate (kg/week) as the daily energy surplus/deficit it implies."""
    return rate_kg_per_week * KCAL_PER_KG / _DAYS_PER_WEEK


def _goal_target_rate_kg_per_week(goal: str, true_weight_kg: float) -> float:
    """The Goal's intended weight-change rate in kg/week, for this bodyweight.

    The %BW/week target (:data:`_GOAL_TARGET_RATE_PCT`) scaled by bodyweight, so a
    heavier lifter's absolute kg/week is proportionally larger. An unknown goal
    falls back to maintenance (0).
    """
    pct = _GOAL_TARGET_RATE_PCT.get(goal, 0.0)
    return pct / 100.0 * true_weight_kg


def _protein_g(goal: str, true_weight_kg: float, rule: ProteinRule | None) -> float:
    """Protein target (grams) = a Goal-appropriate g/kg point × bodyweight.

    Uses the injected Principle range when present, else the evidence-based
    fallback band. The Goal picks where in the range to sit
    (:data:`_PROTEIN_GOAL_FRACTION`): cut/strength at the top, bulk lower, maintain
    at the bottom.
    """
    lo = rule.g_per_kg_min if rule is not None else _FALLBACK_PROTEIN_MIN
    hi = rule.g_per_kg_max if rule is not None else _FALLBACK_PROTEIN_MAX
    frac = _PROTEIN_GOAL_FRACTION.get(goal, 0.5)
    g_per_kg = lo + (hi - lo) * frac
    return g_per_kg * true_weight_kg


def _macros(
    goal: str, target_kcal: float, true_weight_kg: float, rule: ProteinRule | None
) -> tuple[float, float, float]:
    """Split a calorie target into (protein_g, carbs_g, fat_g).

    Protein first (from the Principle), fat as a fraction of calories (a hormonal
    floor), carbohydrate the remainder. Carbs are floored at zero so an extreme
    deficit with high protein never yields a negative number (it just means
    protein+fat already meet the target). Note: when that floor binds, protein and
    fat are hard minimums that can't both be honoured under a tiny target, so the
    three macros may sum to slightly *more* than ``target_kcal`` — a deliberate
    trade-off (the protein/fat floors win); a UI summing the macros should expect
    that edge rather than assume they always reconstruct the calorie target.
    """
    protein_g = _protein_g(goal, true_weight_kg, rule)
    fat_g = target_kcal * _FAT_KCAL_FRACTION / _KCAL_PER_G_FAT
    protein_kcal = protein_g * _KCAL_PER_G_PROTEIN
    fat_kcal = fat_g * _KCAL_PER_G_FAT
    carbs_kcal = max(0.0, target_kcal - protein_kcal - fat_kcal)
    carbs_g = carbs_kcal / _KCAL_PER_G_CARB
    return protein_g, carbs_g, fat_g


def compute_budget(inputs: BudgetInputs) -> Budget:
    """Compute the daily Budget from intake, the weight trend, the Goal & protein rule.

    Measures TDEE adaptively from energy balance when both an intake history and a
    weight *rate* are available (``method="adaptive"``); otherwise falls back to a
    labelled bodyweight estimate (``method="estimated"``) when at least a
    bodyweight is known, or an ``insufficient_data`` result when not even that.
    Always applies the Goal's surplus/deficit and derives macros.
    """
    trend = inputs.trend
    true_weight = trend.true_weight_kg if trend is not None else None

    # No bodyweight at all ⇒ we can neither measure nor estimate maintenance.
    if true_weight is None:
        return _INSUFFICIENT

    rate = trend.rate_kg_per_week if trend is not None else None
    have_adaptive = inputs.avg_intake_kcal is not None and rate is not None

    if have_adaptive:
        # Measure maintenance from energy balance: intake minus the energy the
        # observed weight change represents.
        tdee = inputs.avg_intake_kcal - _rate_to_kcal_per_day(rate)
        method = "adaptive"
    else:
        # Labelled fallback: a coarse bodyweight-based maintenance estimate.
        tdee = _KCAL_PER_KG_MAINTENANCE * true_weight
        method = "estimated"

    target_rate = _goal_target_rate_kg_per_week(inputs.goal, true_weight)
    goal_delta = _rate_to_kcal_per_day(target_rate)
    target_kcal = tdee + goal_delta

    protein_g, carbs_g, fat_g = _macros(
        inputs.goal, target_kcal, true_weight, inputs.protein_rule
    )

    return Budget(
        insufficient_data=False,
        method=method,
        tdee_kcal=tdee,
        target_kcal=target_kcal,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        target_rate_kg_per_week=target_rate,
        true_weight_kg=true_weight,
        rate_kg_per_week=rate,
        intake_days=inputs.intake_days,
    )
