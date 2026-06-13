"""Effort: the one-tap reps-in-reserve (RIR) rating on a Set.

CONTEXT.md ("Effort"): a one-tap reps-in-reserve rating (0 / 1 / 2 / 3 / 4+ —
"how many more reps were left?"), optional on every Set, nudged on an Exercise's
last Set, **stored as the RPE-equivalent**. We avoid the word "RPE" in the UI but
persist the RPE number so the Progression engine (a later slice) reads one
canonical effort scale.

The mapping is the standard RIR→RPE inversion (Zourdos 2016): the closer to
failure (fewer reps in reserve), the higher the RPE.

    RIR 0  → RPE 10   (failure — no reps left)
    RIR 1  → RPE 9
    RIR 2  → RPE 8
    RIR 3  → RPE 7
    RIR 4+ → RPE 6     (4 or more reps left; the "easy" floor of the one-tap chip)

The chip surfaces five buckets only; "4+" is the open-ended bottom, so RIR 4
*and beyond* collapse to a single RPE-6 floor. There is no finer resolution by
design — it is a one-tap rating, not a slider.
"""

# The five selectable RIR buckets, in chip order (hardest → easiest). "4+" is
# represented by the integer 4 (its open-ended floor); the UI labels it "4+".
RIR_VALUES: tuple[int, ...] = (0, 1, 2, 3, 4)

# RPE that each RIR bucket stores. RPE = 10 - RIR, floored at 6 for the 4+ bucket.
_RIR_TO_RPE: dict[int, float] = {0: 10.0, 1: 9.0, 2: 8.0, 3: 7.0, 4: 6.0}


def rir_to_rpe(rir: int | None) -> float | None:
    """Map a one-tap RIR bucket to its stored RPE-equivalent.

    ``None`` (no Effort tapped) maps to ``None`` — Effort is always optional and
    is never inferred. Any RIR >= 4 collapses to the 4+ floor (RPE 6), matching
    the open-ended bottom chip; negative RIR is invalid.

    Raises:
        ValueError: if ``rir`` is negative.
    """
    if rir is None:
        return None
    if rir < 0:
        raise ValueError(f"RIR must be >= 0, got {rir}")
    # 4+ bucket: 4 or more reps in reserve all read as the RPE-6 floor.
    bucket = min(rir, 4)
    return _RIR_TO_RPE[bucket]


def rpe_to_rir(rpe: float | None) -> int | None:
    """Inverse of :func:`rir_to_rpe`, for presenting a stored RPE back as a chip.

    ``None`` maps to ``None``. RPE at or below the 6 floor reads back as the "4+"
    bucket (integer 4); RPE at or above 10 reads back as RIR 0. Values in between
    round to the nearest whole RPE before inverting, so a stored 8.0 round-trips
    to RIR 2.
    """
    if rpe is None:
        return None
    # Clamp into the representable RPE window [6, 10] then invert RPE = 10 - RIR.
    clamped = max(6.0, min(10.0, rpe))
    return int(round(10.0 - clamped))
