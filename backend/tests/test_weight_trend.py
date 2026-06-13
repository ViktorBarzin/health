"""Weight-trend smoother core — de-noised "true weight" + rate of change (#23).

The Budget (#23, ADR-0004) is *self-calibrating against the observed weight
trend*, so the trend it calibrates against must be a robust signal, not the raw
scale noise (day-to-day bodyweight swings 1-2% on water/food/glycogen alone). This
core turns a noisy daily BodyMass series into:

* a **de-noised true weight** (a time-aware EMA, so a single heavy/light morning
  doesn't move it much), and
* a **rate of change** (kg/week and %BW/week) — the number the Budget reconciles
  energy balance against.

Pinned behavioural properties (mirroring how test_readiness pins the Readiness
core): the smoother *reduces* noise; on a known linear trend the rate has the
right sign and roughly the right magnitude; gaps / irregular sampling don't break
it; and sparse/empty input yields an explicit ``insufficient_data`` result, never
a fabricated number.

``now`` and the samples are **injected** (no clock, no DB in the pure core) so the
assertions are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.weight_trend import (
    WeightSample,
    compute_weight_trend,
)

# A fixed reference instant so every case is deterministic.
NOW = datetime(2026, 6, 13, 7, 0, 0, tzinfo=timezone.utc)


def _daily(values: list[float], *, end: datetime = NOW, step_days: int = 1) -> list[WeightSample]:
    """A daily series ending at ``end``: ``values[-1]`` is the most-recent day.

    ``values[i]`` sits ``(len-1-i) * step_days`` days before ``end`` so the last
    value is the freshest. Used to build controllable weight series.
    """
    n = len(values)
    return [
        WeightSample(at=end - timedelta(days=(n - 1 - i) * step_days), value=v)
        for i, v in enumerate(values)
    ]


# --------------------------------------------------------------------------- #
# Insufficient data — never a fabricated number
# --------------------------------------------------------------------------- #


def test_empty_is_insufficient_data() -> None:
    result = compute_weight_trend([], now=NOW)
    assert result.insufficient_data is True
    assert result.true_weight_kg is None
    assert result.rate_kg_per_week is None
    assert result.rate_pct_per_week is None


def test_single_sample_has_weight_but_no_rate() -> None:
    """One reading gives a current weight but no defensible rate (need ≥2 over time)."""
    result = compute_weight_trend(_daily([80.0]), now=NOW)
    # We know the weight (it's the only reading) but cannot claim a trend.
    assert result.true_weight_kg == pytest.approx(80.0)
    assert result.rate_kg_per_week is None
    assert result.insufficient_data is False


# --------------------------------------------------------------------------- #
# Smoothing: the EMA de-noises a jittery-but-flat series
# --------------------------------------------------------------------------- #


def test_smoother_reduces_noise_on_a_flat_series() -> None:
    """A trend-free series oscillating around 80 kg smooths to ~80, rate ~0."""
    # A palindromic zigzag (reads the same reversed) — symmetric about its centre,
    # so OLS sees exactly zero trend: just realistic ±1.5 kg day-to-day swing.
    raw = [80.0, 81.5, 78.5, 81.5, 78.5, 78.5, 81.5, 78.5, 81.5, 80.0]
    result = compute_weight_trend(_daily(raw), now=NOW)
    assert result.true_weight_kg is not None
    # The de-noised weight sits near the centre, not at any raw spike.
    assert result.true_weight_kg == pytest.approx(80.0, abs=0.8)
    # A flat-on-average series has a near-zero rate (no spurious trend from noise).
    assert result.rate_kg_per_week is not None
    assert abs(result.rate_kg_per_week) < 0.25


def test_true_weight_is_smoother_than_the_raw_last_point() -> None:
    """The reported true weight is closer to the trend than the noisy last reading."""
    # Flat 80 then a single freak +3 kg morning. True weight shouldn't jump to 83.
    raw = [80.0] * 12 + [83.0]
    result = compute_weight_trend(_daily(raw), now=NOW)
    assert result.true_weight_kg is not None
    # The spike pulls it up only a little, not all the way to 83.
    assert 80.0 <= result.true_weight_kg < 81.5


# --------------------------------------------------------------------------- #
# Rate: correct sign & magnitude on a synthetic linear trend
# --------------------------------------------------------------------------- #


def test_steady_gain_has_positive_rate_of_right_magnitude() -> None:
    """+0.1 kg/day for 28 days ⇒ ~+0.7 kg/week."""
    raw = [80.0 + 0.1 * i for i in range(28)]
    result = compute_weight_trend(_daily(raw), now=NOW)
    assert result.rate_kg_per_week is not None
    assert result.rate_kg_per_week == pytest.approx(0.7, abs=0.2)
    # %BW/week relative to the ~82 kg current weight.
    assert result.rate_pct_per_week is not None
    assert result.rate_pct_per_week == pytest.approx(
        result.rate_kg_per_week / result.true_weight_kg * 100, abs=0.05
    )


def test_steady_loss_has_negative_rate() -> None:
    """−0.1 kg/day ⇒ ~−0.7 kg/week (a cut)."""
    raw = [85.0 - 0.1 * i for i in range(28)]
    result = compute_weight_trend(_daily(raw), now=NOW)
    assert result.rate_kg_per_week is not None
    assert result.rate_kg_per_week == pytest.approx(-0.7, abs=0.2)
    assert result.rate_pct_per_week is not None
    assert result.rate_pct_per_week < 0


def test_rate_survives_noise_on_a_trend() -> None:
    """A gaining trend with ±1 kg noise still reads a clearly positive rate."""
    noise = [0.8, -0.9, 0.5, -0.6, 1.0, -0.7, 0.3, -0.4, 0.9, -1.0]
    raw = [80.0 + 0.1 * i + noise[i % len(noise)] for i in range(28)]
    result = compute_weight_trend(_daily(raw), now=NOW)
    assert result.rate_kg_per_week is not None
    # Sign is unambiguous and magnitude is in the right ballpark despite noise.
    assert result.rate_kg_per_week > 0.3
    assert result.rate_kg_per_week == pytest.approx(0.7, abs=0.35)


# --------------------------------------------------------------------------- #
# Irregular / sparse sampling handled gracefully (time-aware, not index-based)
# --------------------------------------------------------------------------- #


def test_irregular_sampling_uses_elapsed_time_not_sample_count() -> None:
    """Gaps between weigh-ins don't distort the rate — it's per *day*, not per *sample*.

    Two weigh-ins a week apart, +0.7 kg apart ⇒ ~+0.7 kg/week, regardless of how
    few samples there are.
    """
    samples = [
        WeightSample(at=NOW - timedelta(days=7), value=80.0),
        WeightSample(at=NOW, value=80.7),
    ]
    result = compute_weight_trend(samples, now=NOW)
    assert result.rate_kg_per_week is not None
    assert result.rate_kg_per_week == pytest.approx(0.7, abs=0.2)


def test_unordered_input_is_handled() -> None:
    """The core sorts by time itself — caller need not pre-sort."""
    ordered = _daily([80.0 + 0.1 * i for i in range(28)])
    # A genuine permutation of all 28 indices (no duplicates, no omissions).
    perm = [5, 0, 27, 13, 2, 20] + [i for i in range(28) if i not in {5, 0, 27, 13, 2, 20}]
    shuffled = [ordered[i] for i in perm]
    a = compute_weight_trend(ordered, now=NOW)
    b = compute_weight_trend(shuffled, now=NOW)
    assert a.true_weight_kg == pytest.approx(b.true_weight_kg)
    assert a.rate_kg_per_week == pytest.approx(b.rate_kg_per_week)


def test_only_very_stale_samples_are_insufficient() -> None:
    """Samples far outside the window don't produce a current trend.

    A reading from a year ago tells us nothing about the *current* weight or
    trend, so the core reports insufficient data rather than a stale number.
    """
    samples = [
        WeightSample(at=NOW - timedelta(days=400), value=90.0),
        WeightSample(at=NOW - timedelta(days=395), value=89.0),
    ]
    result = compute_weight_trend(samples, now=NOW)
    assert result.insufficient_data is True


def test_window_days_is_respected() -> None:
    """An ancient point outside the window doesn't drag the rate.

    With a long flat-recent series plus one very old heavy point, the recent
    (in-window) trend dominates — the rate stays near zero, not skewed by the
    out-of-window outlier.
    """
    recent = _daily([80.0] * 21)  # 3 flat weeks
    ancient = [WeightSample(at=NOW - timedelta(days=300), value=95.0)]
    result = compute_weight_trend(ancient + recent, now=NOW, window_days=28)
    assert result.rate_kg_per_week is not None
    assert abs(result.rate_kg_per_week) < 0.1
    assert result.true_weight_kg == pytest.approx(80.0, abs=0.5)
