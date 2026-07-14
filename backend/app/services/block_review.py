"""Block Review engine — the damped, deterministic Program-tuning rules (ADR-0011).

CONTEXT.md ("Block Review"): the third nested loop, above per-set Progression
and per-day autoregulation. Pure (no DB/clock/LLM — the review_query layer
assembles inputs and applies outputs), mirroring ``autoregulation.py``.

The damping is the point (Viktor chose continuous evaluation; damping is what
keeps the schedule followable): decisions need **two complete trailing weeks**
of signal, each lever carries a **cooldown** the caller reports (one volume
move per muscle, one rotation per slot, per training week), thresholds have a
dead band between them (0.80 cut / 0.95 raise) so alternating good and bad
weeks change nothing, and every change is emitted as a receipt-ready record.

Levers here: **volume** (next accumulation targets, within the Principle band)
and **rotation** (flag a chronically-failed slot; the query layer picks the
replacement via the Swap ranking). Rep placement and structural changes belong
to the block-boundary succession, not this continuous loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

#: Two consecutive weeks under this completion ⇒ the muscle's volume is cut.
_CUT_THRESHOLD: float = 0.80
#: …and under this, the cut is 2 sets instead of 1 (severe underperformance).
_SEVERE_THRESHOLD: float = 0.60
#: Two consecutive weeks at/above this completion (with no hard failures and
#: healthy Readiness) ⇒ the muscle earns one more set.
_RAISE_THRESHOLD: float = 0.95
#: Consecutive failed Sessions on the same Exercise before a slot rotates.
_ROTATION_STREAK: int = 3


@dataclass(frozen=True)
class MuscleWeekSignal:
    """One muscle's Adherence aggregate for one training week."""

    muscle: str
    completion: float
    hard_failures: int
    soft_shortfalls: int
    prescribed_sets: int


@dataclass(frozen=True)
class SlotSignal:
    """One Program-day slot's failure streak on its current Exercise."""

    day_index: int
    slot_index: int
    muscle: str
    exercise_id: uuid.UUID | None
    consecutive_failures: int


@dataclass(frozen=True)
class ReviewInputs:
    """Everything a review decision may read — assembled by the query layer.

    ``weeks`` is newest-first: ``weeks[0]`` is the most recent COMPLETE
    training week's per-muscle signals. ``next_week_targets`` / ``bounds`` are
    weekly per-muscle set counts (the Program's coming accumulation target and
    the Principle band). Cooldown sets name what already changed this training
    week — the caller derives them from the revision log.
    """

    weeks: tuple[tuple[MuscleWeekSignal, ...], ...]
    slots: tuple[SlotSignal, ...]
    next_week_targets: dict[str, int]
    bounds: dict[str, tuple[int, int]]
    readiness_ok: bool
    muscles_on_cooldown: frozenset[str]
    slots_on_cooldown: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class ReviewChange:
    """One receipt-ready change: what moves, from→to, and why."""

    lever: str  # "volume" | "rotation"
    muscle: str | None
    day_index: int | None
    slot_index: int | None
    from_value: object
    to_value: object
    reason: str
    principle_key: str | None


def _by_muscle(week: tuple[MuscleWeekSignal, ...]) -> dict[str, MuscleWeekSignal]:
    return {w.muscle: w for w in week}


def review(inputs: ReviewInputs) -> list[ReviewChange]:
    """The damped review: bounded volume moves + rotation flags, stably ordered."""
    changes: list[ReviewChange] = []

    # Volume needs two complete weeks of signal — never act on less.
    if len(inputs.weeks) >= 2:
        latest = _by_muscle(inputs.weeks[0])
        prior = _by_muscle(inputs.weeks[1])
        for muscle in sorted(set(latest) & set(prior)):
            if muscle in inputs.muscles_on_cooldown:
                continue
            target = inputs.next_week_targets.get(muscle)
            if target is None:
                continue
            floor, ceiling = inputs.bounds.get(muscle, (1, target))
            a, b = latest[muscle], prior[muscle]

            if a.completion < _CUT_THRESHOLD and b.completion < _CUT_THRESHOLD:
                severe = (
                    a.completion < _SEVERE_THRESHOLD
                    and b.completion < _SEVERE_THRESHOLD
                )
                to_value = max(floor, target - (2 if severe else 1))
                if to_value < target:
                    changes.append(
                        ReviewChange(
                            lever="volume",
                            muscle=muscle,
                            day_index=None,
                            slot_index=None,
                            from_value=target,
                            to_value=to_value,
                            reason=(
                                f"{muscle}: completed "
                                f"{round(a.completion * 100)}% and "
                                f"{round(b.completion * 100)}% of prescribed sets "
                                "two weeks running — reducing weekly volume"
                            ),
                            principle_key="volume-dose-response",
                        )
                    )
            elif (
                a.completion >= _RAISE_THRESHOLD
                and b.completion >= _RAISE_THRESHOLD
                and a.hard_failures == 0
                and b.hard_failures == 0
                and inputs.readiness_ok
            ):
                to_value = min(ceiling, target + 1)
                if to_value > target:
                    changes.append(
                        ReviewChange(
                            lever="volume",
                            muscle=muscle,
                            day_index=None,
                            slot_index=None,
                            from_value=target,
                            to_value=to_value,
                            reason=(
                                f"{muscle}: fully completed two weeks with no "
                                "failures and healthy readiness — adding a set"
                            ),
                            principle_key="volume-dose-response",
                        )
                    )

    # Rotation: chronic failure on the same movement, once per slot per week.
    for slot in sorted(inputs.slots, key=lambda s: (s.day_index, s.slot_index)):
        if slot.consecutive_failures < _ROTATION_STREAK:
            continue
        if (slot.day_index, slot.slot_index) in inputs.slots_on_cooldown:
            continue
        changes.append(
            ReviewChange(
                lever="rotation",
                muscle=slot.muscle,
                day_index=slot.day_index,
                slot_index=slot.slot_index,
                from_value=str(slot.exercise_id) if slot.exercise_id else None,
                to_value=None,  # the query layer fills the replacement in
                reason=(
                    f"slot {slot.slot_index} on day {slot.day_index} "
                    f"({slot.muscle}): failed {slot.consecutive_failures} "
                    "consecutive sessions — rotating the movement"
                ),
                principle_key=None,
            )
        )

    return changes
