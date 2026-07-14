"""Pure Adherence core (CONTEXT.md "Adherence"; plan M4; ADR-0011).

The measured gap between a Prescription and what was performed — the primary
signal the Block Review learns from. Contract pinned here:

- only NORMAL sets count (the volume.py rule: warmup/drop/failure excluded);
- completion = performed/prescribed sets, capped at 1.0, weighted per slot;
- a rep shortfall at 0 reps-in-reserve is a HARD failure; with reserve (or
  unrated) it's a soft shortfall — failing and stopping early are different
  signals (Effort-aware, mirroring Progression's reserve threshold);
- two slots of the same Exercise consume performed sets in order;
- unprescribed extra work never dilutes slot metrics (counted separately);
- muscle aggregation prefers the slot's own muscle (Program slots know it),
  falling back to a resolver map (freestyle);
- no prescription ⇒ no signal (None), never a fake 100%.
"""

import uuid

from app.services.adherence import (
    PerformedSet,
    PrescribedSlot,
    aggregate_by_muscle,
    session_adherence,
)


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _slot(n: int, *, sets: int = 3, reps: int = 8, weight: float = 60.0, muscle=None):
    return PrescribedSlot(
        exercise_id=_id(n),
        target_sets=sets,
        target_reps=reps,
        target_weight_kg=weight,
        muscle=muscle,
    )


def _set(n: int, *, reps: int = 8, weight: float = 60.0, set_type: str = "normal", rir=None):
    return PerformedSet(
        exercise_id=_id(n), weight_kg=weight, reps=reps, set_type=set_type, rir=rir
    )


def test_full_completion() -> None:
    result = session_adherence([_slot(1, sets=3)], [_set(1)] * 3)
    assert result.completion == 1.0
    slot = result.slots[0]
    assert slot.prescribed_sets == 3 and slot.performed_sets == 3
    assert slot.hard_failures == 0 and slot.soft_shortfalls == 0


def test_partial_sets_and_cap_at_one() -> None:
    partial = session_adherence([_slot(1, sets=4)], [_set(1)] * 2)
    assert partial.completion == 0.5
    extra = session_adherence([_slot(1, sets=2)], [_set(1)] * 5)
    assert extra.completion == 1.0  # doing more never exceeds 100%
    assert extra.slots[0].performed_sets == 2  # slot consumes only its share
    assert extra.extra_sets == 3


def test_non_normal_sets_do_not_count() -> None:
    performed = [
        _set(1, set_type="warmup"),
        _set(1, set_type="drop"),
        _set(1),
    ]
    result = session_adherence([_slot(1, sets=3)], performed)
    assert result.slots[0].performed_sets == 1


def test_hard_failure_vs_soft_shortfall_split_by_effort() -> None:
    performed = [
        _set(1, reps=5, rir=0),  # failed at zero reserve — hard
        _set(1, reps=6, rir=2),  # stopped with reserve — soft
        _set(1, reps=6),  # unrated shortfall — soft (rating never required)
        _set(1, reps=8, rir=0),  # hit the target — not a shortfall at all
    ]
    result = session_adherence([_slot(1, sets=4, reps=8)], performed)
    slot = result.slots[0]
    assert slot.hard_failures == 1
    assert slot.soft_shortfalls == 2


def test_two_slots_same_exercise_consume_in_order() -> None:
    slots = [_slot(1, sets=2), _slot(1, sets=2)]
    result = session_adherence(slots, [_set(1)] * 3)
    assert [s.performed_sets for s in result.slots] == [2, 1]
    assert result.completion == 0.75


def test_session_completion_weighted_by_prescribed_sets() -> None:
    slots = [_slot(1, sets=4), _slot(2, sets=1)]
    performed = [_set(1)] * 4  # slot 2 skipped entirely
    result = session_adherence(slots, performed)
    assert result.completion == 0.8  # 4 of 5 prescribed sets


def test_load_deviation_measured_on_performed_sets() -> None:
    performed = [_set(1, weight=54.0), _set(1, weight=60.0)]
    result = session_adherence([_slot(1, sets=2, weight=60.0)], performed)
    assert result.slots[0].avg_load_deviation is not None
    assert abs(result.slots[0].avg_load_deviation - (-0.05)) < 1e-9


def test_no_prescription_yields_no_signal() -> None:
    result = session_adherence([], [_set(1)])
    assert result.completion is None
    assert result.slots == ()


def test_aggregate_by_muscle_prefers_slot_muscle_and_falls_back() -> None:
    a = session_adherence(
        [_slot(1, sets=2, muscle="chest"), _slot(2, sets=2)],  # slot 2 unlabelled
        [_set(1)] * 2 + [_set(2)],
    )
    weekly = aggregate_by_muscle([a], resolver={_id(2): "quadriceps"})
    assert weekly["chest"].prescribed_sets == 2
    assert weekly["chest"].performed_sets == 2
    assert weekly["chest"].completion == 1.0
    assert weekly["quadriceps"].prescribed_sets == 2
    assert weekly["quadriceps"].performed_sets == 1
    assert weekly["quadriceps"].completion == 0.5


def test_aggregate_accumulates_hard_failures_across_sessions() -> None:
    s1 = session_adherence(
        [_slot(1, sets=1, reps=8, muscle="chest")], [_set(1, reps=5, rir=0)]
    )
    s2 = session_adherence(
        [_slot(1, sets=1, reps=8, muscle="chest")], [_set(1, reps=6, rir=0)]
    )
    weekly = aggregate_by_muscle([s1, s2], resolver={})
    assert weekly["chest"].hard_failures == 2
