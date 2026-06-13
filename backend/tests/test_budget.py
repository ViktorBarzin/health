"""Budget calculator core — adaptive TDEE + goal-driven calorie/macro target (#23).

CONTEXT.md ("Budget"): "The daily calorie/macro target derived from the user's
Goal and their measured energy expenditure, self-calibrating against the observed
weight trend — never a static formula." ("Goal": bulk / cut / maintain /
strength.)

The model has two halves, both pinned here:

1. **Adaptive maintenance (TDEE) from energy balance.** Over a window the user ate
   ``intake`` kcal/day and their *true weight* (the smoother's de-noised value)
   changed at ``rate`` kg/week. Energy balance says a surplus/deficit shows up as
   weight change at ~7700 kcal/kg, so
   ``TDEE = intake − rate_kg_per_week * 7700 / 7``. This *measures* maintenance
   from real data rather than guessing it from a formula — and it self-calibrates:
   if the trend reveals the user was over- or under-eating vs the last estimate,
   the recovered TDEE moves and the target with it.

2. **Goal-driven target.** ``target = TDEE + goal_delta`` where the delta drives
   the Goal's intended rate: bulk → a modest surplus (~0.25-0.5 %BW/week gain),
   cut → a deficit (a sensible loss rate), maintain → maintenance, strength →
   ~maintenance / a slight surplus. Protein comes from the injected Principle
   g/kg rule; fat/carbs split the remainder.

When there isn't enough data to measure TDEE (no weight trend, or no intake), the
core returns a **labelled fallback** (a formula estimate when bodyweight is known,
or an explicit insufficient-data result) — never a confidently-wrong number.

Everything (``now`` is not needed — the windows are pre-reduced by the query
layer) is injected, so the core is pure and these assertions are deterministic.
"""

from __future__ import annotations

import pytest

from app.services.budget import (
    KCAL_PER_KG,
    MAX_PLAUSIBLE_RATE_KG_PER_WEEK,
    BudgetInputs,
    ProteinRule,
    TrendInput,
    compute_budget,
)

# The four Goals come from the Principle model's TrainingGoal enum (the single
# Goal vocabulary, ADR-0004) — referenced here by their string values to keep the
# pure-core test independent of the ORM enum import path.
BULK = "bulk"
CUT = "cut"
MAINTAIN = "maintain"
STRENGTH = "strength"

# A protein rule mirroring the seeded ``protein-intake`` Principle (1.6-2.2 g/kg/d).
PROTEIN = ProteinRule(g_per_kg_min=1.6, g_per_kg_max=2.2)


def _inputs(
    *,
    goal: str,
    intake_kcal: float | None,
    true_weight_kg: float | None,
    rate_kg_per_week: float | None,
    protein: ProteinRule | None = PROTEIN,
    window_days: int = 14,
) -> BudgetInputs:
    trend = (
        TrendInput(true_weight_kg=true_weight_kg, rate_kg_per_week=rate_kg_per_week)
        if true_weight_kg is not None
        else None
    )
    return BudgetInputs(
        goal=goal,
        avg_intake_kcal=intake_kcal,
        intake_days=window_days,
        trend=trend,
        protein_rule=protein,
    )


# --------------------------------------------------------------------------- #
# Adaptive TDEE from energy balance — recovers the right maintenance
# --------------------------------------------------------------------------- #


def test_adaptive_tdee_recovers_maintenance_from_intake_and_weight_change() -> None:
    """Eating 2500 while losing 0.5 kg/week ⇒ TDEE ≈ 2500 + 0.5*7700/7 ≈ 3050.

    The classic energy-balance back-out: a deficit of (0.5 kg/wk * 7700 / 7) ≈
    550 kcal/day below intake, so maintenance is ~550 above the 2500 eaten.
    """
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=2500.0, true_weight_kg=80.0, rate_kg_per_week=-0.5)
    )
    expected_tdee = 2500.0 + 0.5 * KCAL_PER_KG / 7.0
    assert result.tdee_kcal == pytest.approx(expected_tdee, abs=5.0)
    assert result.method == "adaptive"
    assert result.insufficient_data is False


def test_adaptive_tdee_flat_weight_means_intake_is_maintenance() -> None:
    """Weight perfectly flat ⇒ whatever they ate IS maintenance."""
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=2800.0, true_weight_kg=90.0, rate_kg_per_week=0.0)
    )
    assert result.tdee_kcal == pytest.approx(2800.0, abs=1.0)


def test_adaptive_tdee_gaining_on_a_surplus_backs_out_lower_maintenance() -> None:
    """Eating 3000 while gaining 0.25 kg/week ⇒ TDEE below intake (a surplus)."""
    result = compute_budget(
        _inputs(goal=BULK, intake_kcal=3000.0, true_weight_kg=80.0, rate_kg_per_week=0.25)
    )
    expected_tdee = 3000.0 - 0.25 * KCAL_PER_KG / 7.0
    assert result.tdee_kcal == pytest.approx(expected_tdee, abs=5.0)
    assert result.tdee_kcal < 3000.0


# --------------------------------------------------------------------------- #
# Goal drives the target's direction & magnitude
# --------------------------------------------------------------------------- #


def test_maintain_targets_tdee() -> None:
    """A maintain Goal's calorie target is maintenance (no surplus/deficit)."""
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    assert result.target_kcal == pytest.approx(result.tdee_kcal, abs=1.0)


def test_bulk_is_a_modest_surplus_above_maintenance() -> None:
    """A bulk Goal targets a surplus — a positive, but *modest*, delta over TDEE."""
    result = compute_budget(
        _inputs(goal=BULK, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    surplus = result.target_kcal - result.tdee_kcal
    assert surplus > 0
    # ~0.25-0.5 %BW/week on an 80 kg lifter ≈ 0.2-0.4 kg/wk ≈ 220-440 kcal/day.
    assert 150.0 < surplus < 600.0
    assert result.target_rate_kg_per_week is not None
    assert result.target_rate_kg_per_week > 0


def test_cut_is_a_deficit_below_maintenance() -> None:
    """A cut Goal targets a deficit — a negative delta below TDEE, of a sane size."""
    result = compute_budget(
        _inputs(goal=CUT, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    deficit = result.tdee_kcal - result.target_kcal
    assert deficit > 0
    # A sensible cut: ~0.5-1 %BW/week ≈ 0.4-0.8 kg/wk ≈ 440-880 kcal/day.
    assert 300.0 < deficit < 1100.0
    assert result.target_rate_kg_per_week is not None
    assert result.target_rate_kg_per_week < 0


def test_strength_is_near_maintenance() -> None:
    """A strength Goal sits at ~maintenance / a slight surplus — smaller than a bulk."""
    strength = compute_budget(
        _inputs(goal=STRENGTH, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    bulk = compute_budget(
        _inputs(goal=BULK, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    strength_delta = strength.target_kcal - strength.tdee_kcal
    bulk_delta = bulk.target_kcal - bulk.tdee_kcal
    assert strength_delta >= 0
    assert strength_delta < bulk_delta  # a slighter surplus than a bulk


# --------------------------------------------------------------------------- #
# Self-calibration — the target moves the right way as the trend updates
# --------------------------------------------------------------------------- #


def test_bulk_overshooting_pulls_the_target_down() -> None:
    """If a bulker is gaining too fast, the recomputed budget lowers the target.

    Same intake, same goal — only the *observed* rate differs. Gaining fast means
    the measured TDEE is lower (more of the intake is surplus), so the surplus-on-
    top target lands lower than when weight was flat: the system reins the bulk in.
    """
    flat = compute_budget(
        _inputs(goal=BULK, intake_kcal=3000.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    too_fast = compute_budget(
        _inputs(goal=BULK, intake_kcal=3000.0, true_weight_kg=80.0, rate_kg_per_week=1.0)
    )
    assert too_fast.target_kcal < flat.target_kcal


def test_cut_stalling_pushes_the_target_down() -> None:
    """If a cutter has stalled (no loss), the recomputed budget cuts harder.

    A stall means the measured TDEE equals intake; the deficit-below target then
    sits below intake. If instead they were still losing well, TDEE reads higher
    and the target is higher — i.e. a stall correctly tightens the deficit.
    """
    losing = compute_budget(
        _inputs(goal=CUT, intake_kcal=2200.0, true_weight_kg=80.0, rate_kg_per_week=-0.6)
    )
    stalled = compute_budget(
        _inputs(goal=CUT, intake_kcal=2200.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    assert stalled.target_kcal < losing.target_kcal


# --------------------------------------------------------------------------- #
# Macros: protein from the Principle, fat/carb split the remainder
# --------------------------------------------------------------------------- #


def test_protein_comes_from_the_principle_gram_per_kg_rule() -> None:
    """Protein grams = (a value within the Principle's g/kg range) * bodyweight."""
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    # 1.6-2.2 g/kg * 80 kg ⇒ 128-176 g.
    assert 80.0 * 1.6 <= result.protein_g <= 80.0 * 2.2


def test_macros_are_energetically_consistent_with_the_target() -> None:
    """protein*4 + carbs*4 + fat*9 reconstructs the calorie target (Atwater)."""
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=2700.0, true_weight_kg=80.0, rate_kg_per_week=0.0)
    )
    kcal_from_macros = result.protein_g * 4 + result.carbs_g * 4 + result.fat_g * 9
    assert kcal_from_macros == pytest.approx(result.target_kcal, rel=0.03)
    # All three macros are positive (a sane split, no negative carbs).
    assert result.protein_g > 0 and result.carbs_g > 0 and result.fat_g > 0


def test_no_protein_rule_falls_back_to_a_sane_default() -> None:
    """Missing the Principle still yields a defensible protein target (not zero)."""
    result = compute_budget(
        _inputs(
            goal=MAINTAIN, intake_kcal=2700.0, true_weight_kg=80.0,
            rate_kg_per_week=0.0, protein=None,
        )
    )
    # A reasonable fallback band (~1.6-2.2 g/kg) is still applied.
    assert 80.0 * 1.4 <= result.protein_g <= 80.0 * 2.4


# --------------------------------------------------------------------------- #
# Insufficient data — labelled fallback, never a confidently-wrong number
# --------------------------------------------------------------------------- #


def test_no_weight_at_all_is_insufficient_data() -> None:
    """With no bodyweight we can neither measure TDEE nor estimate it — say so."""
    result = compute_budget(
        _inputs(goal=CUT, intake_kcal=2500.0, true_weight_kg=None, rate_kg_per_week=None)
    )
    assert result.insufficient_data is True
    assert result.target_kcal is None
    assert result.tdee_kcal is None


def test_weight_but_no_trend_or_intake_uses_a_labelled_formula_estimate() -> None:
    """Bodyweight only ⇒ a formula TDEE estimate, clearly labelled 'estimated'.

    We can't reconcile energy balance without both an intake history and a weight
    *trend*, so we fall back to a bodyweight-based estimate — but we flag it so the
    UI can say "estimate; log a couple of weeks to calibrate" rather than passing
    it off as measured.
    """
    result = compute_budget(
        _inputs(goal=MAINTAIN, intake_kcal=None, true_weight_kg=80.0, rate_kg_per_week=None)
    )
    assert result.insufficient_data is False
    assert result.method == "estimated"
    assert result.tdee_kcal is not None
    # A plausible maintenance for an 80 kg adult is well inside this band.
    assert 1800.0 < result.tdee_kcal < 3200.0
    assert result.target_kcal is not None


def test_intake_but_no_weight_trend_still_estimates_from_weight() -> None:
    """Intake known but only a single weigh-in (no rate) ⇒ labelled estimate.

    Without a *rate* we can't back TDEE out of energy balance, so even with intake
    we fall back to the labelled bodyweight estimate rather than assuming the lone
    weigh-in means weight is flat.
    """
    result = compute_budget(
        _inputs(goal=BULK, intake_kcal=2900.0, true_weight_kg=82.0, rate_kg_per_week=None)
    )
    assert result.method == "estimated"
    assert result.tdee_kcal is not None
    assert result.target_kcal is not None


def test_estimated_budget_still_applies_the_goal_delta() -> None:
    """A fallback estimate is still goal-aware: a cut estimate is below its TDEE."""
    result = compute_budget(
        _inputs(goal=CUT, intake_kcal=None, true_weight_kg=80.0, rate_kg_per_week=None)
    )
    assert result.target_kcal < result.tdee_kcal


# --------------------------------------------------------------------------- #
# Corrupt-data robustness — an implausible weight rate never yields a negative
# or absurdly-low target / negative macros; it falls back to the labelled estimate
# --------------------------------------------------------------------------- #


def test_implausible_weight_rate_falls_back_to_estimated_not_a_wrong_number() -> None:
    """A physiologically-impossible +5 kg/week (corrupt scale) → labelled estimate.

    A naïve energy-balance back-out would give TDEE = 2500 − 5*7700/7 ≈ −3000, and
    a *negative* calorie target would flow straight through as a "target". Instead,
    a rate beyond the plausibility threshold means the trend is untrustworthy, so we
    fall back to the bodyweight estimate (``method='estimated'``) — never a measured
    number from corrupt data. This is the same honesty contract as insufficient_data.
    """
    result = compute_budget(
        _inputs(goal=BULK, intake_kcal=2500.0, true_weight_kg=80.0, rate_kg_per_week=5.0)
    )
    assert result.insufficient_data is False
    assert result.method == "estimated"  # NOT "adaptive" from the corrupt rate
    # Sane, positive numbers — a bodyweight estimate, not a negative back-out.
    assert result.tdee_kcal is not None and result.tdee_kcal > 1000.0
    assert result.target_kcal is not None and result.target_kcal > 1000.0
    assert result.protein_g > 0 and result.carbs_g >= 0 and result.fat_g > 0


def test_implausible_weight_loss_rate_also_falls_back() -> None:
    """A −4 kg/week (wrong-person / unit-corrupt weigh-ins) is rejected the same way."""
    result = compute_budget(
        _inputs(goal=CUT, intake_kcal=2200.0, true_weight_kg=75.0, rate_kg_per_week=-4.0)
    )
    assert result.method == "estimated"
    assert result.tdee_kcal is not None and result.tdee_kcal > 1000.0
    assert result.target_kcal is not None and result.target_kcal > 1000.0


def test_rate_just_inside_the_threshold_is_still_adaptive() -> None:
    """A fast-but-plausible rate (just under the threshold) is still trusted/measured.

    The guard rejects only the *implausible*; a hard cut/bulk near but below the
    threshold must still be reconciled adaptively (we don't throw away real signal).
    """
    just_under = MAX_PLAUSIBLE_RATE_KG_PER_WEEK - 0.1
    result = compute_budget(
        _inputs(goal=CUT, intake_kcal=2000.0, true_weight_kg=80.0, rate_kg_per_week=-just_under)
    )
    assert result.method == "adaptive"
    expected_tdee = 2000.0 + just_under * KCAL_PER_KG / 7.0
    assert result.tdee_kcal == pytest.approx(expected_tdee, abs=5.0)


def test_output_floor_binds_when_adaptive_tdee_would_go_sub_survival() -> None:
    """A backstop independent of the rate guard: the output floor actually engages.

    Constructed so the *pre-floor* adaptive TDEE is negative — a light person whose
    diary under-reports badly while a fast-but-still-plausible gain is logged:
    TDEE = 800 − 1.4·7700/7 ≈ −740. The plausibility guard does NOT fire (1.4 < 1.5),
    so this is the adaptive path; the defensive floor must catch the absurd number
    and clamp TDEE/target to a sane minimum, with no negative macro escaping.
    """
    just_under = MAX_PLAUSIBLE_RATE_KG_PER_WEEK - 0.1
    naive_tdee = 800.0 - just_under * KCAL_PER_KG / 7.0
    assert naive_tdee < 0.0  # the case really would go negative without the floor
    result = compute_budget(
        _inputs(
            goal=CUT, intake_kcal=800.0, true_weight_kg=50.0,
            rate_kg_per_week=just_under,
        )
    )
    assert result.method == "adaptive"  # guard didn't fire; floor did the work
    assert result.tdee_kcal is not None and result.tdee_kcal >= 1000.0
    assert result.target_kcal is not None and result.target_kcal >= 1000.0
    assert result.fat_g >= 0.0
    assert result.protein_g >= 0.0 and result.carbs_g >= 0.0
