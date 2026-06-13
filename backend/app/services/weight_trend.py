"""Weight-trend smoother — de-noised "true weight" + rate of change (#23, ADR-0004).

The Budget (#23) is *self-calibrating against the observed weight trend* — never a
static formula (CONTEXT.md "Budget"). Raw scale weight swings 1-2% of bodyweight
day-to-day on water, food and glycogen alone, so calibrating against the last raw
reading would be chasing noise. This module turns a noisy daily BodyMass series
into the robust signal the Budget reconciles against:

* a **de-noised "true weight"** — a time-aware exponential moving average (EMA),
  so a single heavy or light morning barely moves it; and
* a **rate of change** in kg/week and %bodyweight/week — the slope of the
  smoothed series, the number that (with intake) reveals a surplus or deficit.

Like :mod:`app.services.readiness` / :mod:`app.services.recovery` this is a
**pure** module: no DB, no clock, no I/O. The reference ``now`` and the samples
are injected; the query layer (:mod:`app.services.budget_query`) reads
``health_records`` BodyMass rows and feeds them in. That keeps the model
deterministic and trivially unit-testable.

The model
=========
1. **Window.** Only samples within :data:`_DEFAULT_WINDOW_DAYS` before ``now`` are
   used — the *current* trend, not ancient history. With no in-window sample the
   result is an explicit ``insufficient_data`` state (never a stale number).

2. **Time-aware EMA for true weight.** We fold the in-window samples oldest→newest
   into an EMA. The smoothing is expressed as a **half-life in days**
   (:data:`_HALFLIFE_DAYS`), not a per-sample factor, so *irregular* sampling is
   handled correctly: a sample ``dt`` days after the previous one decays the old
   estimate by ``0.5 ** (dt / halflife)`` before blending the new reading in. Two
   weigh-ins a week apart and fourteen daily weigh-ins both behave sensibly — the
   weight given to history depends on *elapsed time*, not sample count. The final
   EMA value is the "true weight".

3. **Rate from a least-squares slope of the raw samples.** Ordinary least-squares
   is itself the standard noise-robust trend estimator — it fits the line that
   minimises squared residuals, so symmetric day-to-day noise averages out and the
   recovered slope is the underlying trend. We fit ``value`` against time-in-days
   over the in-window readings and take the slope (kg/day → ×7 for kg/week); with
   exactly two readings it reduces to the exact slope between them. We regress the
   *raw* series (not the EMA) deliberately: the EMA lags the trend by a roughly
   constant offset, which would flatten the apparent slope — the EMA is the right
   tool for a current *level* (the true weight) but the wrong one for a *rate*.
   ``%BW/week`` is the kg/week rate over the current true weight.

A single in-window reading yields a true weight (it's the only data) but **no
rate** — one point can't define a trend, and we say so rather than guessing.

Why this shape (and what it is deliberately not)
================================================
EMA-for-true-weight + slope-for-rate is the well-worn approach of weight-trend
trackers (the "Hacker's Diet" trend line, Libra, Happy Scale): simple,
inspectable, and robust to the dominant noise source. It is a v1 — a fixed
half-life and a plain OLS slope. A Kalman filter, an adaptive half-life, or
outlier rejection are obvious future refinements but unnecessary for a defensible
first signal (YAGNI). Every constant lives at the top — the single place to
retune the smoother.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --------------------------------------------------------------------------- #
# Tunable model constants — the single place to retune the smoother. See the
# module docstring for the reasoning behind each default.
# --------------------------------------------------------------------------- #

#: Trailing window (days) the *current* trend is computed over. 28 days (4 weeks)
#: matches the Readiness baseline window and is long enough to average out a
#: week's water/food noise while still tracking a real cut/bulk.
_DEFAULT_WINDOW_DAYS = 28

#: EMA half-life in days: how long until a reading's weight in the average halves.
#: ~10 days gives a trend line that lags the raw series enough to kill day-to-day
#: noise but still turns within a couple of weeks of a genuine change of direction
#: (the classic weight-trend-tracker feel).
_HALFLIFE_DAYS = 10.0

#: Days/week — the rate is reported per week (kg/week, %BW/week).
_DAYS_PER_WEEK = 7.0


@dataclass(frozen=True)
class WeightSample:
    """One timestamped bodyweight reading (the pure-core input unit).

    The query layer builds these from ``health_records`` BodyMass rows. ``value``
    is in kilograms (the query layer normalises the stored unit if needed).
    """

    at: datetime
    value: float


@dataclass(frozen=True)
class WeightTrend:
    """The de-noised weight trend result.

    ``insufficient_data`` is true (and every field ``None``) when there is no
    reading inside the window — we report that honestly rather than inventing a
    number. Otherwise ``true_weight_kg`` is the smoothed current weight; the two
    ``rate_*`` fields are the trend's slope (``None`` when only a single in-window
    reading exists — a point can't define a trend). ``n_samples`` is how many
    in-window readings backed the result (for the UI's confidence hint).
    """

    true_weight_kg: float | None
    rate_kg_per_week: float | None
    rate_pct_per_week: float | None
    insufficient_data: bool
    n_samples: int = 0


def _days_between(a: datetime, b: datetime) -> float:
    """Signed days from ``a`` to ``b`` (``b`` later ⇒ positive)."""
    return (b - a).total_seconds() / 86400.0


def _ema(ordered: list[WeightSample]) -> float:
    """Time-aware EMA over time-ascending samples → the smoothed current value.

    Each step decays the running estimate by ``0.5 ** (dt / halflife)`` for the
    ``dt`` days since the previous sample, then blends the new reading in with the
    complementary weight. Equal daily spacing reduces to a standard EMA; uneven
    spacing weights history by elapsed time, so gaps are handled correctly.
    """
    ema = ordered[0].value
    prev_at = ordered[0].at
    for s in ordered[1:]:
        dt_days = max(0.0, _days_between(prev_at, s.at))
        # Weight retained by the *old* estimate over this gap (→0 as the gap grows).
        decay = 0.5 ** (dt_days / _HALFLIFE_DAYS)
        ema = decay * ema + (1.0 - decay) * s.value
        prev_at = s.at
    return ema


def _raw_series(ordered: list[WeightSample]) -> list[tuple[float, float]]:
    """``(day_offset_since_first, raw_value)`` points for the rate regression.

    ``day_offset`` (the regression's x) is days since the first in-window sample.
    We regress the *raw* values, not the EMA: OLS already averages out symmetric
    noise to recover the trend slope, whereas the EMA's lag would flatten it.
    """
    t0 = ordered[0].at
    return [(_days_between(t0, s.at), s.value) for s in ordered]


def _ols_slope(points: list[tuple[float, float]]) -> float | None:
    """Ordinary-least-squares slope (Δy per Δx) of ``(x, y)`` points, or None.

    ``None`` when fewer than two points or all x are identical (no time spread to
    define a slope). With exactly two points this is the exact slope between them.
    """
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    if sxx <= 0.0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return sxy / sxx


def compute_weight_trend(
    samples: list[WeightSample],
    *,
    now: datetime,
    window_days: int = _DEFAULT_WINDOW_DAYS,
) -> WeightTrend:
    """De-noise a bodyweight series into a true weight + a rate of change.

    Keeps only readings within ``window_days`` before ``now`` (the current trend),
    smooths them with a time-aware EMA into ``true_weight_kg``, and takes the
    least-squares slope of the smoothed series as the rate (kg/week and %BW/week).
    Returns an ``insufficient_data`` result when no reading is in the window, and a
    weight-but-no-rate result when only one reading is. ``now`` is injected so a
    fixed series yields a fixed trend.
    """
    window_start = now.timestamp() - window_days * 86400.0
    in_window = [s for s in samples if s.at.timestamp() >= window_start]

    if not in_window:
        return WeightTrend(
            true_weight_kg=None,
            rate_kg_per_week=None,
            rate_pct_per_week=None,
            insufficient_data=True,
            n_samples=0,
        )

    ordered = sorted(in_window, key=lambda s: s.at)

    true_weight = _ema(ordered)

    if len(ordered) < 2:
        # One reading: we know the weight, but a single point can't define a trend.
        return WeightTrend(
            true_weight_kg=true_weight,
            rate_kg_per_week=None,
            rate_pct_per_week=None,
            insufficient_data=False,
            n_samples=1,
        )

    slope_per_day = _ols_slope(_raw_series(ordered))
    if slope_per_day is None:
        # All readings landed at the same instant — no time spread for a rate.
        return WeightTrend(
            true_weight_kg=true_weight,
            rate_kg_per_week=None,
            rate_pct_per_week=None,
            insufficient_data=False,
            n_samples=len(ordered),
        )

    rate_kg_week = slope_per_day * _DAYS_PER_WEEK
    rate_pct_week = (
        rate_kg_week / true_weight * 100.0 if true_weight not in (0.0, None) else None
    )
    return WeightTrend(
        true_weight_kg=true_weight,
        rate_kg_per_week=rate_kg_week,
        rate_pct_per_week=rate_pct_week,
        insufficient_data=False,
        n_samples=len(ordered),
    )
