"""Recommendation generator core — the deterministic freestyle workout proposal.

The freestyle path (CONTEXT.md "Recommendation": "generated freestyle from
Recovery + Progression state within the user's Gym Profile" when no Program is
active). ADR-0002 fixes this as the **deterministic, explainable** engine core —
no LLM, reproducible run-to-run. This pins its contract:

* only Exercises whose equipment the user HAS are ever selected (the Gym Profile
  is a hard constraint); bodyweight Exercises are always allowed;
* selection is biased toward FRESH muscles (higher Recovery) and de-prioritizes
  fatigued ones, with muscle diversity so it doesn't hammer one group;
* output is DETERMINISTIC for fixed input (stable tie-breaks), and each
  prescribed Exercise carries target sets × reps × weight from Progression.

Pure module: no DB, no clock — the querying layer assembles the candidates,
Recovery map and Progression history; this core only ranks and prescribes.
"""

from __future__ import annotations

import uuid

from app.services.progression import SetPerformance
from app.services.recommendation import (
    DEFAULT_EXERCISE_COUNT,
    DEFAULT_SETS_PER_EXERCISE,
    ExerciseCandidate,
    generate_recommendation,
)


def _ex(
    name: str,
    equipment: str | None,
    primaries: list[str],
    secondaries: list[str] | None = None,
    history: list[SetPerformance] | None = None,
    *,
    ex_id: uuid.UUID | None = None,
) -> ExerciseCandidate:
    """Build one candidate Exercise for the generator."""
    return ExerciseCandidate(
        exercise_id=ex_id or uuid.uuid4(),
        name=name,
        equipment=equipment,
        primary_muscles=tuple(primaries),
        secondary_muscles=tuple(secondaries or []),
        history=tuple(history or []),
    )


# A deterministic id factory so cases that assert ordering are reproducible.
def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


# --------------------------------------------------------------------------- #
# Equipment is a hard constraint
# --------------------------------------------------------------------------- #


def test_only_available_equipment_is_selected() -> None:
    # A barbell Exercise must never be prescribed when the user has no barbell.
    candidates = [
        _ex("Barbell Bench", "barbell", ["chest"]),
        _ex("Dumbbell Press", "dumbbell", ["chest"]),
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}
    )
    names = {item.name for item in rec.exercises}
    assert "Barbell Bench" not in names
    assert "Dumbbell Press" in names


def test_bodyweight_exercises_always_allowed() -> None:
    # "body only" / None equipment needs nothing, so it is selectable even with
    # an empty Gym Profile equipment list.
    candidates = [
        _ex("Push-up", "body only", ["chest"]),
        _ex("Pull-up", None, ["lats"]),
        _ex("Barbell Row", "barbell", ["middle back"]),
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment=set()
    )
    names = {item.name for item in rec.exercises}
    assert "Push-up" in names
    assert "Pull-up" in names
    assert "Barbell Row" not in names


def test_no_selectable_exercises_yields_empty_recommendation() -> None:
    # Everything needs equipment the user lacks → an empty (but valid) proposal.
    candidates = [_ex("Cable Fly", "cable", ["chest"])]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}
    )
    assert rec.exercises == []


# --------------------------------------------------------------------------- #
# Fresh muscles are favoured; fatigued muscles de-prioritized
# --------------------------------------------------------------------------- #


def test_fatigued_muscle_is_deprioritized() -> None:
    # Two equally-available Exercises; chest is fried (low Recovery), back is
    # fresh. With room for only one pick, the fresh-muscle Exercise wins.
    candidates = [
        _ex("Bench", "dumbbell", ["chest"], ex_id=_id(1)),
        _ex("Row", "dumbbell", ["lats"], ex_id=_id(2)),
    ]
    rec = generate_recommendation(
        candidates,
        recovery={"chest": 10.0, "lats": 95.0},
        available_equipment={"dumbbell"},
        exercise_count=1,
    )
    assert [i.name for i in rec.exercises] == ["Row"]


def test_freshest_muscles_lead_the_proposal() -> None:
    # Ordered by the freshness of the muscles worked: the freshest-muscle
    # Exercise is prescribed first.
    candidates = [
        _ex("Bench", "dumbbell", ["chest"], ex_id=_id(1)),
        _ex("Curl", "dumbbell", ["biceps"], ex_id=_id(2)),
        _ex("Squat", "dumbbell", ["quadriceps"], ex_id=_id(3)),
    ]
    rec = generate_recommendation(
        candidates,
        recovery={"chest": 30.0, "biceps": 60.0, "quadriceps": 90.0},
        available_equipment={"dumbbell"},
        exercise_count=3,
    )
    assert [i.name for i in rec.exercises] == ["Squat", "Curl", "Bench"]


def test_muscle_diversity_not_all_one_group() -> None:
    # Five fresh chest Exercises and one fresh back Exercise: diversity means the
    # back Exercise is pulled in rather than prescribing chest five times — once
    # chest is worked, its muscles are de-prioritized for subsequent picks.
    candidates = [
        _ex("Chest A", "dumbbell", ["chest"], ex_id=_id(1)),
        _ex("Chest B", "dumbbell", ["chest"], ex_id=_id(2)),
        _ex("Chest C", "dumbbell", ["chest"], ex_id=_id(3)),
        _ex("Chest D", "dumbbell", ["chest"], ex_id=_id(4)),
        _ex("Back A", "dumbbell", ["lats"], ex_id=_id(5)),
    ]
    rec = generate_recommendation(
        candidates,
        recovery={},  # all fresh
        available_equipment={"dumbbell"},
        exercise_count=2,
    )
    names = [i.name for i in rec.exercises]
    assert "Back A" in names  # diversity pulled in the other group
    assert len([n for n in names if n.startswith("Chest")]) == 1


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_deterministic_for_fixed_input() -> None:
    # Identical input → byte-identical output (selection, order, targets). The
    # generator is the deterministic core (ADR-0002): no clock, no randomness.
    candidates = [
        _ex("A", "dumbbell", ["chest"], ex_id=_id(1)),
        _ex("B", "dumbbell", ["lats"], ex_id=_id(2)),
        _ex("C", "dumbbell", ["quadriceps"], ex_id=_id(3)),
        _ex("D", "dumbbell", ["biceps"], ex_id=_id(4)),
    ]
    kwargs = dict(
        recovery={"chest": 50.0, "lats": 50.0},
        available_equipment={"dumbbell"},
        exercise_count=3,
    )
    first = generate_recommendation(candidates, **kwargs)
    second = generate_recommendation(candidates, **kwargs)
    assert [(i.exercise_id, i.target_reps, i.target_weight_kg) for i in first.exercises] == [
        (i.exercise_id, i.target_reps, i.target_weight_kg) for i in second.exercises
    ]


def test_equal_recovery_ties_break_on_exercise_id() -> None:
    # When two Exercises tie on muscle freshness, the tie breaks on a stable key
    # (the exercise id) so the order never wobbles between runs.
    candidates = [
        _ex("Zeta", "dumbbell", ["chest"], ex_id=_id(2)),
        _ex("Alpha", "dumbbell", ["lats"], ex_id=_id(1)),
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}, exercise_count=2
    )
    # Both fully fresh → identical score → lower id (Alpha=_id(1)) leads.
    assert [i.exercise_id for i in rec.exercises] == [_id(1), _id(2)]


# --------------------------------------------------------------------------- #
# Each prescribed Exercise carries Progression targets
# --------------------------------------------------------------------------- #


def test_prescribes_progression_target_per_exercise() -> None:
    # An Exercise with history gets its double-progression next target; the
    # default number of sets is prescribed.
    candidates = [
        _ex(
            "Bench",
            "dumbbell",
            ["chest"],
            history=[SetPerformance(weight_kg=60.0, reps=12, rir=2)],
            ex_id=_id(1),
        ),
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}, exercise_count=1
    )
    item = rec.exercises[0]
    # 60×12 @ RIR2 (top of 8–12 with reserve) → +2.5 kg, reset to 8 reps.
    assert item.target_weight_kg == 62.5
    assert item.target_reps == 8
    assert item.target_sets == DEFAULT_SETS_PER_EXERCISE
    assert item.is_starting_point is False


def test_first_time_exercise_gets_starting_prescription() -> None:
    # No history → a starting prescription (bottom of the range, weight 0),
    # flagged so the UI can present it as a first guess.
    candidates = [_ex("New Move", "dumbbell", ["chest"], ex_id=_id(1))]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}, exercise_count=1
    )
    item = rec.exercises[0]
    assert item.target_weight_kg == 0.0
    assert item.is_starting_point is True


def test_default_count_and_sets() -> None:
    # With plenty of candidates and defaults, the proposal holds exactly the
    # default number of Exercises, each at the default set count.
    candidates = [
        _ex(f"Ex{n}", "dumbbell", [m], ex_id=_id(n))
        for n, m in enumerate(
            ["chest", "lats", "quadriceps", "biceps", "triceps",
             "hamstrings", "shoulders", "glutes"],
            start=1,
        )
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}
    )
    assert len(rec.exercises) == DEFAULT_EXERCISE_COUNT
    assert all(i.target_sets == DEFAULT_SETS_PER_EXERCISE for i in rec.exercises)


def test_each_selected_exercise_carries_its_worked_muscles() -> None:
    # The proposal echoes the muscles each pick works (for the explainable "why
    # this Exercise" UI), drawn from the candidate's mapping.
    candidates = [
        _ex("Bench", "dumbbell", ["chest"], ["triceps", "shoulders"], ex_id=_id(1)),
    ]
    rec = generate_recommendation(
        candidates, recovery={}, available_equipment={"dumbbell"}, exercise_count=1
    )
    item = rec.exercises[0]
    assert item.primary_muscles == ("chest",)
    assert set(item.secondary_muscles) == {"triceps", "shoulders"}
