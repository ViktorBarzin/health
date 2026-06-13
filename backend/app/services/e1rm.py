"""Estimated 1-rep-max (e1RM): a pure strength-comparison core.

Lifting sets are logged at all sorts of (weight × reps); to compare them on one
axis — "was this set stronger than that one?" — we estimate the one-rep-max each
set implies. This module is the single canonical e1RM definition for the whole
platform: PR detection (#8), e1RM trend analytics (#10) and the Progression
generator (#11) all import it so they never diverge.

Formula — **Epley** (1985), the most widely used estimator. The textbook form is
``w·(1 + reps/30)``, which returns ``w·31/30`` (not ``w``) at a single rep. We use
the equivalent **1-rep-anchored** form so a single is *exactly* its own 1RM::

    1RM = w · (1 + (reps - 1) / 30)

The two forms differ only by the constant offset of one rep; both are smooth and
strictly increasing in weight and reps. Anchoring at ``reps == 1`` is what every
lifting tracker does and is the boundary this engine's PR/analytics consumers
rely on (a logged single must register as a weight PR at its own value, not
1.033× it). (Brzycki is the common alternative but diverges sharply past ~10 reps
and is undefined at 37 reps; for a general-purpose progression signal Epley's
monotonicity is the safer base.)

Effort adjustment (optional)
----------------------------
A set left with reps **in reserve** (RIR) is heavier than its rep count alone
suggests — if you stop at 5 reps with 3 left in the tank, your true capacity is
nearer an 8-rep max. We fold Effort in the standard, documented way: add the RIR
to the rep count before applying Epley (``effective_reps = reps + rir``). This is
the same idea as the Epley-on-"reps-to-failure" convention. Consequences, all
asserted in the tests:

* RIR 0 (taken to failure) or ``None`` (not rated) ⇒ no change — the plain Epley
  result, so unrated sets are never penalised or inflated;
* the adjustment is monotonic in reserve and **never lowers** the estimate.

Effort travels the platform as RIR (the one-tap chip — see
:mod:`app.services.effort`); e1RM consumes that native RIR directly rather than
round-tripping through the stored RPE, so it stays a clean pure function of the
quantities a Set actually records.
"""

# Epley's denominator constant. Pulled out so the one formula lives in one place.
_EPLEY_DIVISOR = 30.0


def epley_1rm(weight_kg: float, reps: int) -> float:
    """Raw Epley estimate for ``weight_kg`` lifted for ``reps`` reps.

    Returns the weight unchanged at ``reps == 1``; ``0.0`` if either input is
    zero (no load or no completed reps imply no strength estimate).

    Raises:
        ValueError: if ``weight_kg`` or ``reps`` is negative.
    """
    if weight_kg < 0:
        raise ValueError(f"weight_kg must be >= 0, got {weight_kg}")
    if reps < 0:
        raise ValueError(f"reps must be >= 0, got {reps}")
    if weight_kg == 0 or reps == 0:
        return 0.0
    # 1-rep-anchored Epley: (reps - 1) so a single returns the weight exactly.
    return weight_kg * (1.0 + (reps - 1) / _EPLEY_DIVISOR)


def estimated_1rm(weight_kg: float, reps: int, rir: int | None = None) -> float:
    """Estimated 1RM for a Set, optionally adjusted for reps in reserve.

    ``rir`` is the one-tap Effort value (reps left in the tank). A positive RIR
    makes the set effectively heavier — ``effective_reps = reps + rir`` before
    Epley — so the estimate rises and never falls. ``rir`` of ``0`` (to failure)
    or ``None`` (not rated) leaves the plain Epley result untouched.

    Raises:
        ValueError: if ``weight_kg``/``reps`` is negative, or ``rir`` is negative.
    """
    if rir is not None and rir < 0:
        raise ValueError(f"rir must be >= 0, got {rir}")
    effective_reps = reps + (rir or 0)
    return epley_1rm(weight_kg, effective_reps)
