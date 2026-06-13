"""Readiness: the daily biometric 0–100 signal (#14, ADR-0004).

CONTEXT.md ("Readiness"): "A daily per-user signal derived from HRV, resting
heart rate, and sleep trends; an input the engine may weigh, and a dashboard
insight in its own right." It is **distinct from Recovery** (#10): Recovery is
per-muscle training-load freshness from Set history; Readiness is the whole-body
*biometric* state from wearable data (HRV / resting HR / sleep). The recovery-
aware market leader (Fitbod) uses *no* biometric input at all — so this signal
is a deliberate differentiator (ADR-0004).

Like :mod:`app.services.recovery` this is a **pure** module — no DB, no clock,
no IO. The reference "now" and the metric samples are injected; the query layer
(:mod:`app.services.readiness_query`) reads ``health_records`` /
``category_records`` and feeds them in. That keeps the model deterministic and
trivially unit-testable.

The model
=========
The principle is **compare today to the user's own recent baseline**, not to a
population norm — what matters is the *deviation* from where this person usually
sits. For each available metric we:

1. Split the daily series into the **most-recent** reading ("today") and the
   **trailing baseline** (every earlier reading). A metric needs at least one
   baseline reading *and* a recent one to be usable — otherwise we can't say
   whether today is high or low *for this user*, so we don't fake a number.

2. Compute a **robust deviation**: ``(recent − baseline_mean) / spread`` where
   ``spread`` is the baseline standard deviation, floored at a fraction of the
   mean so a metric with a freakishly steady baseline doesn't make a tiny
   absolute change look enormous (:data:`_MIN_SPREAD_FRACTION`). The deviation
   is signed in the metric's *natural* direction, then oriented so **positive =
   better readiness**:

   * **HRV** — higher than baseline is better (parasympathetic recovery), so the
     deviation is used as-is.
   * **Resting heart rate** — higher than baseline is *worse* (sympathetic
     stress / incomplete recovery), so the deviation is negated.
   * **Sleep** — less than baseline is worse; *more* than baseline is good but
     **saturating** (sleeping 10h when you usually get 7.5h doesn't make you
     superhuman) — positive deviations are dampened by
     :data:`_SLEEP_SURPLUS_DAMPEN` while shortfalls count in full.

3. Map each oriented deviation through a **logistic squash** to a 0–100
   component score centred at 50 (at-baseline ⇒ 50, better ⇒ →100, worse ⇒ →0).
   The logistic is smooth and bounded, giving the monotonic, saturating
   sensitivity the engine wants without a hard clip.

4. **Blend** the available component scores with documented weights
   (:data:`_WEIGHTS`), renormalised over whichever metrics are present — so a
   missing metric simply drops out rather than dragging the score to zero, and
   an HRV-only user still gets a defensible number. With *no* usable metric the
   result is an explicit ``insufficient_data`` state.

Every weight, the window split, the spread floor and the squash steepness live
at the top as documented constants — the single place to retune Readiness.

Why this shape (and what it deliberately is *not*)
==================================================
This mirrors the consumer-wearable convention (Whoop/Oura-style "recovery" /
"readiness" rings are HRV-led, RHR- and sleep-adjusted, baseline-relative) while
staying a simple, inspectable formula rather than an opaque model. It is a v1:
one global window, a logistic per metric, fixed weights. Per-metric windows,
sleep-stage detail, or a learned model are obvious future refinements but
unnecessary for a defensible first signal (YAGNI).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

# --------------------------------------------------------------------------- #
# Tunable model constants — the single place to retune Readiness. See the module
# docstring for the reasoning behind each default.
# --------------------------------------------------------------------------- #

#: Blend weights for the three biometric components. HRV leads (the most
#: responsive autonomic-recovery signal), resting HR and sleep adjust it. Weights
#: are renormalised over whichever metrics are actually present, so these are
#: *relative* importances, not absolutes.
_WEIGHTS: dict[str, float] = {
    "hrv": 0.5,
    "resting_hr": 0.25,
    "sleep_hours": 0.25,
}

#: Steepness of the logistic mapping an oriented baseline-deviation (in spread
#: units) to a 0–100 component. At ~1.0 a one-spread deviation lands near the
#: 73/27 marks — a clear but not saturated move; larger = more sensitive.
_SQUASH_STEEPNESS: float = 1.0

#: Floor on a metric's baseline spread, as a fraction of its baseline mean. A
#: metric with a near-constant baseline gets a sensible minimum spread so a small
#: absolute change isn't read as a huge deviation. (e.g. 0.05 ⇒ spread is at
#: least 5% of the mean.)
_MIN_SPREAD_FRACTION: float = 0.05

#: Sleep *surplus* (more than baseline) is good but saturating — extra hours
#: beyond your norm help far less than a shortfall hurts. Positive sleep
#: deviations are scaled by this; shortfalls count in full.
_SLEEP_SURPLUS_DAMPEN: float = 0.4

#: Band thresholds on the 0–100 score for the human label.
_LOW_BAND_MAX: float = 40.0
_HIGH_BAND_MIN: float = 65.0

#: The neutral midpoint a perfectly at-baseline day reads.
_NEUTRAL: float = 50.0


@dataclass(frozen=True)
class MetricSample:
    """One timestamped reading of a biometric metric (HRV, RHR, or sleep hours).

    The pure-core input unit — the query layer builds these from
    ``health_records`` (HRV/RHR) and the sleep aggregation. ``value`` is in the
    metric's natural unit (ms for HRV SDNN, bpm for resting HR, hours for sleep).
    """

    at: datetime
    value: float


@dataclass(frozen=True)
class ReadinessInputs:
    """The biometric series feeding one Readiness computation.

    Each is a list of daily-ish samples; the core picks the most-recent as
    "today" and the rest as the trailing baseline. Any may be empty (that metric
    drops out of the blend).
    """

    hrv: list[MetricSample] = field(default_factory=list)
    resting_hr: list[MetricSample] = field(default_factory=list)
    sleep_hours: list[MetricSample] = field(default_factory=list)


@dataclass(frozen=True)
class ReadinessComponent:
    """One metric's contribution to the score, for the "why this number" UI.

    ``recent`` is today's reading, ``baseline`` the trailing mean, ``score`` the
    metric's own 0–100 sub-score, and ``weight`` its (renormalised) blend weight.
    ``direction`` is ``"above"`` / ``"below"`` / ``"at"`` baseline in the metric's
    natural sense (so the UI can say "HRV below your baseline").
    """

    metric: str
    recent: float
    baseline: float
    score: float
    weight: float
    direction: str


@dataclass(frozen=True)
class Readiness:
    """The daily Readiness result.

    ``insufficient_data`` is true (and ``score``/``band`` are ``None``) when no
    metric had both a recent reading and a baseline — we report that honestly
    rather than inventing a number. Otherwise ``score`` is the 0–100 blend and
    ``band`` is its human label (``low`` / ``moderate`` / ``high``).
    """

    score: float | None
    band: str | None
    insufficient_data: bool
    components: tuple[ReadinessComponent, ...] = ()


# Per-metric orientation: ``+1`` ⇒ above-baseline is *better* readiness, ``-1`` ⇒
# above-baseline is *worse*. (HRV up = good; resting HR up = bad; sleep up = good.)
_ORIENTATION: dict[str, int] = {"hrv": +1, "resting_hr": -1, "sleep_hours": +1}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stddev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _logistic(x: float) -> float:
    """Standard logistic squash to ``(0, 1)`` — smooth, monotone, saturating."""
    # Clamp the exponent to avoid overflow on extreme deviations.
    z = max(-60.0, min(60.0, _SQUASH_STEEPNESS * x))
    return 1.0 / (1.0 + math.exp(-z))


def _split(samples: list[MetricSample]) -> tuple[float, list[float]] | None:
    """Most-recent value + the earlier baseline values, or ``None`` if unusable.

    A metric needs a recent reading *and* at least one earlier (baseline)
    reading. Samples are ordered by time here (the caller need not pre-sort), so
    the core is robust to input ordering.
    """
    if len(samples) < 2:
        return None
    ordered = sorted(samples, key=lambda s: s.at)
    recent = ordered[-1].value
    baseline = [s.value for s in ordered[:-1]]
    return recent, baseline


def _component(metric: str, samples: list[MetricSample]) -> ReadinessComponent | None:
    """Score one metric vs its own trailing baseline, or ``None`` if unusable."""
    split = _split(samples)
    if split is None:
        return None
    recent, baseline_values = split
    baseline_mean = _mean(baseline_values)

    spread = _stddev(baseline_values, baseline_mean)
    min_spread = abs(baseline_mean) * _MIN_SPREAD_FRACTION
    spread = max(spread, min_spread)
    if spread <= 0.0:
        # Degenerate baseline (mean 0, no variance) — treat today as exactly at
        # baseline so we still emit a neutral component rather than dividing by 0.
        deviation = 0.0
    else:
        deviation = (recent - baseline_mean) / spread

    # Orient so positive = better readiness.
    oriented = deviation * _ORIENTATION[metric]
    # Sleep surplus saturates: dampen the *good* direction only.
    if metric == "sleep_hours" and oriented > 0.0:
        oriented *= _SLEEP_SURPLUS_DAMPEN

    score = 100.0 * _logistic(oriented)

    if recent > baseline_mean:
        direction = "above"
    elif recent < baseline_mean:
        direction = "below"
    else:
        direction = "at"

    return ReadinessComponent(
        metric=metric,
        recent=recent,
        baseline=baseline_mean,
        score=score,
        weight=_WEIGHTS[metric],
        direction=direction,
    )


def _band(score: float) -> str:
    """Human label for a 0–100 score."""
    if score < _LOW_BAND_MAX:
        return "low"
    if score >= _HIGH_BAND_MIN:
        return "high"
    return "moderate"


def compute_readiness(inputs: ReadinessInputs, *, now: datetime) -> Readiness:
    """Compute the daily Readiness signal from biometric series.

    For each metric with a recent reading and a baseline, score today against
    that baseline (oriented so higher = better), then blend the available scores
    with renormalised weights. Returns an ``insufficient_data`` result when no
    metric is usable — never a fabricated number. ``now`` is injected for
    determinism (it is not currently used for filtering — the caller windows the
    series — but is part of the pure-core contract and reserved for future
    recency weighting).
    """
    raw = {
        "hrv": inputs.hrv,
        "resting_hr": inputs.resting_hr,
        "sleep_hours": inputs.sleep_hours,
    }
    components: list[ReadinessComponent] = []
    for metric, samples in raw.items():
        component = _component(metric, samples)
        if component is not None:
            components.append(component)

    if not components:
        return Readiness(score=None, band=None, insufficient_data=True)

    total_weight = sum(c.weight for c in components)
    # Renormalise so present metrics' weights sum to 1.
    renormalised = tuple(
        ReadinessComponent(
            metric=c.metric,
            recent=c.recent,
            baseline=c.baseline,
            score=c.score,
            weight=c.weight / total_weight,
            direction=c.direction,
        )
        for c in components
    )
    score = sum(c.score * c.weight for c in renormalised)
    score = max(0.0, min(100.0, score))
    return Readiness(
        score=score,
        band=_band(score),
        insufficient_data=False,
        components=renormalised,
    )
