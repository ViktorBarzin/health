"""Exercise-name matcher — map raw Fitbod names onto the shared Exercise library.

Fitbod exports plain gym names ("Back Squat", "Bench Press", "Lat Pulldown");
the library (free-exercise-db) uses formal catalog names ("Barbell Squat",
"Barbell Bench Press - Medium Grip", "Wide-Grip Lat Pulldown"). This module is
the pure matcher that bridges the two:

1. **Normalise** both sides — lower-case, replace separators (``-``/``/``) with
   spaces, drop other punctuation, collapse whitespace. So "Pull-Up" and "Pull
   Up" compare equal, "Bench Press (Barbell)" loses its parentheses, etc.
2. **Exact (normalised) match** — if a library Exercise's normalised name equals
   the normalised Fitbod name, resolve to it.
3. **Alias** — a small, curated table of normalised Fitbod-name → normalised
   library-name for the common cases where the two vocabularies differ (Fitbod's
   "Back Squat" ↦ the library's "Barbell Squat"). An alias only resolves if its
   **target actually exists** in this library — we never invent a match. An exact
   match always wins over an alias.

Names that resolve none of these are returned as **unresolved**, to be sent to
the manual-match UI (the user picks the library Exercise or creates a custom
one). The matcher is built as a clean, tested unit; the DB glue that turns the
resolution into Sets lives in :mod:`app.services.fitbod_import`.

Kept deliberately conservative: aliases are a hand-curated list of unambiguous
synonyms, not fuzzy string distance. Fuzzy matching risks silently mapping
"Front Squat" onto "Back Squat" — far worse than asking the user once. YAGNI:
the unresolved-name UI is the safety net, so the alias table only needs to cover
the high-frequency barbell/dumbbell/machine staples.
"""

from __future__ import annotations

import re
import uuid

# Strip every character that isn't alphanumeric or whitespace AFTER separators
# have been spaced out. Keeps digits ("3/4 Sit-Up" → "3 4 sit up").
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")
# Separators that should become spaces rather than vanish, so "Pull-Up" and
# "Sit/Up" tokenise the same as their spaced forms.
_SEPARATORS = re.compile(r"[-/]")


def normalize_exercise_name(name: str) -> str:
    """Canonical comparison form of an exercise name.

    Lower-cases, turns ``-``/``/`` separators into spaces, removes remaining
    punctuation, and collapses runs of whitespace. Two names that differ only by
    case, punctuation or spacing normalise to the same string.
    """
    lowered = name.strip().lower()
    spaced = _SEPARATORS.sub(" ", lowered)
    cleaned = _NON_ALNUM.sub(" ", spaced)
    return _WHITESPACE.sub(" ", cleaned).strip()


# Curated alias table: normalised Fitbod name → normalised library name. Only
# applied when the target exists in the library being matched against (so a
# library that lacks the target falls through to "unresolved" rather than a
# wrong guess). Authored from the free-exercise-db catalog vocabulary.
_ALIASES_RAW: dict[str, str] = {
    # Squats
    "back squat": "barbell squat",
    "barbell back squat": "barbell squat",
    "front squat": "front squat clean grip",
    "barbell front squat": "front squat clean grip",
    # Presses
    "bench press": "barbell bench press medium grip",
    "barbell bench press": "barbell bench press medium grip",
    "flat barbell bench press": "barbell bench press medium grip",
    "incline bench press": "barbell incline bench press medium grip",
    "incline barbell bench press": "barbell incline bench press medium grip",
    "overhead press": "standing military press",
    "barbell overhead press": "standing military press",
    "military press": "standing military press",
    "ohp": "standing military press",
    "seated overhead press": "seated barbell military press",
    # Deadlifts
    "deadlift": "barbell deadlift",
    "conventional deadlift": "barbell deadlift",
    "romanian deadlift": "romanian deadlift",
    "rdl": "romanian deadlift",
    # Pulls / rows
    "pull up": "pullups",
    "pullup": "pullups",
    "chin up": "chin up",
    "barbell row": "bent over barbell row",
    "bent over row": "bent over barbell row",
    "bent over barbell row": "bent over barbell row",
    "lat pulldown": "wide grip lat pulldown",
    "wide grip lat pulldown": "wide grip lat pulldown",
    # Legs
    "leg press": "leg press",
    "leg extension": "leg extensions",
    "leg curl": "lying leg curls",
    "lying leg curl": "lying leg curls",
    "seated leg curl": "seated leg curl",
    "walking lunge": "barbell walking lunge",
    "hip thrust": "barbell hip thrust",
    "barbell hip thrust": "barbell hip thrust",
    # Arms / shoulders
    "bicep curl": "barbell curl",
    "barbell curl": "barbell curl",
    "hammer curl": "alternate hammer curl",
    "lateral raise": "side lateral raise",
    "dumbbell lateral raise": "side lateral raise",
    "tricep dip": "dips triceps version",
    "dip": "dips triceps version",
    "dips": "dips triceps version",
    # Core
    "sit up": "3 4 sit up",
    "situp": "3 4 sit up",
}


class ExerciseNameIndex:
    """A name → Exercise-id index supporting exact/normalised + alias matching.

    Built once from the library Exercises visible to a user (global ∪ their
    custom — passed in as ``(id, name)`` pairs), then queried per Fitbod name.
    On a normalised-name collision (two library rows normalise the same), the
    first one wins deterministically by insertion order, so callers should pass
    the entries in a stable order (e.g. sorted by name).
    """

    def __init__(self, entries: list[tuple[uuid.UUID, str]]):
        self._by_norm: dict[str, uuid.UUID] = {}
        for ex_id, name in entries:
            key = normalize_exercise_name(name)
            self._by_norm.setdefault(key, ex_id)
        # Resolve the raw alias table against THIS library's available targets,
        # so an alias only fires when its target exists here. Aliases never
        # override a real exact name (handled at match time, exact-first).
        self._aliases: dict[str, uuid.UUID] = {}
        for fitbod_norm, target_norm in _ALIASES_RAW.items():
            target_id = self._by_norm.get(target_norm)
            if target_id is not None:
                self._aliases[fitbod_norm] = target_id

    def match(self, name: str) -> uuid.UUID | None:
        """Resolve one Fitbod name to a library Exercise id, or ``None``.

        Exact (normalised) match first; then the alias table. ``None`` means the
        name is unresolved and belongs in the manual-match UI.
        """
        norm = normalize_exercise_name(name)
        if not norm:
            return None
        exact = self._by_norm.get(norm)
        if exact is not None:
            return exact
        return self._aliases.get(norm)

    def resolve_all(
        self, names: list[str]
    ) -> tuple[dict[str, uuid.UUID], list[str]]:
        """Resolve many names → (resolved {name: id}, sorted unresolved names).

        The returned maps key on the **raw** Fitbod names (what the importer and
        UI carry), de-duplicated. Unresolved names are sorted for a stable UI.
        """
        resolved: dict[str, uuid.UUID] = {}
        unresolved: set[str] = set()
        for name in names:
            if name in resolved or name in unresolved:
                continue
            hit = self.match(name)
            if hit is not None:
                resolved[name] = hit
            else:
                unresolved.add(name)
        return resolved, sorted(unresolved)
