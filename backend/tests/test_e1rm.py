"""Estimated 1-rep-max (e1RM) core — the engine that converts a (weight, reps)
performance into a single comparable strength number.

This is an ENGINE CORE reused by PR detection (#8), analytics (#10) and the
Progression generator (#11), so its mathematical properties are pinned hard with
property-based-style parametrization rather than a handful of point checks:

* monotonic non-decreasing in weight (heavier at equal reps ⇒ ≥ estimate);
* monotonic non-decreasing in reps (more reps at equal weight ⇒ ≥ estimate);
* reps == 1 ⇒ estimate == weight exactly (a single is its own 1RM);
* the optional RIR effort adjustment never *lowers* the estimate, and a set with
  reps in reserve estimates ≥ the same set logged to failure-equivalent reps.
"""

import pytest

from app.services.e1rm import epley_1rm, estimated_1rm

# A spread of representative loads/reps for the property sweeps. Kept small but
# spanning light→heavy and single→high-rep, so the monotonicity properties are
# exercised without bloating the suite with near-duplicate parametrizations.
_WEIGHTS = [1.0, 60.0, 142.5, 315.0]
_REPS = [1, 3, 5, 12, 20]


def test_reps_one_equals_weight_exactly() -> None:
    # A single rep is its own 1RM — the Epley formula's fixed boundary.
    for w in _WEIGHTS:
        assert epley_1rm(w, 1) == pytest.approx(w)
        assert estimated_1rm(w, 1) == pytest.approx(w)


def test_epley_known_value() -> None:
    # 1-rep-anchored Epley: 100 kg × 5 → 100 * (1 + (5-1)/30) = 113.3333.
    assert epley_1rm(100.0, 5) == pytest.approx(100.0 * (1 + 4 / 30))


@pytest.mark.parametrize("reps", _REPS)
def test_monotonic_non_decreasing_in_weight(reps: int) -> None:
    # Heavier at the same reps can never estimate a lower 1RM.
    prev = None
    for w in _WEIGHTS:
        est = estimated_1rm(w, reps)
        if prev is not None:
            assert est >= prev
        prev = est


@pytest.mark.parametrize("weight", _WEIGHTS)
def test_monotonic_non_decreasing_in_reps(weight: float) -> None:
    # More reps at the same weight can never estimate a lower 1RM.
    prev = None
    for r in _REPS:
        est = estimated_1rm(weight, r)
        if prev is not None:
            assert est >= prev
        prev = est


def test_more_reps_strictly_increases_estimate() -> None:
    # Epley is strictly increasing in reps for a fixed positive weight.
    assert estimated_1rm(100.0, 6) > estimated_1rm(100.0, 5)


def test_zero_weight_is_zero() -> None:
    # No load ⇒ no estimate, at any rep count (avoids polluting PRs with 0-weight
    # bodyweight placeholders).
    for r in _REPS:
        assert estimated_1rm(0.0, r) == 0.0


def test_zero_reps_is_zero() -> None:
    # A set with no completed reps contributes no strength estimate.
    for w in _WEIGHTS:
        assert estimated_1rm(w, 0) == 0.0


def test_negative_inputs_are_invalid() -> None:
    with pytest.raises(ValueError):
        estimated_1rm(-1.0, 5)
    with pytest.raises(ValueError):
        estimated_1rm(100.0, -1)


# --------------------------------------------------------------------------- #
# Effort (RIR) adjustment: reps-in-reserve make a set effectively heavier.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("weight", _WEIGHTS)
@pytest.mark.parametrize("reps", _REPS)
def test_rir_adjustment_never_lowers_the_estimate(weight: float, reps: int) -> None:
    # The never-lowering property must hold at every RIR bucket; sweep them within
    # the test rather than as a third parametrize dimension (avoids a needless
    # combinatorial blow-up of near-identical cases).
    base = estimated_1rm(weight, reps)
    for rir in (0, 1, 2, 3, 4):
        assert estimated_1rm(weight, reps, rir=rir) >= base


def test_rir_zero_or_none_equals_unadjusted() -> None:
    # RIR 0 = taken to failure (no reserve) and None = not rated both leave the
    # estimate exactly as the plain (weight, reps) Epley result.
    for w in _WEIGHTS:
        for r in _REPS:
            assert estimated_1rm(w, r, rir=0) == pytest.approx(estimated_1rm(w, r))
            assert estimated_1rm(w, r, rir=None) == pytest.approx(estimated_1rm(w, r))


def test_more_reserve_means_higher_estimate() -> None:
    # 100 kg × 5 with 3 reps in reserve estimates the same as ~100 kg × 8 to
    # failure — leaving reps in the tank means the true 1RM is higher.
    with_reserve = estimated_1rm(100.0, 5, rir=3)
    failure_equiv = estimated_1rm(100.0, 8)
    assert with_reserve == pytest.approx(failure_equiv)


@pytest.mark.parametrize("weight", _WEIGHTS)
def test_rir_adjustment_monotonic_in_reserve(weight: float) -> None:
    # At fixed weight/reps, more reps in reserve ⇒ a higher (never lower) estimate.
    prev = None
    for rir in [0, 1, 2, 3, 4]:
        est = estimated_1rm(weight, 5, rir=rir)
        if prev is not None:
            assert est >= prev
        prev = est
