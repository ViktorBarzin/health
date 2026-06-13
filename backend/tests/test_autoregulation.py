"""Autoregulation core — adjust the day's targets on Readiness + Recovery (#14).

This is the deterministic engine core that closes the loop (ADR-0002/0004):
given the Program's generated prescription, today's biometric **Readiness**, and
per-muscle **Recovery**, it trims or keeps volume **within Principle bounds**,
emits a **human-readable reason**, and — crucially — **never overrides anything
the user has edited or logged**. It also owns two related pure decisions: the
**fatigue-triggered early deload** (fire when readiness/recovery are
persistently low) and the **missed-day reflow** (re-anchor the week's day index
when scheduled days were skipped).

Properties pinned here (the same hard-pinning as :mod:`tests.test_recovery`):

* **poor readiness trims volume** — but never below the Principle floor for the
  slot, and at least one working set always remains;
* **strong readiness keeps the plan or allows slightly more** — but never above
  the Principle ceiling;
* **moderate / insufficient-data readiness leaves the plan unchanged**;
* a **still-fatigued muscle** (low Recovery) is trimmed harder than a fresh one;
* **user-edited slots are passed through untouched** even when readiness is poor;
* a **reason string is produced** that mentions the readiness number;
* **early deload** fires on sustained low signals and not on healthy ones;
* **missed-day reflow** advances the next-due day past skipped days.

All inputs (readiness, recovery, the slots, the "now") are injected — the core
is pure and deterministic.
"""

from app.services.autoregulation import (
    AdjustableSlot,
    AdjustmentResult,
    autoregulate_day,
    early_deload_triggered,
    reflow_day_index,
)


def _slot(
    *,
    muscle: str = "chest",
    sets: int = 5,
    reps: int = 8,
    weight: float = 60.0,
    floor: int = 2,
    ceiling: int = 8,
    user_edited: bool = False,
    deload_sets: int | None = None,
) -> AdjustableSlot:
    """A generated slot with its per-week Principle volume bounds for the muscle."""
    return AdjustableSlot(
        key=muscle,
        muscle=muscle,
        sets=sets,
        reps=reps,
        weight_kg=weight,
        sets_floor=floor,
        sets_ceiling=ceiling,
        user_edited=user_edited,
        deload_sets=deload_sets,
    )


# --------------------------------------------------------------------------- #
# Readiness drives volume
# --------------------------------------------------------------------------- #


def test_poor_readiness_trims_top_sets() -> None:
    slots = [_slot(sets=5)]
    result = autoregulate_day(slots, readiness=40.0, recovery={"chest": 80.0})
    assert isinstance(result, AdjustmentResult)
    adjusted = result.slots[0]
    assert adjusted.sets < 5
    assert adjusted.sets >= adjusted.sets_floor


def test_strong_readiness_keeps_or_raises_within_ceiling() -> None:
    slots = [_slot(sets=5, ceiling=8)]
    result = autoregulate_day(slots, readiness=90.0, recovery={"chest": 95.0})
    adjusted = result.slots[0]
    assert adjusted.sets >= 5
    assert adjusted.sets <= adjusted.sets_ceiling


def test_strong_readiness_never_exceeds_ceiling() -> None:
    # Already at the ceiling: strong readiness can't push past the Principle cap.
    slots = [_slot(sets=8, ceiling=8)]
    result = autoregulate_day(slots, readiness=99.0, recovery={"chest": 100.0})
    assert result.slots[0].sets == 8


def test_strong_readiness_never_raises_a_deloaded_slot() -> None:
    # A slot whose generated volume is already at/below its Principle floor (a
    # DELOAD week — planned recovery) must NOT be bumped on a strong, fresh day:
    # subjective "feeling great" can't undo a scheduled deload.
    slots = [_slot(sets=4, floor=6, ceiling=12)]  # 4 sets < floor 6 → deload-depth
    result = autoregulate_day(slots, readiness=95.0, recovery={"chest": 95.0})
    assert result.slots[0].sets == 4
    assert result.adjusted is False


def test_strong_readiness_does_not_raise_a_slot_exactly_at_floor() -> None:
    # At the floor exactly (the lightest accumulation week) is still "at/below
    # floor" — a strong day holds, it doesn't push it up.
    slots = [_slot(sets=6, floor=6, ceiling=12)]
    result = autoregulate_day(slots, readiness=95.0, recovery={"chest": 95.0})
    assert result.slots[0].sets == 6


def test_moderate_readiness_leaves_plan_unchanged() -> None:
    slots = [_slot(sets=5)]
    result = autoregulate_day(slots, readiness=55.0, recovery={"chest": 90.0})
    assert result.slots[0].sets == 5
    assert result.adjusted is False


def test_insufficient_readiness_leaves_plan_unchanged() -> None:
    # No readiness signal → no biometric adjustment; recovery is healthy too.
    slots = [_slot(sets=5)]
    result = autoregulate_day(slots, readiness=None, recovery={"chest": 90.0})
    assert result.slots[0].sets == 5
    assert result.adjusted is False


def test_trim_never_goes_below_floor_or_one_set() -> None:
    # Even with rock-bottom readiness and a fatigued muscle, the slot keeps at
    # least its Principle floor and never drops below one working set.
    slots = [_slot(sets=3, floor=2)]
    result = autoregulate_day(slots, readiness=5.0, recovery={"chest": 10.0})
    adjusted = result.slots[0]
    assert adjusted.sets >= adjusted.sets_floor
    assert adjusted.sets >= 1


def test_floor_of_one_is_respected_even_when_principle_floor_is_one() -> None:
    slots = [_slot(sets=2, floor=1)]
    result = autoregulate_day(slots, readiness=1.0, recovery={"chest": 1.0})
    assert result.slots[0].sets >= 1


def test_lower_readiness_trims_at_least_as_much() -> None:
    # Monotonic: the worse the readiness, the fewer (or equal) sets prescribed.
    prev = None
    for r in [90.0, 70.0, 55.0, 45.0, 35.0, 20.0, 5.0]:
        slots = [_slot(sets=6, floor=2, ceiling=8)]
        sets = autoregulate_day(slots, readiness=r, recovery={"chest": 85.0}).slots[0].sets
        if prev is not None:
            assert sets <= prev
        prev = sets


# --------------------------------------------------------------------------- #
# Per-muscle recovery
# --------------------------------------------------------------------------- #


def test_fatigued_muscle_trimmed_harder_than_fresh() -> None:
    # Same poor readiness; the still-fatigued muscle loses more sets than the
    # fresh one in the same session.
    slots = [
        _slot(muscle="chest", sets=6, floor=2, ceiling=8),
        _slot(muscle="back", sets=6, floor=2, ceiling=8),
    ]
    result = autoregulate_day(
        slots, readiness=45.0, recovery={"chest": 30.0, "back": 95.0}
    )
    chest = next(s for s in result.slots if s.muscle == "chest")
    back = next(s for s in result.slots if s.muscle == "back")
    assert chest.sets <= back.sets


def test_fresh_muscle_on_good_readiness_is_untrimmed() -> None:
    slots = [_slot(muscle="back", sets=5, floor=2, ceiling=8)]
    result = autoregulate_day(slots, readiness=80.0, recovery={"back": 95.0})
    assert result.slots[0].sets >= 5


def test_low_recovery_alone_trims_even_with_no_readiness() -> None:
    # No biometric readiness, but a muscle is clearly under-recovered from
    # training load → still trim that muscle.
    slots = [_slot(muscle="quadriceps", sets=6, floor=2, ceiling=8)]
    result = autoregulate_day(
        slots, readiness=None, recovery={"quadriceps": 20.0}
    )
    assert result.slots[0].sets < 6
    assert result.adjusted is True


# --------------------------------------------------------------------------- #
# User edits ALWAYS win
# --------------------------------------------------------------------------- #


def test_user_edited_slot_is_never_trimmed() -> None:
    # The user bumped this slot to 7 sets; poor readiness must not touch it.
    slots = [_slot(sets=7, user_edited=True, floor=2, ceiling=8)]
    result = autoregulate_day(slots, readiness=20.0, recovery={"chest": 20.0})
    adjusted = result.slots[0]
    assert adjusted.sets == 7
    assert adjusted.weight_kg == 60.0
    assert adjusted.reps == 8


def test_user_edited_slot_kept_even_above_ceiling() -> None:
    # User explicitly went above the Principle ceiling — their edit still wins.
    slots = [_slot(sets=12, user_edited=True, ceiling=8)]
    result = autoregulate_day(slots, readiness=90.0, recovery={"chest": 95.0})
    assert result.slots[0].sets == 12


def test_mixed_user_edited_and_generated() -> None:
    # Generated chest gets trimmed on poor readiness; user-edited back does not.
    slots = [
        _slot(muscle="chest", sets=6, floor=2, ceiling=8, user_edited=False),
        _slot(muscle="back", sets=6, floor=2, ceiling=8, user_edited=True),
    ]
    result = autoregulate_day(
        slots, readiness=35.0, recovery={"chest": 50.0, "back": 50.0}
    )
    chest = next(s for s in result.slots if s.muscle == "chest")
    back = next(s for s in result.slots if s.muscle == "back")
    assert chest.sets < 6
    assert back.sets == 6


# --------------------------------------------------------------------------- #
# Reason string
# --------------------------------------------------------------------------- #


def test_reason_mentions_readiness_number_when_trimming() -> None:
    slots = [_slot(sets=5)]
    result = autoregulate_day(slots, readiness=48.0, recovery={"chest": 80.0})
    assert result.reason
    assert "48" in result.reason


def test_no_reason_or_neutral_when_unchanged() -> None:
    slots = [_slot(sets=5)]
    result = autoregulate_day(slots, readiness=55.0, recovery={"chest": 90.0})
    assert result.adjusted is False


def test_strong_readiness_reason_is_positive() -> None:
    slots = [_slot(sets=5, ceiling=8)]
    result = autoregulate_day(slots, readiness=92.0, recovery={"chest": 95.0})
    # Whether or not it raises volume, a strong-readiness day should be flagged
    # as good (the reason explains it), not silent.
    assert result.reason


# --------------------------------------------------------------------------- #
# Early deload ACTS — it cuts the day to deload depth (not just a normal trim)
# --------------------------------------------------------------------------- #


def test_early_deload_cuts_day_to_deload_depth() -> None:
    # A sustained-low stretch fired the trigger → cut each slot to its supplied
    # deload-depth target (4), deeper than the normal per-readiness trim and well
    # below the generated 12 sets.
    slots = [_slot(sets=12, floor=6, ceiling=12, deload_sets=4)]
    result = autoregulate_day(
        slots, readiness=40.0, recovery={"chest": 80.0}, early_deload=True
    )
    assert result.slots[0].sets == 4
    assert result.early_deload is True
    assert result.adjusted is True
    assert "deload" in result.reason.lower()


def test_early_deload_is_deeper_than_a_normal_trim() -> None:
    # The same poor-readiness day cuts FURTHER under an early deload than the
    # ordinary per-readiness trim would — the flag actually changes the dose.
    base = _slot(sets=12, floor=6, ceiling=12, deload_sets=4)
    normal = autoregulate_day([base], readiness=40.0, recovery={"chest": 80.0})
    deload = autoregulate_day(
        [base], readiness=40.0, recovery={"chest": 80.0}, early_deload=True
    )
    assert deload.slots[0].sets < normal.slots[0].sets


def test_early_deload_falls_back_to_floor_without_a_target() -> None:
    # No deload_sets supplied → fall back to the Principle floor (still a real cut).
    slots = [_slot(sets=12, floor=6, ceiling=12, deload_sets=None)]
    result = autoregulate_day(
        slots, readiness=None, recovery={}, early_deload=True
    )
    assert result.slots[0].sets == 6


def test_early_deload_never_overrides_user_edits() -> None:
    # The cardinal invariant holds even under an early deload: a user-edited slot
    # is untouched.
    slots = [_slot(sets=12, floor=6, ceiling=12, deload_sets=4, user_edited=True)]
    result = autoregulate_day(
        slots, readiness=30.0, recovery={"chest": 30.0}, early_deload=True
    )
    assert result.slots[0].sets == 12


def test_early_deload_never_raises_a_light_slot() -> None:
    # If the generated value is already below the deload target, the deload only
    # ever reduces — never raises it up to the target.
    slots = [_slot(sets=3, floor=6, ceiling=12, deload_sets=5)]
    result = autoregulate_day(
        slots, readiness=None, recovery={}, early_deload=True
    )
    assert result.slots[0].sets == 3


# --------------------------------------------------------------------------- #
# Early deload (fatigue-triggered) — the trigger predicate
# --------------------------------------------------------------------------- #


def test_early_deload_fires_on_sustained_low_readiness() -> None:
    # Several consecutive days well below the threshold → deload early.
    assert early_deload_triggered([35.0, 30.0, 28.0, 33.0]) is True


def test_early_deload_does_not_fire_on_healthy_signals() -> None:
    assert early_deload_triggered([72.0, 68.0, 80.0, 75.0]) is False


def test_early_deload_does_not_fire_on_a_single_bad_day() -> None:
    # One rough day in an otherwise healthy stretch isn't a deload trigger.
    assert early_deload_triggered([75.0, 30.0, 72.0, 78.0]) is False


def test_early_deload_needs_enough_history() -> None:
    # Too few readings to be confident → don't trigger.
    assert early_deload_triggered([20.0]) is False
    assert early_deload_triggered([]) is False


def test_early_deload_ignores_missing_days() -> None:
    # ``None`` entries (no signal that day) are skipped, not treated as low.
    assert early_deload_triggered([None, 30.0, None, 28.0, 32.0]) is True
    assert early_deload_triggered([None, 75.0, None]) is False


# --------------------------------------------------------------------------- #
# Missed-day reflow
# --------------------------------------------------------------------------- #


def test_reflow_advances_past_missed_days() -> None:
    # Scheduled 3 sessions this week, the user logged 1 → next due is day 1
    # (the reflow keeps the rotation honest rather than stalling on day 0).
    assert reflow_day_index(sessions_done=1, days_per_week=3) == 1


def test_reflow_wraps_within_the_week() -> None:
    assert reflow_day_index(sessions_done=4, days_per_week=3) == 1
    assert reflow_day_index(sessions_done=3, days_per_week=3) == 0


def test_reflow_zero_sessions_is_day_zero() -> None:
    assert reflow_day_index(sessions_done=0, days_per_week=4) == 0


def test_reflow_handles_zero_days_safely() -> None:
    # Defensive: a degenerate 0 days/week never divides by zero.
    assert reflow_day_index(sessions_done=2, days_per_week=0) == 0
