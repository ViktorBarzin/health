"""Pure duration shaper (plan ③) — "I have 30 minutes" one-tap day shaping.

Deterministic mapper from a time budget to the EXISTING adjust levers
(volume_scale / max_exercises) — no new engine authority: the result is what
`apply_adjustment` produces, receipts intact. Contract:

- a day that already fits is untouched (explicit no-op);
- otherwise pick the candidate (exercise count, volume scale) that USES the
  most of the budget while fitting — prefer keeping exercises, then volume;
- volume only ever scales DOWN (a shaper never adds work), floors at 1 set;
- when even the minimal shape overruns, return it and say so honestly;
- deterministic: same inputs, same shape.
"""

import uuid

from app.services.duration import (
    SETUP_SECONDS_PER_EXERCISE,
    WORK_SECONDS_PER_SET,
    estimate_seconds,
    shape_to_duration,
)
from app.services.recommendation import Recommendation, RecommendedExercise


def _ex(n: int, sets: int = 3) -> RecommendedExercise:
    return RecommendedExercise(
        exercise_id=uuid.UUID(int=n),
        name=f"Exercise {n}",
        target_sets=sets,
        target_reps=8,
        target_weight_kg=60.0,
        is_starting_point=False,
        primary_muscles=("chest",),
        secondary_muscles=(),
    )


def _rec(count: int, sets: int = 3) -> Recommendation:
    return Recommendation(exercises=[_ex(n + 1, sets) for n in range(count)])


REST = 120  # the app-wide default rest used throughout these cases


def test_estimate_counts_setup_work_and_between_set_rest() -> None:
    # One exercise, 3 sets: setup + 3 work + 2 rests (no rest after the last
    # set — the next exercise's setup covers the transition).
    expected = SETUP_SECONDS_PER_EXERCISE + 3 * WORK_SECONDS_PER_SET + 2 * REST
    assert estimate_seconds(_rec(1), rest_seconds=REST) == expected
    assert estimate_seconds(_rec(4), rest_seconds=REST) == 4 * expected
    assert estimate_seconds(Recommendation(), rest_seconds=REST) == 0


def test_day_that_already_fits_is_untouched() -> None:
    result = shape_to_duration(_rec(3), 60, rest_seconds=REST)
    assert result.adjustment.is_noop()
    assert result.recommendation.exercises == _rec(3).exercises
    assert result.fits is True


def test_trims_exercise_count_to_use_the_budget() -> None:
    # 5 × (90 + 3·40 + 2·120) = 2250 s = 37.5 min. A 30-min budget fits
    # exactly 4 exercises at full volume (4 × 450 = 1800 s) — the shaper keeps
    # the most training that fits, preferring exercises over volume cuts.
    result = shape_to_duration(_rec(5), 30, rest_seconds=REST)
    assert result.fits is True
    assert len(result.recommendation.exercises) == 4
    assert all(e.target_sets == 3 for e in result.recommendation.exercises)
    assert result.adjustment.max_exercises == 4
    assert result.adjustment.volume_scale is None  # full volume kept


def test_scales_volume_when_dropping_alone_cannot_fit() -> None:
    # A 10-min budget: 1 full exercise = 450 s, but 2 exercises at half volume
    # (2 sets each) = 2 × (90 + 2·40 + 1·120) = 580 s — more training, still
    # under 600 s. The shaper prefers the fuller use of the budget.
    result = shape_to_duration(_rec(5), 10, rest_seconds=REST)
    assert result.fits is True
    assert len(result.recommendation.exercises) == 2
    assert all(e.target_sets == 2 for e in result.recommendation.exercises)
    assert estimate_seconds(result.recommendation, rest_seconds=REST) <= 600


def test_never_raises_volume_and_floors_at_one_set() -> None:
    result = shape_to_duration(_rec(4, sets=2), 5, rest_seconds=REST)
    for ex in result.recommendation.exercises:
        assert 1 <= ex.target_sets <= 2


def test_impossible_budget_returns_minimal_shape_and_says_so() -> None:
    result = shape_to_duration(_rec(5), 3, rest_seconds=REST)
    assert result.fits is False
    assert len(result.recommendation.exercises) == 1
    assert "over" in result.note.lower()


def test_empty_recommendation_is_a_noop() -> None:
    result = shape_to_duration(Recommendation(), 30, rest_seconds=REST)
    assert result.adjustment.is_noop()
    assert result.recommendation.exercises == []
    assert result.fits is True
