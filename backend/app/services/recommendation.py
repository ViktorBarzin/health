"""Recommendation generator — the deterministic freestyle workout proposal core.

CONTEXT.md ("Recommendation"): "A generated Session proposal — exercises with
target sets × reps × weight — for one gym visit … freestyle otherwise; starting
it instantiates the Session the user logs against." This module is the
**freestyle** path: no active Program (#13), no LLM (#14) — the deterministic,
explainable engine core ADR-0002 mandates ("The LLM proposes; it never decides").

What it does
============
Given the candidate Exercises (already scoped to the user's library), the
per-muscle **Recovery** map (from :mod:`app.services.recovery`), the user's
**Gym Profile** equipment, and each Exercise's recent Set history, it produces
today's proposal: a ranked set of Exercises, each with target sets × reps ×
weight from the **Progression** core (:mod:`app.services.progression`).

Heuristics (the documented, defensible choices)
-----------------------------------------------
1. **Equipment is a hard filter.** An Exercise is selectable only if its
   ``equipment`` is in the Gym Profile — except bodyweight Exercises
   (``equipment`` of ``None`` or ``"body only"``), which need nothing and are
   always allowed. Equipment the user lacks is *never* prescribed.

2. **Freshness score = mean Recovery of the muscles worked.** An Exercise's
   freshness is the mean Recovery (0–100; a muscle absent from the map is fresh
   = 100) across the muscles it works — **primary** movers at full weight,
   **secondary** movers at :data:`SECONDARY_WEIGHT` (the same half-credit
   convention Recovery itself uses). Higher = fresher = preferred, so fatigued
   muscles are de-prioritized.

3. **Greedy, diversity-aware selection.** Pick the freshest-scoring Exercise,
   then *temporarily knock down* the Recovery of the muscles it just worked (by
   :data:`WORKED_PENALTY` for primaries, scaled for secondaries) before scoring
   the next pick. This stops the proposal from stacking one muscle group: after
   chest is chosen, chest scores lower for the rest of the selection, so a
   different fresh group surfaces — a balanced session biased to fresh muscles.

4. **Deterministic.** No clock, no randomness; ties on freshness break on the
   Exercise id (a stable key), so identical input yields byte-identical output.

5. **Defaults.** :data:`DEFAULT_EXERCISE_COUNT` Exercises, each at
   :data:`DEFAULT_SETS_PER_EXERCISE` sets — a sane freestyle full-session size;
   the rep/weight target per Exercise comes from Progression.

YAGNI: this is a clean, explainable ranker — not an optimizer. Volume-landmark
targeting, split templates and autoregulation belong to the Program layer (#13);
biometric Readiness to #14.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.services.progression import (
    DEFAULT_LOAD_INCREMENT_KG,
    DEFAULT_REP_RANGE,
    ProgressionTarget,
    SetPerformance,
    next_target,
)

# --------------------------------------------------------------------------- #
# Tunable generator constants — the single place to retune freestyle generation.
# --------------------------------------------------------------------------- #

#: How many Exercises a freestyle proposal holds by default. Five is a typical
#: full-session size (Fitbod-style) — enough to cover several muscle groups
#: without overstaying a single visit.
DEFAULT_EXERCISE_COUNT: int = 5

#: Sets prescribed per Exercise by default. Three working sets is the standard
#: freestyle default and lands inside the 10–20 sets/muscle/week dose-response
#: window over a normal training week (ADR-0004 Principles).
DEFAULT_SETS_PER_EXERCISE: int = 3

#: A fully-fresh muscle's Recovery (and the value used for any muscle absent from
#: the Recovery map — untrained ⇒ fully recovered, matching the analytics fill).
_FULL_RECOVERY: float = 100.0

#: Secondary movers count for this fraction of a primary when scoring freshness —
#: the same half-credit convention :mod:`app.services.recovery` uses for load.
SECONDARY_WEIGHT: float = 0.5

#: Recovery points a worked PRIMARY muscle is knocked down by for the rest of the
#: selection, so the next pick favours a different fresh group (diversity). A
#: secondary mover is knocked down by ``WORKED_PENALTY * SECONDARY_WEIGHT``.
#: Sized so one pick meaningfully de-prioritises its group within a 5-Exercise
#: proposal without permanently banning it.
WORKED_PENALTY: float = 40.0

#: Equipment values that require nothing to perform — always selectable whatever
#: the Gym Profile holds.
_BODYWEIGHT_EQUIPMENT: frozenset[str | None] = frozenset({None, "body only"})


@dataclass(frozen=True)
class ExerciseCandidate:
    """One Exercise the generator may pick, with what it needs to rank/prescribe.

    Assembled by the querying layer from the Exercise library + the user's Set
    history: ``equipment`` is the Exercise's required equipment (free text,
    aligned with the Gym Profile vocabulary); ``primary_muscles`` /
    ``secondary_muscles`` are its ``exercise_muscles`` mapping; ``history`` is the
    recent working-set performances (most-recent-first) fed to Progression.
    """

    exercise_id: uuid.UUID
    name: str
    equipment: str | None
    primary_muscles: tuple[str, ...]
    secondary_muscles: tuple[str, ...] = ()
    history: tuple[SetPerformance, ...] = ()


@dataclass(frozen=True)
class RecommendedExercise:
    """One prescribed Exercise in a proposal: target sets × reps × weight.

    Mirrors what the user will log against; ``is_starting_point`` flags a
    first-guess weight (no history). The worked muscles are echoed for the
    explainable "why this Exercise" UI.
    """

    exercise_id: uuid.UUID
    name: str
    target_sets: int
    target_reps: int
    target_weight_kg: float
    is_starting_point: bool
    primary_muscles: tuple[str, ...]
    secondary_muscles: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    """A freestyle workout proposal — the ordered Exercises to perform today."""

    exercises: list[RecommendedExercise] = field(default_factory=list)


def _is_selectable(candidate: ExerciseCandidate, available: frozenset[str]) -> bool:
    """Whether the Gym Profile can equip this Exercise (bodyweight always can)."""
    if candidate.equipment in _BODYWEIGHT_EQUIPMENT:
        return True
    return candidate.equipment in available


def _freshness(
    candidate: ExerciseCandidate, recovery: dict[str, float]
) -> float:
    """Mean Recovery of the muscles this Exercise works (primary full, secondary half).

    A muscle absent from ``recovery`` is fully recovered (100). With no mapped
    muscles at all the Exercise is treated as fully fresh, so it can still be
    picked rather than silently dropped.
    """
    total = 0.0
    weight = 0.0
    for muscle in candidate.primary_muscles:
        total += recovery.get(muscle, _FULL_RECOVERY)
        weight += 1.0
    for muscle in candidate.secondary_muscles:
        total += recovery.get(muscle, _FULL_RECOVERY) * SECONDARY_WEIGHT
        weight += SECONDARY_WEIGHT
    if weight == 0.0:
        return _FULL_RECOVERY
    return total / weight


def _apply_worked_penalty(
    candidate: ExerciseCandidate, recovery: dict[str, float]
) -> None:
    """Knock down the worked muscles' Recovery in-place after a pick (diversity).

    Mutates the *working copy* of the Recovery map the selection loop owns — never
    the caller's input. Primaries take the full penalty, secondaries the scaled
    one; scores floor at 0.
    """
    for muscle in candidate.primary_muscles:
        base = recovery.get(muscle, _FULL_RECOVERY)
        recovery[muscle] = max(0.0, base - WORKED_PENALTY)
    for muscle in candidate.secondary_muscles:
        base = recovery.get(muscle, _FULL_RECOVERY)
        recovery[muscle] = max(0.0, base - WORKED_PENALTY * SECONDARY_WEIGHT)


def _prescribe(
    candidate: ExerciseCandidate,
    *,
    sets_per_exercise: int,
    rep_range: tuple[int, int],
    load_increment_kg: float,
) -> RecommendedExercise:
    """Turn a chosen candidate into a prescribed Exercise via Progression."""
    target: ProgressionTarget = next_target(
        candidate.history,
        rep_range=rep_range,
        load_increment_kg=load_increment_kg,
    )
    return RecommendedExercise(
        exercise_id=candidate.exercise_id,
        name=candidate.name,
        target_sets=sets_per_exercise,
        target_reps=target.reps,
        target_weight_kg=target.weight_kg,
        is_starting_point=target.is_starting_point,
        primary_muscles=candidate.primary_muscles,
        secondary_muscles=candidate.secondary_muscles,
    )


def generate_recommendation(
    candidates: Iterable[ExerciseCandidate],
    *,
    recovery: dict[str, float],
    available_equipment: Iterable[str],
    exercise_count: int = DEFAULT_EXERCISE_COUNT,
    sets_per_exercise: int = DEFAULT_SETS_PER_EXERCISE,
    rep_range: tuple[int, int] = DEFAULT_REP_RANGE,
    load_increment_kg: float = DEFAULT_LOAD_INCREMENT_KG,
) -> Recommendation:
    """Produce today's freestyle workout proposal — deterministic and explainable.

    Filters ``candidates`` to those the Gym Profile (``available_equipment``) can
    equip, then greedily picks up to ``exercise_count`` of them biased toward
    fresh muscles (``recovery``), de-prioritising a group once it's been worked
    (diversity). Each pick is prescribed ``sets_per_exercise`` sets at the
    Progression next target. Pure: given the same inputs the output is identical
    (ties break on the Exercise id).
    """
    available = frozenset(available_equipment)
    selectable: Sequence[ExerciseCandidate] = [
        c for c in candidates if _is_selectable(c, available)
    ]

    # A working copy of Recovery the loop mutates to enforce diversity; the
    # caller's map is never touched.
    working_recovery = dict(recovery)

    chosen: list[RecommendedExercise] = []
    remaining = list(selectable)
    while remaining and len(chosen) < exercise_count:
        # Highest freshness first; ties break on the stable Exercise id so the
        # order is reproducible. (max over a stable key, not random.)
        best = max(
            remaining,
            key=lambda c: (_freshness(c, working_recovery), _neg_id(c.exercise_id)),
        )
        chosen.append(
            _prescribe(
                best,
                sets_per_exercise=sets_per_exercise,
                rep_range=rep_range,
                load_increment_kg=load_increment_kg,
            )
        )
        remaining.remove(best)
        _apply_worked_penalty(best, working_recovery)

    return Recommendation(exercises=chosen)


def _neg_id(exercise_id: uuid.UUID) -> int:
    """Sort key that makes the *lower* Exercise id win a freshness tie.

    ``max`` picks the largest key, so we negate the id's integer form: the
    smallest id becomes the largest negated value and leads on a tie — a stable,
    deterministic tie-break.
    """
    return -exercise_id.int
