"""Swap ranking core — ranked equivalents for one Recommendation slot (CONTEXT.md "Swap").

Pure and deterministic (ADR-0002): no DB, no clock. Given the outgoing Exercise
and a candidate pool, produce the ranked alternatives the SwapSheet offers when a
station is taken mid-Session. The DB glue (:mod:`app.services.swap_query`)
assembles the pool (library Exercises sharing a primary muscle, minus Exclusions)
and the user context; this module owns the rules:

1. **Equivalence = shared PRIMARY muscle.** An alternative must share at least
   one primary mover with the outgoing Exercise — a chest slot gets a chest
   movement. (Asserted here even though the pool query pre-filters, so the rule
   has exactly one authoritative home.)
2. **Equipment is a hard filter** — the same Gym Profile rule the freestyle
   generator applies (:func:`app.services.recommendation.is_bodyweight` allows
   bodyweight movements everywhere).
3. **Blocked ids never surface**: the outgoing Exercise itself, Exercises already
   in today's plan, and the user's Exclusions (the caller folds those in).
4. **Ranking** (descending): shared-primary-muscle count → has-history (real
   Progression beats a first guess) → freshness (mean Recovery of the muscles it
   works — the freestyle scoring) → stable Exercise-id tie-break.
5. **The prescription is the alternative's OWN Progression** — reps/weight from
   its history via :func:`app.services.progression.next_target`, flagged
   ``is_starting_point`` when there is none. The outgoing Exercise's numbers
   never transfer; the slot's set COUNT stays client-side (volume belongs to the
   slot's muscle, not the movement).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.services.progression import (
    DEFAULT_LOAD_INCREMENT_KG,
    DEFAULT_REP_RANGE,
    next_target,
)
from app.services.recommendation import (
    ExerciseCandidate,
    SECONDARY_WEIGHT,
    is_bodyweight,
)

#: How many alternatives a SwapSheet holds by default — enough to steer toward
#: whatever station is free without scrolling a library mid-set.
DEFAULT_ALTERNATIVES: int = 8

#: A muscle absent from the Recovery map is fully recovered (the freestyle fill).
_FULL_RECOVERY: float = 100.0


@dataclass(frozen=True)
class RankedAlternative:
    """One offered equivalent: who it is, why it qualifies, what to prescribe."""

    exercise_id: uuid.UUID
    name: str
    equipment: str | None
    target_reps: int
    target_weight_kg: float
    is_starting_point: bool
    has_history: bool
    primary_muscles: tuple[str, ...]
    secondary_muscles: tuple[str, ...]
    #: Primary muscles shared with the outgoing Exercise — the "hits the same
    #: chest" line the sheet shows.
    shared_muscles: tuple[str, ...]


def _freshness(candidate: ExerciseCandidate, recovery: dict[str, float]) -> float:
    """Mean Recovery of the muscles worked (primary full, secondary half-credit).

    Mirrors the freestyle generator's scoring so a Swap prefers fresh muscles for
    exactly the same reason the original pick did.
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


def rank_alternatives(
    target: ExerciseCandidate,
    pool: Iterable[ExerciseCandidate],
    *,
    recovery: dict[str, float],
    available_equipment: Iterable[str],
    blocked_ids: frozenset[uuid.UUID] = frozenset(),
    limit: int = DEFAULT_ALTERNATIVES,
    rep_range: tuple[int, int] = DEFAULT_REP_RANGE,
    load_increment_kg: float = DEFAULT_LOAD_INCREMENT_KG,
) -> list[RankedAlternative]:
    """Rank the equivalents that could replace ``target`` — best swap first."""
    available = frozenset(available_equipment)
    target_primaries = set(target.primary_muscles)

    scored: list[tuple[tuple[int, int, float, int], ExerciseCandidate, tuple[str, ...]]] = []
    for cand in pool:
        if cand.exercise_id == target.exercise_id or cand.exercise_id in blocked_ids:
            continue
        if not (is_bodyweight(cand.equipment) or cand.equipment in available):
            continue
        shared = tuple(
            m for m in cand.primary_muscles if m in target_primaries
        )
        if not shared:
            continue
        key = (
            len(shared),
            1 if cand.history else 0,
            _freshness(cand, recovery),
            -cand.exercise_id.int,
        )
        scored.append((key, cand, shared))

    scored.sort(key=lambda item: item[0], reverse=True)

    out: list[RankedAlternative] = []
    for _, cand, shared in scored[: max(0, limit)]:
        prescription = next_target(
            cand.history,
            rep_range=rep_range,
            load_increment_kg=load_increment_kg,
        )
        out.append(
            RankedAlternative(
                exercise_id=cand.exercise_id,
                name=cand.name,
                equipment=cand.equipment,
                target_reps=prescription.reps,
                target_weight_kg=prescription.weight_kg,
                is_starting_point=prescription.is_starting_point,
                has_history=bool(cand.history),
                primary_muscles=cand.primary_muscles,
                secondary_muscles=cand.secondary_muscles,
                shared_muscles=shared,
            )
        )
    return out
