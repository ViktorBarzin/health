"""Recovery core — per-muscle freshness from recent training load.

This is an ENGINE CORE (it feeds the Recommendation generator, #11), so its
behavioural properties are pinned hard, the same way :mod:`tests.test_e1rm`
pins the e1RM core:

* a freshly-trained muscle reads low and recovers toward 100% as time passes
  (monotonic non-decreasing recovery with time-since-training);
* a muscle that was never trained reads exactly 100% (fully fresh);
* primary movers fatigue more than secondary movers for the same Set
  (secondary muscles get partial credit), so they read *lower* recovery;
* non-normal Sets (warmup/drop/failure) never accrue fatigue — the exclusion
  is the same one :func:`app.services.volume.counts_for_volume` owns;
* every score is bounded in ``[0, 100]``.

The reference "now" is **injected** (never read from the clock inside the pure
core) so these assertions are deterministic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.training_session import SetType
from app.services.recovery import (
    DEFAULT_HALF_LIFE_HOURS,
    SECONDARY_WEIGHT,
    MuscleSetLoad,
    muscle_recovery,
)

# A fixed reference instant so every case is deterministic.
NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _load(
    muscle: str,
    *,
    hours_ago: float,
    volume: float = 1000.0,
    role: str = "primary",
    set_type: SetType = SetType.normal,
) -> MuscleSetLoad:
    """Build one attributed muscle load event ``hours_ago`` before ``NOW``."""
    return MuscleSetLoad(
        muscle=muscle,
        role=role,
        performed_at=NOW - timedelta(hours=hours_ago),
        volume_load=volume,
        set_type=set_type,
    )


# --------------------------------------------------------------------------- #
# Untrained / empty
# --------------------------------------------------------------------------- #


def test_untrained_muscle_is_fully_recovered() -> None:
    # No load anywhere ⇒ every queried muscle reads a perfect 100%.
    scores = muscle_recovery([], now=NOW)
    assert scores == {}


def test_muscle_with_no_recent_load_reads_100() -> None:
    # A muscle that appears in no load event is fresh; the helper reports 100
    # for any muscle we ask about that has no fatigue.
    scores = muscle_recovery([_load("chest", hours_ago=10)], now=NOW)
    # Chest was trained, so it is < 100; biceps (never trained) is absent →
    # callers treat "absent" as 100. We assert chest dropped and biceps absent.
    assert "biceps" not in scores
    assert scores["chest"] < 100.0


# --------------------------------------------------------------------------- #
# Freshly trained reads low; recovers toward 100 over time
# --------------------------------------------------------------------------- #


def test_freshly_trained_muscle_reads_low() -> None:
    # Heavy load moments ago ⇒ well below fully-recovered.
    scores = muscle_recovery(
        [_load("quadriceps", hours_ago=0.0, volume=5000.0)], now=NOW
    )
    assert scores["quadriceps"] < 50.0


def test_recovery_is_monotonic_with_time_since_training() -> None:
    # Same single Set, evaluated at increasing times since it was performed:
    # recovery only ever rises (fatigue decays).
    prev = None
    for hours in [0.0, 12.0, 24.0, 48.0, 96.0, 168.0]:
        scores = muscle_recovery(
            [_load("chest", hours_ago=hours, volume=3000.0)], now=NOW
        )
        score = scores.get("chest", 100.0)
        if prev is not None:
            assert score >= prev
        prev = score


def test_recovery_approaches_full_after_many_half_lives() -> None:
    # After ~10 half-lives the residual fatigue is negligible; recovery ~100.
    many = DEFAULT_HALF_LIFE_HOURS * 10
    scores = muscle_recovery(
        [_load("chest", hours_ago=many, volume=3000.0)], now=NOW
    )
    assert scores.get("chest", 100.0) > 99.0


# --------------------------------------------------------------------------- #
# Primary fatigues more than secondary
# --------------------------------------------------------------------------- #


def test_primary_fatigues_more_than_secondary() -> None:
    # Identical Set load, identical timing: as a primary mover the muscle takes
    # the full hit; as a secondary mover only partial — so secondary stays
    # fresher (higher recovery).
    primary = muscle_recovery(
        [_load("chest", hours_ago=6, volume=4000.0, role="primary")], now=NOW
    )["chest"]
    secondary = muscle_recovery(
        [_load("chest", hours_ago=6, volume=4000.0, role="secondary")], now=NOW
    )["chest"]
    assert secondary > primary


def test_secondary_credit_is_the_documented_fraction() -> None:
    # A secondary hit equals a primary hit scaled by SECONDARY_WEIGHT, so a
    # secondary set of volume V fatigues exactly like a primary set of V·weight.
    sec = muscle_recovery(
        [_load("chest", hours_ago=6, volume=1000.0, role="secondary")], now=NOW
    )["chest"]
    equiv_primary = muscle_recovery(
        [
            _load(
                "chest",
                hours_ago=6,
                volume=1000.0 * SECONDARY_WEIGHT,
                role="primary",
            )
        ],
        now=NOW,
    )["chest"]
    assert sec == pytest.approx(equiv_primary)


# --------------------------------------------------------------------------- #
# Non-normal Sets never accrue fatigue
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("set_type", [SetType.warmup, SetType.drop, SetType.failure])
def test_non_normal_sets_do_not_fatigue(set_type: SetType) -> None:
    # A warmup/drop/failure Set contributes no fatigue, so the muscle reads
    # fully recovered (absent from the map) despite a non-trivial volume.
    scores = muscle_recovery(
        [_load("chest", hours_ago=0.0, volume=5000.0, set_type=set_type)],
        now=NOW,
    )
    assert "chest" not in scores


def test_mixed_sets_count_only_normal() -> None:
    # Two sets on the same muscle, one normal and one warmup: the result equals
    # the normal one alone (the warmup is invisible to Recovery).
    mixed = muscle_recovery(
        [
            _load("chest", hours_ago=6, volume=3000.0, set_type=SetType.normal),
            _load("chest", hours_ago=6, volume=9000.0, set_type=SetType.warmup),
        ],
        now=NOW,
    )["chest"]
    normal_only = muscle_recovery(
        [_load("chest", hours_ago=6, volume=3000.0, set_type=SetType.normal)],
        now=NOW,
    )["chest"]
    assert mixed == pytest.approx(normal_only)


# --------------------------------------------------------------------------- #
# Accumulation and bounds
# --------------------------------------------------------------------------- #


def test_more_total_load_means_lower_recovery() -> None:
    # Two identical sets fatigue a muscle more than one (fatigue accumulates),
    # so recovery is strictly lower.
    one = muscle_recovery(
        [_load("lats", hours_ago=6, volume=2000.0)], now=NOW
    )["lats"]
    two = muscle_recovery(
        [
            _load("lats", hours_ago=6, volume=2000.0),
            _load("lats", hours_ago=6, volume=2000.0),
        ],
        now=NOW,
    )["lats"]
    assert two < one


def test_scores_are_bounded_0_to_100() -> None:
    # Even an absurd load can't push recovery below 0, and it never exceeds 100.
    scores = muscle_recovery(
        [_load("glutes", hours_ago=0.0, volume=10_000_000.0)], now=NOW
    )
    assert 0.0 <= scores["glutes"] <= 100.0


def test_independent_muscles_do_not_interfere() -> None:
    # Loading chest leaves an untouched muscle (hamstrings) at full recovery.
    scores = muscle_recovery(
        [_load("chest", hours_ago=2, volume=4000.0)], now=NOW
    )
    assert "hamstrings" not in scores
    assert scores["chest"] < 100.0


def test_naive_and_aware_reference_times_agree() -> None:
    # The half-life math is on elapsed hours; a naive NOW (no tzinfo) must give
    # the same answer as the aware one for naive-stored timestamps.
    naive_now = NOW.replace(tzinfo=None)
    load = MuscleSetLoad(
        muscle="chest",
        role="primary",
        performed_at=naive_now - timedelta(hours=12),
        volume_load=3000.0,
        set_type=SetType.normal,
    )
    aware_load = _load("chest", hours_ago=12, volume=3000.0)
    assert muscle_recovery([load], now=naive_now)["chest"] == pytest.approx(
        muscle_recovery([aware_load], now=NOW)["chest"]
    )
