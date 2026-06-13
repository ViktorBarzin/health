"""Progression core — per-Exercise next target via effort-gated double progression.

This is an ENGINE CORE (it drives the Recommendation generator, #11), so its
behavioural rules are pinned hard the same way :mod:`tests.test_e1rm` and
:mod:`tests.test_recovery` pin theirs. Double progression with an Effort gate
(Zourdos 2016 RIR/RPE; Refalo 2023 0–3-RIR effort zone): within a rep range you
*add reps* until the top, and only when the top is reached with reps still in
reserve do you *add load* and reset to the bottom. Repeated failure backs the
load off. When Effort is missing the gate falls back to rep performance alone —
a rating is never required (CONTEXT.md: "when Effort is missing it falls back to
rep performance alone").

The reference is the Exercise's recent Set history (most recent working set);
the function is pure (no DB, no clock) so every case below is deterministic.
"""

from __future__ import annotations

import pytest

from app.services.progression import (
    DEFAULT_LOAD_INCREMENT_KG,
    DEFAULT_REP_RANGE,
    SetPerformance,
    ProgressionTarget,
    next_target,
)


def _perf(weight_kg: float, reps: int, rir: int | None = None) -> SetPerformance:
    """Build one prior working-set performance for an Exercise."""
    return SetPerformance(weight_kg=weight_kg, reps=reps, rir=rir)


# --------------------------------------------------------------------------- #
# First-time / no history → a sensible starting prescription
# --------------------------------------------------------------------------- #


def test_no_history_returns_starting_prescription() -> None:
    # With nothing logged the engine can't know a working weight, so it proposes
    # the bottom of the rep range at weight 0 (the UI reads 0 as "enter a
    # weight"/bodyweight) and flags it as a starting guess.
    target = next_target([])
    low, _high = DEFAULT_REP_RANGE
    assert target.reps == low
    assert target.weight_kg == 0.0
    assert target.is_starting_point is True


def test_no_history_with_seed_weight_uses_it() -> None:
    # A caller may seed a starting weight (e.g. from a similar Exercise); it is
    # prescribed at the bottom of the range.
    target = next_target([], starting_weight_kg=40.0)
    low, _high = DEFAULT_REP_RANGE
    assert target.weight_kg == 40.0
    assert target.reps == low
    assert target.is_starting_point is True


# --------------------------------------------------------------------------- #
# Add-reps phase: mid-range → keep the load, prescribe one more rep
# --------------------------------------------------------------------------- #


def test_mid_range_adds_a_rep_holds_load() -> None:
    # Last time 60 kg × 8 in an 8–12 range with reps in reserve: still room to
    # add reps, so hold the load and target one more rep.
    target = next_target([_perf(60.0, 8, rir=2)])
    assert target.weight_kg == 60.0
    assert target.reps == 9
    assert target.is_starting_point is False


def test_mid_range_no_effort_still_adds_a_rep() -> None:
    # Effort missing (rir=None): fall back to rep performance — mid-range still
    # means add a rep at the same load. Rating is never required.
    target = next_target([_perf(60.0, 9, rir=None)])
    assert target.weight_kg == 60.0
    assert target.reps == 10


def test_add_reps_never_exceeds_top_of_range() -> None:
    # The add-reps phase caps at the top of the range; it never prescribes reps
    # beyond ``high`` (that is what the load bump is for).
    _low, high = DEFAULT_REP_RANGE
    target = next_target([_perf(60.0, high - 1, rir=2)])
    assert target.reps == high
    assert target.weight_kg == 60.0


# --------------------------------------------------------------------------- #
# Load-increase phase: top of range WITH reserve → add load, reset to bottom
# --------------------------------------------------------------------------- #


def test_top_of_range_with_reserve_increases_load() -> None:
    # Hit the top (12) of an 8–12 range with 2 reps in reserve → the set was
    # comfortably within capacity: add the load increment and reset to the
    # bottom of the range.
    _low, high = DEFAULT_REP_RANGE
    target = next_target([_perf(60.0, high, rir=2)])
    low, _high = DEFAULT_REP_RANGE
    assert target.weight_kg == 60.0 + DEFAULT_LOAD_INCREMENT_KG
    assert target.reps == low


def test_top_of_range_to_failure_holds_and_adds_rep_capped() -> None:
    # Top of range but taken to FAILURE (rir=0): the rep target is met but there
    # was no reserve, so we do NOT add load yet — hold and stay at the top
    # (capped), banking the rep quality before progressing the load.
    _low, high = DEFAULT_REP_RANGE
    target = next_target([_perf(60.0, high, rir=0)])
    assert target.weight_kg == 60.0
    assert target.reps == high


def test_overshoot_top_with_reserve_increases_load() -> None:
    # Logged ABOVE the top (e.g. 14 reps in an 8–12 range) with reserve: clearly
    # time to add load and reset to the bottom.
    _low, high = DEFAULT_REP_RANGE
    target = next_target([_perf(60.0, high + 2, rir=3)])
    low, _high = DEFAULT_REP_RANGE
    assert target.weight_kg == 60.0 + DEFAULT_LOAD_INCREMENT_KG
    assert target.reps == low


def test_top_of_range_no_effort_increases_load() -> None:
    # Effort missing at the top of the range: the rep-only fallback treats
    # hitting the top as the trigger to add load (it cannot see reserve, so it
    # progresses on rep performance alone).
    _low, high = DEFAULT_REP_RANGE
    target = next_target([_perf(60.0, high, rir=None)])
    low, _high = DEFAULT_REP_RANGE
    assert target.weight_kg == 60.0 + DEFAULT_LOAD_INCREMENT_KG
    assert target.reps == low


# --------------------------------------------------------------------------- #
# Failure / back-off: missed the bottom of the range → hold or reduce load
# --------------------------------------------------------------------------- #


def test_missed_bottom_to_failure_backs_off_load() -> None:
    # Below the bottom of the range AND to failure (rir=0): the load is too
    # heavy — back it off by the increment and target the bottom of the range.
    low, _high = DEFAULT_REP_RANGE
    target = next_target([_perf(100.0, low - 3, rir=0)])
    assert target.weight_kg == 100.0 - DEFAULT_LOAD_INCREMENT_KG
    assert target.reps == low


def test_missed_bottom_backs_off_but_never_below_zero() -> None:
    # Back-off can never drive the prescribed weight negative (a very light
    # Exercise missed at the bottom): it floors at 0.
    low, _high = DEFAULT_REP_RANGE
    target = next_target([_perf(1.0, low - 5, rir=0)])
    assert target.weight_kg == 0.0
    assert target.reps == low


def test_below_bottom_with_reserve_holds_and_targets_bottom() -> None:
    # Below the bottom but with reps in reserve (didn't push hard): don't punish
    # the load — hold it and target the bottom of the range to build the reps.
    low, _high = DEFAULT_REP_RANGE
    target = next_target([_perf(80.0, low - 1, rir=3)])
    assert target.weight_kg == 80.0
    assert target.reps == low


# --------------------------------------------------------------------------- #
# Uses the most recent working set; ignores non-working context
# --------------------------------------------------------------------------- #


def test_uses_most_recent_performance_first_in_list() -> None:
    # The history is passed most-recent-first; the engine progresses from the
    # latest working set, not an older one.
    target = next_target(
        [_perf(70.0, 12, rir=2), _perf(60.0, 8, rir=2)]
    )
    low, _high = DEFAULT_REP_RANGE
    # Most-recent = 70×12 @ RIR2 → load bump from 70, reset reps.
    assert target.weight_kg == 70.0 + DEFAULT_LOAD_INCREMENT_KG
    assert target.reps == low


# --------------------------------------------------------------------------- #
# Custom rep range / increment are honoured
# --------------------------------------------------------------------------- #


def test_custom_rep_range_and_increment() -> None:
    # A strength-style 3–5 range with a 5 kg increment: hitting 5 reps with
    # reserve bumps by 5 kg and resets to 3.
    target = next_target(
        [_perf(120.0, 5, rir=1)],
        rep_range=(3, 5),
        load_increment_kg=5.0,
    )
    assert target.weight_kg == 125.0
    assert target.reps == 3


# --------------------------------------------------------------------------- #
# Monotonic sanity: a better performance never yields an EASIER next target.
#
# NOTE on the right lens. Double progression deliberately RESETS reps to the
# bottom when it adds load, so a single-set *e1RM* is NOT monotonic across the
# load-bump boundary (80×12 ≈ 109 e1RM holds higher than the freshly-bumped
# 82.5×8 ≈ 102 — by design: the heavier load for fewer reps is the progression).
# The meaningful invariants are therefore on the two prescribed axes directly:
# the next LOAD never decreases as performance improves, and within the
# constant-load add-reps phase the next REP target never decreases.
# --------------------------------------------------------------------------- #


def test_next_load_is_monotonic_non_decreasing_in_reps_performed() -> None:
    # At a fixed weight, performing MORE reps last time never prescribes a LOWER
    # next load: below-range may back off, in-range holds, top-of-range adds — a
    # step function that only ever rises with reps performed.
    prev_weight: float | None = None
    for reps in range(1, 18):
        t = next_target([_perf(80.0, reps, rir=2)])
        if prev_weight is not None:
            assert t.weight_kg >= prev_weight - 1e-9
        prev_weight = t.weight_kg


def test_next_reps_non_decreasing_within_add_reps_phase() -> None:
    # Within the add-reps phase (load held), performing more reps last time
    # prescribes ≥ as many reps next time — never fewer.
    low, high = DEFAULT_REP_RANGE
    prev_reps: int | None = None
    for reps in range(low, high):
        t = next_target([_perf(80.0, reps, rir=2)])
        assert t.weight_kg == 80.0  # still the add-reps phase: load held
        if prev_reps is not None:
            assert t.reps >= prev_reps
        prev_reps = t.reps


def test_more_reserve_never_lowers_next_load() -> None:
    # At a fixed weight×reps at the top of the range, more reps in reserve never
    # prescribes a LOWER next LOAD: to-failure (RIR 0) holds the load, while any
    # reserve bumps it. Reserve signals capacity, so the load is equal or higher.
    prev_weight: float | None = None
    _low, high = DEFAULT_REP_RANGE
    for rir in [0, 1, 2, 3, 4]:
        t = next_target([_perf(80.0, high, rir=rir)])
        if prev_weight is not None:
            assert t.weight_kg >= prev_weight - 1e-9
        prev_weight = t.weight_kg


def test_target_is_immutable() -> None:
    # ProgressionTarget is a frozen value object (safe to share across the
    # generator without aliasing surprises).
    target = next_target([_perf(60.0, 8, rir=2)])
    with pytest.raises(Exception):
        target.weight_kg = 999.0  # type: ignore[misc]
