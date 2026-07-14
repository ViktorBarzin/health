"""Pure Block Review engine (CONTEXT.md "Block Review"; ADR-0011; plan M4).

The damped, deterministic rule set that keeps the active Program true to
observed Adherence. Contract pinned here:

- volume DOWN: a muscle under 80% completion two consecutive weeks → future
  accumulation targets drop (−2 when severe <60%, else −1), never below the
  Principle floor;
- volume UP: ≥95% completion two weeks, zero hard failures, healthy Readiness
  → +1, never above the ceiling;
- one volume move per muscle per training week (cooldown) — the damping;
- rotation: a slot failing 3+ consecutive Sessions on the same Exercise is
  flagged for rotation (the query layer picks the replacement via the Swap
  ranking), at most once per slot per week;
- insufficient data (fewer than 2 complete weeks) → no changes, ever;
- deterministic: same inputs → same changes, stably ordered;
- no flip-flop: a week of failure followed by a good week produces nothing.
"""

import uuid

from app.services.block_review import (
    MuscleWeekSignal,
    ReviewInputs,
    SlotSignal,
    review,
)


def _week(muscle: str, *, completion: float, hard: int = 0, prescribed: int = 12):
    return MuscleWeekSignal(
        muscle=muscle,
        completion=completion,
        hard_failures=hard,
        soft_shortfalls=0,
        prescribed_sets=prescribed,
    )


def _inputs(
    weeks,
    *,
    slots=(),
    next_targets=None,
    bounds=None,
    readiness_ok=True,
    muscles_on_cooldown=frozenset(),
    slots_on_cooldown=frozenset(),
):
    return ReviewInputs(
        weeks=tuple(tuple(w) for w in weeks),
        slots=tuple(slots),
        next_week_targets=next_targets or {"chest": 12},
        bounds=bounds or {"chest": (10, 20)},
        readiness_ok=readiness_ok,
        muscles_on_cooldown=muscles_on_cooldown,
        slots_on_cooldown=slots_on_cooldown,
    )


def test_two_weak_weeks_reduce_volume() -> None:
    inputs = _inputs([[_week("chest", completion=0.7)], [_week("chest", completion=0.75)]])
    changes = review(inputs)
    assert len(changes) == 1
    ch = changes[0]
    assert ch.lever == "volume" and ch.muscle == "chest"
    assert ch.from_value == 12 and ch.to_value == 11  # −1 (not severe)


def test_severe_underperformance_cuts_two_sets() -> None:
    inputs = _inputs([[_week("chest", completion=0.5)], [_week("chest", completion=0.55)]])
    changes = review(inputs)
    assert changes[0].to_value == 10  # −2, still at/above the floor


def test_volume_never_goes_below_the_floor() -> None:
    inputs = _inputs(
        [[_week("chest", completion=0.4)], [_week("chest", completion=0.4)]],
        next_targets={"chest": 10},
        bounds={"chest": (10, 20)},
    )
    assert review(inputs) == []  # already at the floor — nothing to cut


def test_two_strong_weeks_add_a_set() -> None:
    inputs = _inputs(
        [[_week("chest", completion=1.0)], [_week("chest", completion=0.96)]]
    )
    changes = review(inputs)
    assert changes[0].to_value == 13


def test_no_increase_on_hard_failures_or_poor_readiness() -> None:
    with_failures = _inputs(
        [[_week("chest", completion=1.0, hard=1)], [_week("chest", completion=1.0)]]
    )
    assert review(with_failures) == []
    tired = _inputs(
        [[_week("chest", completion=1.0)], [_week("chest", completion=1.0)]],
        readiness_ok=False,
    )
    assert review(tired) == []


def test_volume_never_exceeds_the_ceiling() -> None:
    inputs = _inputs(
        [[_week("chest", completion=1.0)], [_week("chest", completion=1.0)]],
        next_targets={"chest": 20},
        bounds={"chest": (10, 20)},
    )
    assert review(inputs) == []


def test_cooldown_blocks_a_second_move_in_the_same_week() -> None:
    inputs = _inputs(
        [[_week("chest", completion=0.7)], [_week("chest", completion=0.7)]],
        muscles_on_cooldown=frozenset({"chest"}),
    )
    assert review(inputs) == []


def test_mixed_weeks_change_nothing_no_flip_flop() -> None:
    good_then_bad = _inputs(
        [[_week("chest", completion=1.0)], [_week("chest", completion=0.6)]]
    )
    assert review(good_then_bad) == []
    bad_then_good = _inputs(
        [[_week("chest", completion=0.6)], [_week("chest", completion=1.0)]]
    )
    assert review(bad_then_good) == []


def test_one_week_of_data_is_not_enough() -> None:
    inputs = _inputs([[_week("chest", completion=0.4)]])
    assert review(inputs) == []


def test_rotation_flagged_after_three_consecutive_failed_sessions() -> None:
    ex = uuid.UUID(int=7)
    slot = SlotSignal(
        day_index=0,
        slot_index=1,
        muscle="chest",
        exercise_id=ex,
        consecutive_failures=3,
    )
    inputs = _inputs(
        [[_week("chest", completion=0.9)], [_week("chest", completion=0.9)]],
        slots=[slot],
    )
    changes = review(inputs)
    rotations = [c for c in changes if c.lever == "rotation"]
    assert len(rotations) == 1
    assert rotations[0].day_index == 0 and rotations[0].slot_index == 1
    assert rotations[0].from_value == str(ex)

    # Two failures isn't enough; a rotated slot on cooldown is skipped.
    calm = SlotSignal(0, 1, "chest", ex, consecutive_failures=2)
    assert review(_inputs([[_week("chest",
        completion=0.9)], [_week("chest", completion=0.9)]], slots=[calm])) == []
    cool = _inputs(
        [[_week("chest", completion=0.9)], [_week("chest", completion=0.9)]],
        slots=[slot],
        slots_on_cooldown=frozenset({(0, 1)}),
    )
    assert review(cool) == []


def test_changes_are_stably_ordered_and_deterministic() -> None:
    weeks = [
        [_week("chest", completion=0.7), _week("lats", completion=0.7)],
        [_week("chest", completion=0.7), _week("lats", completion=0.7)],
    ]
    inputs = _inputs(
        weeks,
        next_targets={"chest": 12, "lats": 14},
        bounds={"chest": (10, 20), "lats": (10, 20)},
    )
    first = review(inputs)
    second = review(inputs)
    assert first == second
    assert [c.muscle for c in first] == ["chest", "lats"]  # sorted
