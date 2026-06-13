"""Conversational adjust — the LLM-proposes layer (#14, ADR-0002).

ADR-0002 is the contract this pins: *"The LLM proposes; it never decides — the
computed state and the user's edits are authoritative."* So the tests assert:

* the **deterministic** provider works with **no external service** — it parses
  "make it shorter" / "no barbell today" / "I'm tired" / "easier" into a
  structured :class:`Adjustment` (the default path; no ship-dark dependency);
* a proposed adjustment is **validated against Principle bounds** before it's
  applied — a volume scale can't push a slot below its floor nor above its
  ceiling, and dropping every Exercise is refused (the proposal never *decides*
  an unsafe plan);
* applying an adjustment produces editable targets (a new Recommendation) — it
  never mutates anything in place, so the user's later edits still win.

The pure parsing + validation + application all live in :mod:`app.services.adjust`
and are unit-tested here without any network or DB.
"""

import uuid

import pytest

from app.services.adjust import (
    Adjustment,
    AdjustmentBounds,
    DeterministicAdjustProvider,
    apply_adjustment,
    validate_adjustment,
)
from app.services.recommendation import Recommendation, RecommendedExercise


def _ex(
    name: str,
    *,
    sets: int = 4,
    reps: int = 8,
    weight: float = 60.0,
    equipment: str = "barbell",
    primary: tuple[str, ...] = ("chest",),
) -> RecommendedExercise:
    return RecommendedExercise(
        exercise_id=uuid.uuid4(),
        name=name,
        target_sets=sets,
        target_reps=reps,
        target_weight_kg=weight,
        is_starting_point=False,
        primary_muscles=primary,
        secondary_muscles=(),
    )


def _rec(*exercises: RecommendedExercise) -> Recommendation:
    return Recommendation(exercises=list(exercises))


# --------------------------------------------------------------------------- #
# Deterministic provider parses intent (no external service)
# --------------------------------------------------------------------------- #


def test_deterministic_provider_shorter_trims_session() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose("make it shorter", equipment=["barbell", "dumbbell"])
    # "shorter" → fewer exercises (a time cut), expressed as a max_exercises cap.
    assert proposal.max_exercises is not None
    assert proposal.note  # a human explanation accompanies the proposal


def test_deterministic_provider_no_barbell_excludes_equipment() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose("no barbell today", equipment=["barbell", "dumbbell"])
    assert "barbell" in proposal.exclude_equipment


def test_deterministic_provider_tired_scales_volume_down() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose("I'm tired", equipment=["barbell"])
    assert proposal.volume_scale is not None
    assert proposal.volume_scale < 1.0


def test_deterministic_provider_easier_scales_volume_down() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose("can you make it easier", equipment=["barbell"])
    assert proposal.volume_scale is not None and proposal.volume_scale < 1.0


def test_deterministic_provider_dumbbells_only() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose(
        "dumbbells only please", equipment=["barbell", "dumbbell", "machine"]
    )
    # Everything that isn't a dumbbell is excluded.
    assert "barbell" in proposal.exclude_equipment
    assert "machine" in proposal.exclude_equipment
    assert "dumbbell" not in proposal.exclude_equipment


def test_deterministic_provider_unknown_request_is_a_noop_with_note() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose("tell me a joke", equipment=["barbell"])
    # Nothing actionable parsed → an explicit no-op proposal, never a crash.
    assert proposal.is_noop()
    assert proposal.note


def test_deterministic_provider_combines_intents() -> None:
    provider = DeterministicAdjustProvider()
    proposal = provider.propose(
        "shorter and no barbell, I'm tired", equipment=["barbell", "dumbbell"]
    )
    assert proposal.max_exercises is not None
    assert "barbell" in proposal.exclude_equipment
    assert proposal.volume_scale is not None and proposal.volume_scale < 1.0


# --------------------------------------------------------------------------- #
# Validation against Principle bounds (the LLM proposes, the engine validates)
# --------------------------------------------------------------------------- #


def test_validate_clamps_volume_scale_to_floor() -> None:
    # A proposal that would scale volume to near-zero is clamped so no slot drops
    # below its Principle floor.
    bounds = AdjustmentBounds(min_volume_scale=0.5, max_volume_scale=1.2)
    proposed = Adjustment(volume_scale=0.1)
    validated = validate_adjustment(proposed, bounds)
    assert validated.volume_scale == pytest.approx(0.5)


def test_validate_clamps_volume_scale_to_ceiling() -> None:
    bounds = AdjustmentBounds(min_volume_scale=0.5, max_volume_scale=1.2)
    proposed = Adjustment(volume_scale=3.0)
    validated = validate_adjustment(proposed, bounds)
    assert validated.volume_scale == pytest.approx(1.2)


def test_validate_rejects_excluding_all_equipment() -> None:
    # Excluding every available implement would empty the session — refused, so
    # the LLM can't "decide" an impossible plan.
    bounds = AdjustmentBounds(available_equipment=["barbell", "dumbbell"])
    proposed = Adjustment(exclude_equipment=["barbell", "dumbbell"])
    validated = validate_adjustment(proposed, bounds)
    # At least one implement is preserved.
    assert set(validated.exclude_equipment) != {"barbell", "dumbbell"}


def test_validate_caps_max_exercises_to_at_least_one() -> None:
    bounds = AdjustmentBounds()
    proposed = Adjustment(max_exercises=0)
    validated = validate_adjustment(proposed, bounds)
    assert validated.max_exercises is None or validated.max_exercises >= 1


# --------------------------------------------------------------------------- #
# Application produces editable targets (never mutates in place)
# --------------------------------------------------------------------------- #


def test_apply_volume_scale_trims_sets_within_floor() -> None:
    rec = _rec(_ex("Bench", sets=4), _ex("Fly", sets=3))
    adjusted = apply_adjustment(rec, Adjustment(volume_scale=0.5), sets_floor=1)
    assert [e.target_sets for e in adjusted.exercises] == [2, 2]
    # The original is untouched (immutability → user edits later still win).
    assert [e.target_sets for e in rec.exercises] == [4, 3]


def test_apply_volume_scale_never_below_floor() -> None:
    rec = _rec(_ex("Bench", sets=2))
    adjusted = apply_adjustment(rec, Adjustment(volume_scale=0.1), sets_floor=1)
    assert adjusted.exercises[0].target_sets >= 1


def test_apply_exclude_equipment_drops_those_exercises() -> None:
    rec = _rec(
        _ex("Barbell Bench", equipment="barbell"),
        _ex("DB Press", equipment="dumbbell"),
    )
    adjusted = apply_adjustment(
        rec, Adjustment(exclude_equipment=["barbell"]), equipment_by_exercise={
            rec.exercises[0].exercise_id: "barbell",
            rec.exercises[1].exercise_id: "dumbbell",
        }
    )
    names = [e.name for e in adjusted.exercises]
    assert "Barbell Bench" not in names
    assert "DB Press" in names


def test_apply_max_exercises_caps_the_list() -> None:
    rec = _rec(_ex("A"), _ex("B"), _ex("C"), _ex("D"))
    adjusted = apply_adjustment(rec, Adjustment(max_exercises=2))
    assert len(adjusted.exercises) == 2
    # The first two are kept (order preserved).
    assert [e.name for e in adjusted.exercises] == ["A", "B"]


def test_apply_noop_returns_equivalent_recommendation() -> None:
    rec = _rec(_ex("Bench", sets=4))
    adjusted = apply_adjustment(rec, Adjustment())
    assert [e.target_sets for e in adjusted.exercises] == [4]


def test_apply_does_not_empty_when_excluding_all_present_equipment() -> None:
    # Defensive: even if validation were skipped, applying an exclude that would
    # drop everything keeps the proposal honest by leaving the list non-empty is
    # NOT apply's job — but apply must not crash and returns what's left.
    rec = _rec(_ex("Barbell Bench", equipment="barbell"))
    adjusted = apply_adjustment(
        rec,
        Adjustment(exclude_equipment=["barbell"]),
        equipment_by_exercise={rec.exercises[0].exercise_id: "barbell"},
    )
    assert isinstance(adjusted, Recommendation)
