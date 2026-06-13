"""Volume helper — the non-normal-set exclusion (CONTEXT.md "Set").

Pins the rule that only ``normal`` Sets count toward volume (and, by extension,
PR statistics in later slices). These are pure unit tests over the helper; no DB.
"""

import pytest

from app.models.training_session import SetType, TrainingSet
from app.services.volume import counts_for_volume, session_volume, set_volume


@pytest.mark.parametrize(
    "set_type,expected",
    [
        (SetType.normal, True),
        (SetType.warmup, False),
        (SetType.drop, False),
        (SetType.failure, False),
    ],
)
def test_only_normal_sets_count(set_type: SetType, expected: bool) -> None:
    assert counts_for_volume(set_type) is expected


def test_set_volume_is_weight_times_reps_for_normal() -> None:
    assert set_volume(100.0, 5, SetType.normal) == 500.0


@pytest.mark.parametrize("set_type", [SetType.warmup, SetType.drop, SetType.failure])
def test_set_volume_is_zero_for_non_normal(set_type: SetType) -> None:
    # Excluded by default even though weight × reps would be non-zero.
    assert set_volume(100.0, 5, set_type) == 0.0


def test_session_volume_sums_only_normal_sets() -> None:
    sets = [
        TrainingSet(weight_kg=60.0, reps=10, set_type=SetType.warmup),   # excluded
        TrainingSet(weight_kg=100.0, reps=5, set_type=SetType.normal),   # 500
        TrainingSet(weight_kg=100.0, reps=4, set_type=SetType.normal),   # 400
        TrainingSet(weight_kg=80.0, reps=8, set_type=SetType.drop),      # excluded
        TrainingSet(weight_kg=100.0, reps=1, set_type=SetType.failure),  # excluded
    ]
    # Only the two normal sets: 500 + 400.
    assert session_volume(sets) == 900.0


def test_session_volume_of_no_counted_sets_is_zero() -> None:
    sets = [
        TrainingSet(weight_kg=60.0, reps=10, set_type=SetType.warmup),
        TrainingSet(weight_kg=80.0, reps=8, set_type=SetType.drop),
    ]
    assert session_volume(sets) == 0.0
