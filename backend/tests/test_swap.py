"""Pure Swap ranking core (CONTEXT.md "Swap").

A Swap replaces one Recommendation slot with a ranked equivalent: same target
muscles, within the Gym Profile, Recovery-aware, preferring Exercises the user
has history on, with the incoming Exercise prescribed off its OWN Progression.
These tests pin the ranking contract:

- an alternative must share >=1 PRIMARY muscle with the outgoing Exercise;
- equipment is a hard filter (bodyweight always allowed) — same rule as the
  freestyle generator;
- blocked ids (the outgoing Exercise itself, Exercises already in the day,
  Exclusions) never appear;
- ranking: shared-primary-muscle count > has-history > freshness > stable id;
- the prescription comes from the alternative's own history (starting-point
  flagged when there is none);
- deterministic: same inputs, same output.
"""

import uuid

from app.services.progression import SetPerformance
from app.services.recommendation import ExerciseCandidate
from app.services.swap import rank_alternatives

# Stable ids so tie-breaks are predictable: _id(1) < _id(2) < ...
def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _cand(
    n: int,
    name: str,
    *,
    equipment: str | None = "barbell",
    primary: tuple[str, ...] = ("chest",),
    secondary: tuple[str, ...] = (),
    history: tuple[SetPerformance, ...] = (),
) -> ExerciseCandidate:
    return ExerciseCandidate(
        exercise_id=_id(n),
        name=name,
        equipment=equipment,
        primary_muscles=primary,
        secondary_muscles=secondary,
        history=history,
    )


_TARGET = _cand(1, "Barbell Bench Press", primary=("chest",), secondary=("triceps",))
_EQUIP = ("barbell", "dumbbell")


def test_requires_shared_primary_muscle() -> None:
    pool = [
        _cand(2, "Dumbbell Bench Press", equipment="dumbbell", primary=("chest",)),
        # Shares only a SECONDARY muscle with the target's primary — not an equivalent.
        _cand(3, "Triceps Pushdown", equipment="dumbbell", primary=("triceps",)),
        _cand(4, "Back Squat", primary=("quadriceps",)),
    ]
    out = rank_alternatives(_TARGET, pool, recovery={}, available_equipment=_EQUIP)
    assert [a.name for a in out] == ["Dumbbell Bench Press"]


def test_equipment_is_hard_filter_and_bodyweight_always_allowed() -> None:
    pool = [
        _cand(2, "Machine Chest Press", equipment="machine", primary=("chest",)),
        _cand(3, "Push-Up", equipment=None, primary=("chest",)),
        _cand(4, "Cable Fly", equipment="cable", primary=("chest",)),
    ]
    out = rank_alternatives(_TARGET, pool, recovery={}, available_equipment=_EQUIP)
    # machine + cable are not in the profile; bodyweight needs nothing.
    assert [a.name for a in out] == ["Push-Up"]


def test_blocked_ids_and_the_target_itself_never_appear() -> None:
    pool = [
        _TARGET,  # the outgoing Exercise is never its own alternative
        _cand(2, "Dumbbell Bench Press", equipment="dumbbell", primary=("chest",)),
        _cand(3, "Incline Bench Press", primary=("chest",)),
    ]
    out = rank_alternatives(
        _TARGET,
        pool,
        recovery={},
        available_equipment=_EQUIP,
        blocked_ids=frozenset({_id(3)}),
    )
    assert [a.name for a in out] == ["Dumbbell Bench Press"]


def test_more_shared_primary_muscles_rank_higher() -> None:
    target = _cand(1, "Incline Press", primary=("chest", "shoulders"))
    pool = [
        _cand(2, "Chest Fly", primary=("chest",)),
        _cand(3, "Overhead-Lean Press", primary=("chest", "shoulders")),
    ]
    out = rank_alternatives(target, pool, recovery={}, available_equipment=_EQUIP)
    assert [a.name for a in out] == ["Overhead-Lean Press", "Chest Fly"]


def test_has_history_beats_no_history() -> None:
    perf = (SetPerformance(weight_kg=40.0, reps=8),)
    pool = [
        _cand(2, "Never Trained Press", primary=("chest",)),
        _cand(3, "Trained Press", primary=("chest",), history=perf),
    ]
    out = rank_alternatives(_TARGET, pool, recovery={}, available_equipment=_EQUIP)
    assert [a.name for a in out] == ["Trained Press", "Never Trained Press"]
    assert out[0].has_history is True
    assert out[1].has_history is False


def test_fresher_muscles_break_a_history_tie() -> None:
    pool = [
        _cand(2, "Fatigued-Secondary Press", primary=("chest",), secondary=("triceps",)),
        _cand(3, "Fresh-Secondary Press", primary=("chest",), secondary=("biceps",)),
    ]
    out = rank_alternatives(
        _TARGET,
        pool,
        recovery={"triceps": 10.0, "biceps": 100.0},
        available_equipment=_EQUIP,
    )
    assert [a.name for a in out] == ["Fresh-Secondary Press", "Fatigued-Secondary Press"]


def test_deterministic_lower_id_wins_full_tie_and_limit_applies() -> None:
    pool = [_cand(n, f"Press {n}", primary=("chest",)) for n in range(2, 15)]
    out = rank_alternatives(_TARGET, pool, recovery={}, available_equipment=_EQUIP)
    assert len(out) == 8  # default limit
    assert [a.name for a in out] == [f"Press {n}" for n in range(2, 10)]
    limited = rank_alternatives(
        _TARGET, pool, recovery={}, available_equipment=_EQUIP, limit=3
    )
    assert [a.name for a in limited] == ["Press 2", "Press 3", "Press 4"]


def test_prescription_comes_from_the_alternatives_own_history() -> None:
    perf = (SetPerformance(weight_kg=40.0, reps=8),)
    pool = [
        _cand(2, "Trained Press", primary=("chest",), history=perf),
        _cand(3, "New Press", primary=("chest",)),
    ]
    out = rank_alternatives(_TARGET, pool, recovery={}, available_equipment=_EQUIP)
    trained = next(a for a in out if a.name == "Trained Press")
    fresh = next(a for a in out if a.name == "New Press")
    # Progressed off its own last set — not the outgoing Exercise's numbers.
    assert trained.target_weight_kg >= 40.0
    assert trained.is_starting_point is False
    assert fresh.is_starting_point is True
    # The shared muscles are echoed for the "hits the same muscles" UI line.
    assert trained.shared_muscles == ("chest",)
