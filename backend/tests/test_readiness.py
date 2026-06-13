"""Readiness core — the daily biometric 0–100 signal (#14, ADR-0004).

Readiness is an ENGINE CORE (it feeds autoregulation and is a dashboard insight
in its own right), so its behavioural properties are pinned hard the same way
:mod:`tests.test_recovery` pins the Recovery core:

* a *recent* HRV below the user's own baseline lowers readiness (and a
  monotonic sensitivity: the lower the recent HRV vs baseline, the lower the
  score);
* an *elevated* resting heart rate vs baseline lowers readiness (monotonic);
* *poor* sleep vs baseline lowers readiness (monotonic);
* the metrics combine — all three depressed reads lower than any one depressed;
* with NO metrics the core returns an explicit *insufficient-data* state, never
  a misleading number; a missing metric simply drops out of the blend (the
  remaining signals still produce a score);
* the score is bounded in ``[0, 100]``; a user sitting exactly at baseline on
  every metric reads the neutral midpoint.

CONTEXT.md ("Readiness"): "A daily per-user signal derived from HRV, resting
heart rate, and sleep trends". This is distinct from training-load **Recovery**
(#10) — Readiness is the *biometric* signal.

The reference "now" and the metric samples are **injected** (never read from a
clock or DB inside the pure core) so the assertions are deterministic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.readiness import (
    MetricSample,
    ReadinessInputs,
    compute_readiness,
)

# A fixed reference instant so every case is deterministic.
NOW = datetime(2026, 6, 13, 7, 0, 0, tzinfo=timezone.utc)


def _series(
    *,
    days: int,
    value: float,
    recent: float | None = None,
    start_days_ago: int = 1,
) -> list[MetricSample]:
    """A daily series ending today: ``days`` baseline points at ``value`` plus
    one *most-recent* point at ``recent`` (defaults to ``value``).

    Sample ``i`` (0 = oldest) sits ``start_days_ago + days - i`` days before
    NOW, so the recent point is the freshest. Used to build HRV/RHR/sleep series
    with a controllable "today vs the trailing baseline" relationship.
    """
    out: list[MetricSample] = []
    for i in range(days):
        days_ago = start_days_ago + (days - i)
        out.append(MetricSample(at=NOW - timedelta(days=days_ago), value=value))
    out.append(
        MetricSample(
            at=NOW - timedelta(hours=8),
            value=recent if recent is not None else value,
        )
    )
    return out


def _inputs(
    *,
    hrv: list[MetricSample] | None = None,
    resting_hr: list[MetricSample] | None = None,
    sleep_hours: list[MetricSample] | None = None,
) -> ReadinessInputs:
    return ReadinessInputs(
        hrv=hrv or [],
        resting_hr=resting_hr or [],
        sleep_hours=sleep_hours or [],
    )


# --------------------------------------------------------------------------- #
# Insufficient data
# --------------------------------------------------------------------------- #


def test_no_metrics_is_insufficient_data() -> None:
    result = compute_readiness(_inputs(), now=NOW)
    assert result.insufficient_data is True
    assert result.score is None


def test_only_a_single_sample_with_no_baseline_is_insufficient() -> None:
    # One lone HRV reading and nothing to compare it to → we can't say if it's
    # high or low for this user, so we don't fake a number.
    one = [MetricSample(at=NOW - timedelta(hours=8), value=50.0)]
    result = compute_readiness(_inputs(hrv=one), now=NOW)
    assert result.insufficient_data is True
    assert result.score is None


def test_baseline_present_yields_a_score() -> None:
    result = compute_readiness(
        _inputs(hrv=_series(days=14, value=50.0)), now=NOW
    )
    assert result.insufficient_data is False
    assert result.score is not None
    assert 0.0 <= result.score <= 100.0


# --------------------------------------------------------------------------- #
# At baseline → neutral midpoint
# --------------------------------------------------------------------------- #


def test_at_baseline_on_every_metric_reads_neutral() -> None:
    # Today equals the trailing baseline on all three → the neutral midpoint.
    result = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0),
            resting_hr=_series(days=14, value=60.0),
            sleep_hours=_series(days=14, value=7.5),
        ),
        now=NOW,
    )
    assert result.score == pytest.approx(50.0, abs=1.0)


# --------------------------------------------------------------------------- #
# HRV: lower vs baseline → lower readiness (monotonic)
# --------------------------------------------------------------------------- #


def test_low_hrv_lowers_readiness() -> None:
    baseline = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0)), now=NOW
    ).score
    low = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0, recent=35.0)), now=NOW
    ).score
    assert baseline is not None and low is not None
    assert low < baseline


def test_high_hrv_raises_readiness() -> None:
    baseline = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0)), now=NOW
    ).score
    high = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0, recent=75.0)), now=NOW
    ).score
    assert baseline is not None and high is not None
    assert high > baseline


def test_hrv_sensitivity_is_monotonic() -> None:
    # As recent HRV falls further below baseline, readiness only ever drops.
    prev = None
    for recent in [70.0, 60.0, 55.0, 45.0, 35.0, 25.0]:
        score = compute_readiness(
            _inputs(hrv=_series(days=14, value=55.0, recent=recent)), now=NOW
        ).score
        assert score is not None
        if prev is not None:
            assert score <= prev
        prev = score


# --------------------------------------------------------------------------- #
# Resting HR: elevated vs baseline → lower readiness (monotonic)
# --------------------------------------------------------------------------- #


def test_elevated_resting_hr_lowers_readiness() -> None:
    baseline = compute_readiness(
        _inputs(resting_hr=_series(days=14, value=58.0)), now=NOW
    ).score
    elevated = compute_readiness(
        _inputs(resting_hr=_series(days=14, value=58.0, recent=70.0)), now=NOW
    ).score
    assert baseline is not None and elevated is not None
    assert elevated < baseline


def test_resting_hr_sensitivity_is_monotonic() -> None:
    # Higher recent RHR vs baseline → lower readiness, monotonically.
    prev = None
    for recent in [52.0, 56.0, 58.0, 64.0, 70.0, 78.0]:
        score = compute_readiness(
            _inputs(resting_hr=_series(days=14, value=58.0, recent=recent)),
            now=NOW,
        ).score
        assert score is not None
        if prev is not None:
            assert score <= prev
        prev = score


# --------------------------------------------------------------------------- #
# Sleep: poor vs baseline → lower readiness (monotonic)
# --------------------------------------------------------------------------- #


def test_poor_sleep_lowers_readiness() -> None:
    baseline = compute_readiness(
        _inputs(sleep_hours=_series(days=14, value=7.5)), now=NOW
    ).score
    poor = compute_readiness(
        _inputs(sleep_hours=_series(days=14, value=7.5, recent=4.5)), now=NOW
    ).score
    assert baseline is not None and poor is not None
    assert poor < baseline


def test_sleep_sensitivity_is_monotonic_below_baseline() -> None:
    prev = None
    for recent in [8.0, 7.5, 6.5, 5.5, 4.5, 3.5]:
        score = compute_readiness(
            _inputs(sleep_hours=_series(days=14, value=7.5, recent=recent)),
            now=NOW,
        ).score
        assert score is not None
        if prev is not None:
            assert score <= prev
        prev = score


# --------------------------------------------------------------------------- #
# Metrics combine
# --------------------------------------------------------------------------- #


def test_all_three_depressed_reads_lower_than_one_depressed() -> None:
    only_hrv = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0, recent=35.0),
            resting_hr=_series(days=14, value=58.0),
            sleep_hours=_series(days=14, value=7.5),
        ),
        now=NOW,
    ).score
    all_three = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0, recent=35.0),
            resting_hr=_series(days=14, value=58.0, recent=70.0),
            sleep_hours=_series(days=14, value=7.5, recent=4.5),
        ),
        now=NOW,
    ).score
    assert only_hrv is not None and all_three is not None
    assert all_three < only_hrv


def test_missing_metric_drops_out_of_the_blend() -> None:
    # HRV-only (no RHR/sleep) still yields a score, and a low HRV there lowers it
    # — the absent metrics simply don't contribute rather than breaking the core.
    baseline = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0)), now=NOW
    )
    low = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0, recent=30.0)), now=NOW
    )
    assert baseline.insufficient_data is False
    assert low.score is not None and baseline.score is not None
    assert low.score < baseline.score


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #


def test_score_is_bounded_even_for_extreme_inputs() -> None:
    crashed = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=80.0, recent=1.0),
            resting_hr=_series(days=14, value=50.0, recent=200.0),
            sleep_hours=_series(days=14, value=8.0, recent=0.0),
        ),
        now=NOW,
    )
    soaring = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=40.0, recent=300.0),
            resting_hr=_series(days=14, value=70.0, recent=30.0),
            sleep_hours=_series(days=14, value=5.0, recent=12.0),
        ),
        now=NOW,
    )
    assert crashed.score is not None and 0.0 <= crashed.score <= 100.0
    assert soaring.score is not None and 0.0 <= soaring.score <= 100.0
    # The crashed reading must be clearly poor; the soaring one clearly strong.
    assert crashed.score < 25.0
    assert soaring.score > 75.0


# --------------------------------------------------------------------------- #
# The components are reported (for the "why this number" UI)
# --------------------------------------------------------------------------- #


def test_components_report_which_metrics_were_used() -> None:
    result = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0, recent=35.0),
            sleep_hours=_series(days=14, value=7.5),
        ),
        now=NOW,
    )
    keys = {c.metric for c in result.components}
    assert "hrv" in keys
    assert "sleep_hours" in keys
    assert "resting_hr" not in keys  # absent metric isn't reported
    hrv_component = next(c for c in result.components if c.metric == "hrv")
    # Recent HRV well below baseline → the component direction is "below".
    assert hrv_component.recent < hrv_component.baseline


def test_band_label_tracks_score() -> None:
    poor = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0, recent=20.0),
            resting_hr=_series(days=14, value=58.0, recent=75.0),
            sleep_hours=_series(days=14, value=7.5, recent=3.5),
        ),
        now=NOW,
    )
    strong = compute_readiness(
        _inputs(
            hrv=_series(days=14, value=55.0, recent=80.0),
            resting_hr=_series(days=14, value=58.0, recent=48.0),
            sleep_hours=_series(days=14, value=7.5, recent=9.0),
        ),
        now=NOW,
    )
    assert poor.band == "low"
    assert strong.band == "high"


# --------------------------------------------------------------------------- #
# Recency: only the most recent reading is "today"; the rest form the baseline
# --------------------------------------------------------------------------- #


def test_naive_and_aware_now_agree() -> None:
    aware = compute_readiness(
        _inputs(hrv=_series(days=14, value=55.0, recent=35.0)), now=NOW
    ).score
    naive_inputs = _inputs(
        hrv=[
            MetricSample(at=s.at.replace(tzinfo=None), value=s.value)
            for s in _series(days=14, value=55.0, recent=35.0)
        ]
    )
    naive = compute_readiness(naive_inputs, now=NOW.replace(tzinfo=None)).score
    assert aware is not None and naive is not None
    assert aware == pytest.approx(naive)
