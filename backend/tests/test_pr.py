"""PR detection core — does a freshly-logged Set beat the user's history?

CONTEXT.md ("PR"): "a user's personal record for an Exercise — best weight,
reps-at-weight, estimated 1RM, or volume; detected live as a Set is logged
(offline included) and celebrated in the UI."

This pure module is the shared algorithm definition: the backend imports it to
compute/persist authoritative PRs on sync, and the TS port
(``frontend/src/lib/pr.ts``) mirrors it so the offline browser detector and the
server agree. The tests pin the four dimensions, the normal-only rule, the
first-ever-set case, and the strict-improvement (ties don't count) rule.
"""

import pytest

from app.models.training_session import SetType
from app.services.pr import (
    PRKind,
    PriorBests,
    detect_prs,
)

# A clean slate: the user has never logged this Exercise.
EMPTY = PriorBests()


def _kinds(results) -> set[PRKind]:
    return {r.kind for r in results}


# --------------------------------------------------------------------------- #
# First-ever set: every applicable dimension is a PR.
# --------------------------------------------------------------------------- #


def test_first_ever_normal_set_is_a_pr_on_every_dimension() -> None:
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=EMPTY
    )
    assert _kinds(results) == {
        PRKind.weight,
        PRKind.e1rm,
        PRKind.reps_at_weight,
        PRKind.volume,
    }


def test_first_ever_set_carries_its_achieved_values() -> None:
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=EMPTY
    )
    by_kind = {r.kind: r for r in results}
    assert by_kind[PRKind.weight].value == pytest.approx(100.0)
    assert by_kind[PRKind.reps_at_weight].value == pytest.approx(5)
    assert by_kind[PRKind.volume].value == pytest.approx(500.0)
    # e1RM at 100×5 (1-rep-anchored Epley) = 100*(1+4/30).
    assert by_kind[PRKind.e1rm].value == pytest.approx(100.0 * (1 + 4 / 30))
    # reps_at_weight records the weight it was achieved at.
    assert by_kind[PRKind.reps_at_weight].at_weight_kg == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# Set-type exclusion: non-normal Sets never generate PRs.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("set_type", [SetType.warmup, SetType.drop, SetType.failure])
def test_non_normal_sets_never_pr_even_against_empty_history(set_type: SetType) -> None:
    # A monster warmup/drop/failure set still produces no PR (the volume.py rule).
    results = detect_prs(
        weight_kg=500.0, reps=20, set_type=set_type, rir=None, prior=EMPTY
    )
    assert results == []


# --------------------------------------------------------------------------- #
# Best weight (at any reps).
# --------------------------------------------------------------------------- #


def test_heavier_weight_is_a_weight_pr() -> None:
    prior = PriorBests(best_weight_kg=100.0, best_e1rm=200.0, best_volume_kg=2000.0)
    results = detect_prs(
        weight_kg=102.5, reps=1, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.weight in _kinds(results)


def test_equal_weight_is_not_a_weight_pr() -> None:
    # Ties never count — strictly greater only.
    prior = PriorBests(best_weight_kg=100.0)
    results = detect_prs(
        weight_kg=100.0, reps=1, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.weight not in _kinds(results)


def test_lighter_weight_is_not_a_weight_pr() -> None:
    prior = PriorBests(best_weight_kg=100.0)
    results = detect_prs(
        weight_kg=80.0, reps=1, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.weight not in _kinds(results)


# --------------------------------------------------------------------------- #
# Best estimated 1RM.
# --------------------------------------------------------------------------- #


def test_higher_e1rm_is_an_e1rm_pr() -> None:
    # 100×5 → e1RM 113.3; beating a prior best e1RM of 110.
    prior = PriorBests(best_weight_kg=200.0, best_e1rm=110.0, best_volume_kg=99999.0)
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.e1rm in _kinds(results)
    # …but not a weight PR (lighter than the 200 best) nor a volume PR.
    assert PRKind.weight not in _kinds(results)
    assert PRKind.volume not in _kinds(results)


def test_equal_e1rm_is_not_a_pr() -> None:
    exact = 100.0 * (1 + 4 / 30)  # 100×5
    prior = PriorBests(best_e1rm=exact, best_weight_kg=999.0, best_volume_kg=999999.0)
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.e1rm not in _kinds(results)


def test_reps_in_reserve_can_tip_an_e1rm_pr() -> None:
    # 100×5 to failure → e1RM 113.3 (below a 116 prior). With 3 reps in reserve
    # the effective set is 100×8 → e1RM 123.3, which clears it.
    prior = PriorBests(best_e1rm=116.0, best_weight_kg=999.0, best_volume_kg=999999.0)
    to_failure = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=0, prior=prior
    )
    assert PRKind.e1rm not in _kinds(to_failure)
    with_reserve = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=3, prior=prior
    )
    assert PRKind.e1rm in _kinds(with_reserve)


# --------------------------------------------------------------------------- #
# Best reps at a given weight.
# --------------------------------------------------------------------------- #


def test_more_reps_at_a_known_weight_is_a_reps_pr() -> None:
    # Best at 100 kg was 5 reps; 6 reps at 100 kg is a reps-at-weight PR.
    prior = PriorBests(
        best_weight_kg=100.0,
        best_e1rm=500.0,  # high, so e1rm won't also fire and muddy the assert
        best_volume_kg=999999.0,
        reps_by_weight={100.0: 5},
    )
    results = detect_prs(
        weight_kg=100.0, reps=6, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.reps_at_weight in _kinds(results)


def test_equal_reps_at_a_known_weight_is_not_a_reps_pr() -> None:
    prior = PriorBests(
        best_weight_kg=100.0,
        best_e1rm=500.0,
        best_volume_kg=999999.0,
        reps_by_weight={100.0: 5},
    )
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.reps_at_weight not in _kinds(results)


def test_first_set_at_a_new_weight_is_a_reps_pr() -> None:
    # Never lifted 110 kg before — any rep count at it is a reps-at-weight PR,
    # even if fewer reps than at a different (lower) weight.
    prior = PriorBests(
        best_weight_kg=100.0,
        best_e1rm=500.0,
        best_volume_kg=999999.0,
        reps_by_weight={100.0: 10},
    )
    results = detect_prs(
        weight_kg=110.0, reps=2, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.reps_at_weight in _kinds(results)
    by_kind = {r.kind: r for r in results}
    assert by_kind[PRKind.reps_at_weight].at_weight_kg == pytest.approx(110.0)


# --------------------------------------------------------------------------- #
# Best single-set volume (weight × reps).
# --------------------------------------------------------------------------- #


def test_higher_single_set_volume_is_a_volume_pr() -> None:
    prior = PriorBests(best_weight_kg=999.0, best_e1rm=99999.0, best_volume_kg=500.0)
    # 80 × 8 = 640 > 500.
    results = detect_prs(
        weight_kg=80.0, reps=8, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.volume in _kinds(results)


def test_equal_volume_is_not_a_volume_pr() -> None:
    prior = PriorBests(best_weight_kg=999.0, best_e1rm=99999.0, best_volume_kg=500.0)
    # 100 × 5 = 500, exactly the prior best.
    results = detect_prs(
        weight_kg=100.0, reps=5, set_type=SetType.normal, rir=None, prior=prior
    )
    assert PRKind.volume not in _kinds(results)


# --------------------------------------------------------------------------- #
# Multiple dimensions can fire at once; zero-load sets never PR.
# --------------------------------------------------------------------------- #


def test_one_set_can_set_several_prs_at_once() -> None:
    prior = PriorBests(
        best_weight_kg=90.0,
        best_e1rm=100.0,
        best_volume_kg=400.0,
        reps_by_weight={90.0: 5},
    )
    # 100 × 6: heavier than 90 (weight), e1RM ~116.7 > 100, volume 600 > 400,
    # and a new weight (100) so reps-at-weight too. All four.
    results = detect_prs(
        weight_kg=100.0, reps=6, set_type=SetType.normal, rir=None, prior=prior
    )
    assert _kinds(results) == {
        PRKind.weight,
        PRKind.e1rm,
        PRKind.reps_at_weight,
        PRKind.volume,
    }


def test_zero_weight_set_produces_no_pr() -> None:
    # A 0 kg placeholder (e.g. bodyweight not yet entered) never PRs.
    results = detect_prs(
        weight_kg=0.0, reps=10, set_type=SetType.normal, rir=None, prior=EMPTY
    )
    assert results == []


def test_zero_reps_set_produces_no_pr() -> None:
    results = detect_prs(
        weight_kg=100.0, reps=0, set_type=SetType.normal, rir=None, prior=EMPTY
    )
    assert results == []
