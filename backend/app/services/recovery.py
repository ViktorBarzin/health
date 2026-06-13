"""Recovery: per-muscle freshness computed from recent training load.

CONTEXT.md ("Recovery"): "The per-muscle freshness score computed from recent
Set history; steers exercise selection away from still-fatigued muscles." It is
the inverse of fatigue on one 0–100 scale (100 = fully recovered/fresh, low =
recently/heavily trained). ADR-0002 fixes this as a **deterministic, explainable**
core; this slice (#10) builds it and the Recommendation generator (#11) consumes
it. Like :mod:`app.services.e1rm`/:mod:`app.services.volume`, it is a **pure**
module — no DB, no clock — so it is trivially unit-testable and reusable; the
querying layer (``api/analytics.py``) builds its inputs from ``training_sets`` ⋈
``exercise_muscles`` and injects the reference time.

The model
=========
Training a muscle accrues **fatigue** that **decays exponentially over time**.
This is the same "training load + recency only" model the recovery-aware market
leader (Fitbod) uses — verified to use *no* biometric input (HRV/sleep/RHR);
biometric Readiness is a separate, later signal (#14, ADR-0004). The steps:

1. **Attribute load to muscles.** Each *normal* Set's volume-load (``weight ×
   reps`` — the proxy owned by :mod:`app.services.volume`) is credited to the
   muscles it works, via the ``exercise_muscles`` mapping. A **primary** mover
   takes the full load; a **secondary** mover takes a documented fraction
   (:data:`SECONDARY_WEIGHT` = 0.5) — secondary movers do real but lesser work,
   the standard half-credit convention used across volume-landmark guidance
   (e.g. Schoenfeld/Israetel "counting sets" — secondary ≈ half a set). Non-normal
   Sets (warmup/drop/failure) contribute nothing (the same exclusion
   :func:`app.services.volume.counts_for_volume` owns).

2. **Decay each contribution by time.** A contribution performed ``h`` hours ago
   is scaled by ``0.5 ** (h / HALF_LIFE)`` — an exponential decay with a
   **half-life** of :data:`DEFAULT_HALF_LIFE_HOURS` = 48 h. 48 h sits in the
   well-documented 48–72 h muscle-protein-synthesis / DOMS recovery window for a
   trained muscle group and is the conservative low end (faster perceived
   recovery → the engine re-suggests a muscle sooner; the user's own logging and
   Effort keep it honest). One global half-life is a deliberate v1 simplification
   — per-muscle half-lives (legs recover slower than arms) are an obvious future
   refinement but unnecessary for a defensible first model (YAGNI).

3. **Sum and normalise to a recovery %.** Per muscle, total decayed fatigue
   ``F`` maps to a recovery score with a saturating exponential::

       recovery% = 100 · exp(−F / FATIGUE_SCALE)

   This has exactly the properties the engine needs (all asserted in
   :mod:`tests.test_recovery`): an untrained muscle (``F = 0``) is exactly
   **100%**; recovery is **strictly decreasing in fatigue** (more/heavier/more-
   recent load ⇒ lower), **monotonically increasing back toward 100 as time
   passes** (``F`` decays), and **bounded in ``[0, 100]``** for any load (it
   asymptotes to 0, never negative). :data:`DEFAULT_FATIGUE_SCALE` sets where a
   "normal hard session" lands: with the default, a single fresh ~5000 kg·rep
   primary session reads roughly half-recovered (~49%), a typical ~2500 kg·rep
   session reads ~70% fresh, and fatigue keeps decaying back toward 100% over the
   following days — tunable in one place if real data says otherwise.

All three tunable constants live here, at the top, with the reasoning above.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.models.training_session import SetType
from app.services.volume import counts_for_volume

# --------------------------------------------------------------------------- #
# Tunable model constants — the single place to retune Recovery. See the module
# docstring for the reasoning behind each default.
# --------------------------------------------------------------------------- #

#: Half-life of training fatigue, in hours. A contribution loses half its weight
#: every HALF_LIFE hours. 48 h ≈ the conservative end of the 48–72 h recovery
#: window for a trained muscle group.
DEFAULT_HALF_LIFE_HOURS: float = 48.0

#: Fraction of a Set's volume-load credited to a *secondary* mover (a primary
#: mover takes the full 1.0). Secondary muscles do real but lesser work — the
#: standard "half a set" counting convention.
SECONDARY_WEIGHT: float = 0.5

#: Normalisation scale (in volume-load units) mapping summed decayed fatigue to a
#: recovery %. Larger ⇒ a given load reads as *more* recovered. Chosen so a single
#: hard ~5000 kg·rep primary session reads ≈ half-recovered when fresh.
DEFAULT_FATIGUE_SCALE: float = 7000.0

#: Recovery is reported as a percentage on this scale.
_FULL_RECOVERY: float = 100.0


@dataclass(frozen=True)
class MuscleSetLoad:
    """One Set's volume-load already attributed to one muscle, with its role.

    The pure-core input unit: the querying layer expands each Set into one of
    these per muscle the Set's Exercise maps to (via ``exercise_muscles``), so
    this module never touches the ORM. ``volume_load`` is ``weight × reps`` for
    the Set (the caller may pass the raw load for every Set — non-normal ones are
    filtered here by ``set_type`` so the exclusion stays owned by
    :func:`app.services.volume.counts_for_volume`). ``role`` is the muscle's role
    for that Exercise (``"primary"`` / ``"secondary"`` — the ``muscle_role`` enum
    values).
    """

    muscle: str
    role: str
    performed_at: datetime
    volume_load: float
    set_type: SetType = SetType.normal


def _elapsed_hours(now: datetime, performed_at: datetime) -> float:
    """Hours between ``performed_at`` and ``now`` (clamped at 0 for future sets).

    Tolerates a mix of naive and aware datetimes by dropping tzinfo when only one
    side carries it — the math is on elapsed wall-clock hours, and the caller
    controls both values' convention.
    """
    a, b = now, performed_at
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    seconds = (a - b).total_seconds()
    return max(0.0, seconds / 3600.0)


def _decay(hours: float, half_life_hours: float) -> float:
    """Exponential time-decay factor in ``[0, 1]``: ``0.5 ** (hours / half_life)``."""
    return 0.5 ** (hours / half_life_hours)


def _role_weight(role: str) -> float:
    """Load fraction for a muscle role: 1.0 primary, SECONDARY_WEIGHT secondary."""
    return SECONDARY_WEIGHT if role == "secondary" else 1.0


def muscle_fatigue(
    loads: Iterable[MuscleSetLoad],
    *,
    now: datetime,
    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
) -> dict[str, float]:
    """Total time-decayed, role-weighted fatigue per muscle.

    The raw, un-normalised accumulator behind :func:`muscle_recovery`, exposed so
    the Recommendation engine (or debugging/analytics) can read fatigue directly
    on the same scale as ``volume_load``. Only ``normal`` Sets contribute; muscles
    with no contribution are simply absent from the result (fatigue 0).
    """
    fatigue: dict[str, float] = {}
    for load in loads:
        if not counts_for_volume(load.set_type):
            continue
        hours = _elapsed_hours(now, load.performed_at)
        contribution = (
            load.volume_load
            * _role_weight(load.role)
            * _decay(hours, half_life_hours)
        )
        if contribution <= 0.0:
            continue
        fatigue[load.muscle] = fatigue.get(load.muscle, 0.0) + contribution
    return fatigue


def fatigue_to_recovery(fatigue: float, *, fatigue_scale: float) -> float:
    """Map summed decayed fatigue to a recovery % in ``[0, 100]``.

    ``recovery = 100 · exp(−fatigue / scale)``: 100 at zero fatigue, strictly
    decreasing, asymptotically 0 (never negative) for unbounded load.
    """
    if fatigue <= 0.0:
        return _FULL_RECOVERY
    return _FULL_RECOVERY * math.exp(-fatigue / fatigue_scale)


def muscle_recovery(
    loads: Iterable[MuscleSetLoad],
    *,
    now: datetime,
    half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
    fatigue_scale: float = DEFAULT_FATIGUE_SCALE,
) -> dict[str, float]:
    """Per-muscle recovery score (0–100) from attributed Set loads.

    Returns one entry per muscle that carries *any* fatigue from a normal Set.
    A muscle absent from the result has no recent training load and is fully
    recovered — callers treat "absent" as ``100.0`` (the heatmap/engine fill
    untrained muscles green). ``now`` is injected so the function is a pure,
    deterministic mapping of its inputs.
    """
    fatigue = muscle_fatigue(loads, now=now, half_life_hours=half_life_hours)
    return {
        muscle: fatigue_to_recovery(f, fatigue_scale=fatigue_scale)
        for muscle, f in fatigue.items()
    }
