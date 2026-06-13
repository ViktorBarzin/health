"""Exercise-name matcher: normalised/exact match, aliases, unresolved → manual.

The matcher maps raw Fitbod exercise names onto the shared Exercise library. It
is a pure unit (a name index built from ``(id, name)`` pairs) so the
normalisation, alias and fallback rules are tested without a DB.
"""

import uuid

from app.services.matcher import (
    ExerciseNameIndex,
    normalize_exercise_name,
)


def _idx(*names: str) -> tuple[ExerciseNameIndex, dict[str, uuid.UUID]]:
    """Build an index over the given library names; return it + name→id map."""
    ids = {name: uuid.uuid4() for name in names}
    entries = [(ids[name], name) for name in names]
    return ExerciseNameIndex(entries), ids


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize_exercise_name("  Back   Squat ") == "back squat"


def test_normalize_strips_punctuation() -> None:
    assert normalize_exercise_name("Bench Press (Barbell)") == "bench press barbell"
    assert normalize_exercise_name("Romanian Deadlift - RDL") == "romanian deadlift rdl"


def test_normalize_unifies_hyphen_and_slash_variants() -> None:
    assert normalize_exercise_name("Pull-Up") == normalize_exercise_name("Pull Up")
    assert normalize_exercise_name("Sit/Up") == normalize_exercise_name("Sit Up")


# --------------------------------------------------------------------------- #
# Exact and normalised matching
# --------------------------------------------------------------------------- #


def test_exact_name_resolves() -> None:
    index, ids = _idx("Barbell Squat", "Barbell Bench Press")
    assert index.match("Barbell Squat") == ids["Barbell Squat"]


def test_case_and_punctuation_insensitive_match() -> None:
    index, ids = _idx("Barbell Bench Press - Medium Grip")
    # Different case + missing the qualifier punctuation still normalises equal
    # only if the whole normalised string matches; here it does after casing.
    assert (
        index.match("barbell bench press - medium grip")
        == ids["Barbell Bench Press - Medium Grip"]
    )


def test_whitespace_variants_match() -> None:
    index, ids = _idx("Lat Pulldown")
    assert index.match("Lat   Pulldown") == ids["Lat Pulldown"]


def test_unknown_name_is_unresolved() -> None:
    index, _ = _idx("Barbell Squat")
    assert index.match("Some Machine That Does Not Exist") is None


# --------------------------------------------------------------------------- #
# Aliases: common Fitbod → free-exercise-db name differences
# --------------------------------------------------------------------------- #


def test_alias_back_squat_resolves_to_barbell_squat() -> None:
    index, ids = _idx("Barbell Squat", "Barbell Bench Press")
    # Fitbod calls it "Back Squat"; the library has "Barbell Squat".
    assert index.match("Back Squat") == ids["Barbell Squat"]


def test_alias_only_used_when_target_present() -> None:
    # Library does NOT contain the alias target → no match (don't invent one).
    index, _ = _idx("Leg Press")
    assert index.match("Back Squat") is None


def test_alias_prefers_exact_when_both_exist() -> None:
    # If the library literally has "Back Squat", use it over the alias target.
    index, ids = _idx("Back Squat", "Barbell Squat")
    assert index.match("Back Squat") == ids["Back Squat"]


# --------------------------------------------------------------------------- #
# Batch resolution → resolved map + unresolved list
# --------------------------------------------------------------------------- #


def test_resolve_all_splits_resolved_and_unresolved() -> None:
    index, ids = _idx("Barbell Squat", "Barbell Bench Press")
    resolved, unresolved = index.resolve_all(
        ["Back Squat", "Barbell Bench Press", "Cable Fly Variation X"]
    )
    assert resolved["Back Squat"] == ids["Barbell Squat"]
    assert resolved["Barbell Bench Press"] == ids["Barbell Bench Press"]
    assert unresolved == ["Cable Fly Variation X"]


def test_resolve_all_is_deterministic_for_duplicates() -> None:
    index, ids = _idx("Barbell Squat")
    resolved, unresolved = index.resolve_all(["Back Squat", "Back Squat"])
    assert resolved == {"Back Squat": ids["Barbell Squat"]}
    assert unresolved == []
