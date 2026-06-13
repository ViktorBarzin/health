"""Effort RIR↔RPE mapping (CONTEXT.md "Effort").

The one-tap reps-in-reserve chip stores an RPE-equivalent. These tests pin the
exact mapping for all five buckets plus None, and the round-trip, so the
Progression engine (a later slice) inherits one canonical effort scale.
"""

import pytest

from app.services.effort import RIR_VALUES, rir_to_rpe, rpe_to_rir


@pytest.mark.parametrize(
    "rir,expected_rpe",
    [
        (0, 10.0),  # failure — no reps left
        (1, 9.0),
        (2, 8.0),
        (3, 7.0),
        (4, 6.0),  # the "4+" floor
    ],
)
def test_rir_to_rpe_maps_each_bucket(rir: int, expected_rpe: float) -> None:
    assert rir_to_rpe(rir) == expected_rpe


def test_rir_none_maps_to_none() -> None:
    # Effort is optional and never inferred.
    assert rir_to_rpe(None) is None


def test_rir_above_four_collapses_to_the_four_plus_floor() -> None:
    # "4+" is open-ended: 4, 5, 10 reps in reserve all store as RPE 6.
    assert rir_to_rpe(4) == 6.0
    assert rir_to_rpe(5) == 6.0
    assert rir_to_rpe(10) == 6.0


def test_negative_rir_is_invalid() -> None:
    with pytest.raises(ValueError):
        rir_to_rpe(-1)


def test_the_five_selectable_buckets_are_zero_through_four() -> None:
    assert RIR_VALUES == (0, 1, 2, 3, 4)


@pytest.mark.parametrize("rir", list(RIR_VALUES))
def test_rir_round_trips_through_rpe(rir: int) -> None:
    # Every selectable bucket survives store-then-read-back.
    assert rpe_to_rir(rir_to_rpe(rir)) == rir


def test_rpe_none_maps_back_to_none() -> None:
    assert rpe_to_rir(None) is None


@pytest.mark.parametrize(
    "rpe,expected_rir",
    [
        (10.0, 0),
        (9.0, 1),
        (8.0, 2),
        (7.0, 3),
        (6.0, 4),
        (5.0, 4),  # below the floor still reads as 4+
        (11.0, 0),  # above the ceiling still reads as failure
    ],
)
def test_rpe_to_rir_clamps_and_inverts(rpe: float, expected_rir: int) -> None:
    assert rpe_to_rir(rpe) == expected_rir
