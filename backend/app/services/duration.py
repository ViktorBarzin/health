"""Duration shaper (plan ③) — deterministic "I have N minutes" day shaping.

CONTEXT.md: a Recommendation is the engine's proposal for one visit; this
module re-shapes it to a time budget using ONLY the existing conversational-
adjust levers (:mod:`app.services.adjust`'s ``volume_scale`` /
``max_exercises``) — a deterministic preset over the same bounded pipeline, so
the shaper can never produce a session the engine couldn't (ADR-0002), and
receipts stay intact.

Time model (documented constants, deliberately simple):
    per exercise = SETUP + sets × WORK + (sets − 1) × rest
Setup covers changing stations/loading plates (which also absorbs the rest
after an exercise's final set); WORK is the under-the-bar time of one set.

Shape selection: enumerate every (exercise count, volume scale ≤ 1) candidate,
keep those fitting the budget, and pick the one that USES the most of it —
tie-broken toward more exercises, then more volume. "Have 30 minutes" should
buy the most training 30 minutes holds, not the most aggressive cut. When even
the minimal shape (1 exercise at the 0.5 scale floor) overruns, return it and
say so — never silently pretend it fits.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.exercise_pref import DEFAULT_REST_SECONDS
from app.services.adjust import Adjustment, apply_adjustment
from app.services.recommendation import Recommendation

#: Under-the-bar seconds for one working set (a typical 6–12-rep set).
WORK_SECONDS_PER_SET: int = 40

#: Station change + plate loading per exercise; also absorbs the rest after the
#: exercise's final set, which is why that rest isn't counted separately.
SETUP_SECONDS_PER_EXERCISE: int = 90

#: The volume-scale candidates a shape may use — never above 1.0 (a shaper only
#: trims) and never below the adjust envelope's 0.5 floor.
_SCALE_STEPS: tuple[float, ...] = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5)


@dataclass(frozen=True)
class DurationShapeResult:
    """A shaped day: the new proposal, the levers used, and honesty flags."""

    recommendation: Recommendation
    adjustment: Adjustment
    estimated_seconds: int
    fits: bool
    note: str


def estimate_seconds(
    recommendation: Recommendation, *, rest_seconds: int = DEFAULT_REST_SECONDS
) -> int:
    """Estimated wall-clock seconds to perform a proposal (see the time model)."""
    total = 0
    for ex in recommendation.exercises:
        sets = max(0, ex.target_sets)
        if sets == 0:
            continue
        total += (
            SETUP_SECONDS_PER_EXERCISE
            + sets * WORK_SECONDS_PER_SET
            + (sets - 1) * rest_seconds
        )
    return total


def shape_to_duration(
    recommendation: Recommendation,
    minutes: int,
    *,
    rest_seconds: int = DEFAULT_REST_SECONDS,
) -> DurationShapeResult:
    """Fit a proposal into ``minutes``, keeping as much training as fits."""
    budget = minutes * 60
    base_estimate = estimate_seconds(recommendation, rest_seconds=rest_seconds)
    if base_estimate <= budget:
        return DurationShapeResult(
            recommendation=recommendation,
            adjustment=Adjustment(note="already fits"),
            estimated_seconds=base_estimate,
            fits=True,
            note=f"Fits as planned (~{_mins(base_estimate)} min).",
        )

    count = len(recommendation.exercises)
    best: tuple[int, int, float] | None = None  # (estimate, count, scale)
    best_shape: Recommendation | None = None
    best_adjustment: Adjustment | None = None
    minimal: tuple[Recommendation, Adjustment, int] | None = None

    for n in range(count, 0, -1):
        for scale in _SCALE_STEPS:
            adjustment = Adjustment(
                volume_scale=None if scale == 1.0 else scale,
                max_exercises=None if n == count else n,
            )
            shaped = apply_adjustment(recommendation, adjustment, sets_floor=1)
            est = estimate_seconds(shaped, rest_seconds=rest_seconds)
            if minimal is None or est < minimal[2]:
                minimal = (shaped, adjustment, est)
            if est > budget:
                continue
            key = (est, n, scale)
            if best is None or key > best:
                best = key
                best_shape = shaped
                best_adjustment = adjustment

    if best_shape is not None and best_adjustment is not None and best is not None:
        return DurationShapeResult(
            recommendation=best_shape,
            adjustment=best_adjustment,
            estimated_seconds=best[0],
            fits=True,
            note=_shape_note(recommendation, best_shape, best[0]),
        )

    # Even the smallest shape overruns — return it, honestly labelled.
    assert minimal is not None  # count >= 1 here, so at least one candidate ran
    shaped, adjustment, est = minimal
    return DurationShapeResult(
        recommendation=shaped,
        adjustment=adjustment,
        estimated_seconds=est,
        fits=False,
        note=(
            f"Even the shortest shape runs over — about {_mins(est)} min "
            f"against your {minutes}."
        ),
    )


def _mins(seconds: int) -> int:
    return round(seconds / 60)


def _shape_note(
    base: Recommendation, shaped: Recommendation, estimated: int
) -> str:
    dropped = len(base.exercises) - len(shaped.exercises)
    scaled = any(
        s.target_sets < b.target_sets
        for b, s in zip(base.exercises, shaped.exercises)
    )
    parts: list[str] = []
    if dropped > 0:
        parts.append(f"dropped {dropped} exercise{'s' if dropped != 1 else ''}")
    if scaled:
        parts.append("trimmed sets")
    action = " and ".join(parts) if parts else "reshaped"
    return f"{action.capitalize()} to fit — about {_mins(estimated)} min."
