"""Conversational adjust — the LLM-proposes layer over today's Recommendation.

CONTEXT.md + ADR-0002: a "make it shorter / no barbell today / I'm tired" style
adjustment that re-shapes today's proposal. The cardinal rule (ADR-0002): **the
LLM proposes; it never decides**. So this module is built as three separable,
testable pieces with the engine — not the model — holding final authority:

1. a **provider** (behind the :class:`AdjustProvider` ABC, the same swappable-
   provider pattern the rest of the platform uses) turns the user's free-text
   request into a *structured* :class:`Adjustment` **proposal**. The default
   :class:`DeterministicAdjustProvider` is a rules-based parser that needs **no
   external service** — so the feature ships working, never dark. A real LLM
   provider calling the in-cluster claude-agent-service lives in
   :mod:`app.services.adjust_agent`, gated behind an env var (default OFF);

2. :func:`validate_adjustment` **clamps the proposal to Principle bounds** — a
   volume scale can't push a slot below its floor or above its ceiling, an
   equipment exclusion can't empty the session, the exercise cap stays ≥ 1. This
   is where "the LLM proposes, the engine decides" is enforced: whatever a
   provider returns is bounded before anything is applied;

3. :func:`apply_adjustment` produces a **new** Recommendation (never mutates in
   place) of editable targets. Starting it instantiates Sets the user logs
   against and freely overwrites — so the user's edits always win.

The provider's job is *only* to map fuzzy language to the structured levers; it
cannot invent a prescription. The levers themselves are deliberately small and
safe (volume scale, equipment exclusion, exercise cap) — the same knobs
deterministic autoregulation uses — so a proposal can never produce a workout the
engine couldn't.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

from app.services.recommendation import Recommendation, RecommendedExercise

# --------------------------------------------------------------------------- #
# Bounds defaults — the safe envelope a proposal is clamped into. Documented in
# place; these mirror the autoregulation philosophy (move within, never beyond).
# --------------------------------------------------------------------------- #

#: A conversational adjust may trim volume to at most this fraction (50%) — the
#: same floor autoregulation uses; below this it stops being "the same session,
#: lighter" and becomes a different plan the engine didn't generate.
_DEFAULT_MIN_VOLUME_SCALE: float = 0.5
#: …and raise it to at most this fraction (a small, opt-in bump).
_DEFAULT_MAX_VOLUME_SCALE: float = 1.2

#: The volume scale the deterministic provider proposes for a "tired/easier"
#: request — a clear but bounded cut.
_TIRED_VOLUME_SCALE: float = 0.7
#: The exercise cap a "shorter" request proposes (a typical short session).
_SHORTER_MAX_EXERCISES: int = 3


@dataclass(frozen=True)
class Adjustment:
    """A structured, bounded proposal to re-shape today's Recommendation.

    Every field is optional; an all-``None`` adjustment is a no-op
    (:meth:`is_noop`). ``volume_scale`` multiplies each slot's set count;
    ``exclude_equipment`` drops Exercises needing any listed implement;
    ``max_exercises`` caps the list length. These are the only levers — the LLM
    cannot prescribe a raw set/weight, only nudge the engine's own output.
    """

    volume_scale: float | None = None
    exclude_equipment: list[str] = field(default_factory=list)
    max_exercises: int | None = None
    note: str = ""

    def is_noop(self) -> bool:
        """Whether this proposal changes nothing (nothing actionable parsed)."""
        return (
            self.volume_scale is None
            and not self.exclude_equipment
            and self.max_exercises is None
        )


@dataclass(frozen=True)
class AdjustmentBounds:
    """The Principle/equipment envelope a proposal is validated into.

    ``min_volume_scale`` / ``max_volume_scale`` bound how far volume may move (so
    a clamp keeps every slot inside its Principle band); ``available_equipment``
    is what the Gym Profile holds, so :func:`validate_adjustment` can refuse an
    exclusion that would leave the user with nothing.
    """

    min_volume_scale: float = _DEFAULT_MIN_VOLUME_SCALE
    max_volume_scale: float = _DEFAULT_MAX_VOLUME_SCALE
    available_equipment: list[str] = field(default_factory=list)


class AdjustProvider(ABC):
    """Turns a free-text adjust request into a structured :class:`Adjustment`.

    The swappable boundary (ADR-0002): the deterministic default and the
    claude-agent-service LLM both implement this. A provider only *proposes* —
    its output is always validated (:func:`validate_adjustment`) before it's
    applied, so a provider can never decide an out-of-bounds plan.
    """

    @abstractmethod
    def propose(self, request: str, *, equipment: list[str]) -> Adjustment:
        """Propose a structured adjustment for ``request`` given the user's equipment."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Deterministic provider — rules-based, no external service (the default)
# --------------------------------------------------------------------------- #

# Phrase → intent keyword sets. Kept small and explicit; matched case-insensitively
# as substrings so natural phrasing ("can you make it shorter?") still parses.
_SHORTER_CUES = ("shorter", "quick", "less time", "short on time", "in a hurry", "rush")
_TIRED_CUES = ("tired", "exhausted", "easier", "go easy", "easy day", "wiped", "fatigued", "drained", "sore")
_EQUIPMENT_WORDS = (
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "kettlebell",
    "bodyweight",
    "band",
    "smith machine",
    "ez curl bar",
)


class DeterministicAdjustProvider(AdjustProvider):
    """Rules-based adjust provider — works with no external service (the default).

    Parses a small, well-documented vocabulary into the structured levers:

    * "shorter" / "quick" / "in a hurry" → cap the exercise count;
    * "no <equipment>" → exclude that implement;
    * "<equipment> only" → exclude every *other* available implement;
    * "tired" / "easier" / "sore" → scale volume down.

    Multiple intents in one message combine. Anything it can't parse becomes an
    explicit **no-op** proposal with a note — never a crash, never a guess.
    """

    def propose(self, request: str, *, equipment: list[str]) -> Adjustment:
        text = request.lower()
        notes: list[str] = []

        max_exercises: int | None = None
        if any(cue in text for cue in _SHORTER_CUES):
            max_exercises = _SHORTER_MAX_EXERCISES
            notes.append("trimmed to a shorter session")

        volume_scale: float | None = None
        if any(cue in text for cue in _TIRED_CUES):
            volume_scale = _TIRED_VOLUME_SCALE
            notes.append("eased the volume back")

        exclude = self._parse_equipment(text, equipment)
        if exclude:
            notes.append(f"dropped {', '.join(sorted(exclude))}")

        adjustment = Adjustment(
            volume_scale=volume_scale,
            exclude_equipment=sorted(exclude),
            max_exercises=max_exercises,
            note="; ".join(notes) if notes else (
                "I couldn't act on that — try 'make it shorter', "
                "'no barbell', or 'I'm tired'."
            ),
        )
        return adjustment

    def _parse_equipment(self, text: str, equipment: list[str]) -> set[str]:
        """Resolve "no X" / "X only" phrases into the set of implements to exclude.

        Matches the singular *and* a naive plural ("dumbbell" / "dumbbells") so
        natural phrasing parses, and only acts on implements the user actually
        has so we never propose dropping something that isn't in the session.
        """
        available = {e.lower() for e in equipment}
        exclude: set[str] = set()

        def _forms(word: str) -> tuple[str, ...]:
            return (word, f"{word}s")

        # "<equipment> only" / "just <equipment>" → exclude everything else.
        for word in _EQUIPMENT_WORDS:
            if word not in available:
                continue
            if any(
                f"{form} only" in text or f"just {form}" in text
                for form in _forms(word)
            ):
                exclude |= {e for e in available if e != word}

        # "no <equipment>" / "without <equipment>" / "skip <equipment>".
        for word in _EQUIPMENT_WORDS:
            if word not in available:
                continue
            if any(
                p in text
                for form in _forms(word)
                for p in (f"no {form}", f"without {form}", f"skip {form}", f"avoid {form}")
            ):
                exclude.add(word)

        return exclude


# --------------------------------------------------------------------------- #
# Validation — clamp a proposal into Principle/equipment bounds
# --------------------------------------------------------------------------- #


def validate_adjustment(
    adjustment: Adjustment, bounds: AdjustmentBounds
) -> Adjustment:
    """Clamp a proposed adjustment into its safe envelope (the engine decides).

    * ``volume_scale`` is clamped to ``[min_volume_scale, max_volume_scale]``;
    * an ``exclude_equipment`` that would remove **every** available implement is
      trimmed so at least one remains (a proposal can't empty the session);
    * ``max_exercises`` is floored at 1 (or dropped if non-positive).

    Returns a new, bounded :class:`Adjustment`. This is the ADR-0002 boundary: no
    matter what a provider returns, only the clamped result is ever applied.
    """
    volume_scale = adjustment.volume_scale
    if volume_scale is not None:
        volume_scale = max(
            bounds.min_volume_scale, min(bounds.max_volume_scale, volume_scale)
        )

    exclude = list(adjustment.exclude_equipment)
    available = {e.lower() for e in bounds.available_equipment}
    if available and {e.lower() for e in exclude} >= available:
        # Would leave nothing — keep one implement (the first available, stably).
        keep = sorted(available)[0]
        exclude = [e for e in exclude if e.lower() != keep]

    max_exercises = adjustment.max_exercises
    if max_exercises is not None and max_exercises < 1:
        max_exercises = None

    return replace(
        adjustment,
        volume_scale=volume_scale,
        exclude_equipment=exclude,
        max_exercises=max_exercises,
    )


# --------------------------------------------------------------------------- #
# Application — produce a NEW Recommendation of editable targets
# --------------------------------------------------------------------------- #


def _scaled_sets(sets: int, scale: float, floor: int) -> int:
    """Scale a set count, never below the floor / one working set."""
    return max(max(1, floor), int(round(sets * scale)))


def apply_adjustment(
    recommendation: Recommendation,
    adjustment: Adjustment,
    *,
    sets_floor: int = 1,
    equipment_by_exercise: dict[uuid.UUID, str | None] | None = None,
) -> Recommendation:
    """Apply a (validated) adjustment, returning a NEW Recommendation.

    Order of operations: exclude by equipment, scale volume, then cap the count.
    The input is never mutated — the result is fresh editable targets the user
    logs against and overwrites (so their edits win). ``sets_floor`` is the
    per-slot floor a volume cut respects; ``equipment_by_exercise`` maps each
    Exercise to its required implement for the exclusion (omitted ⇒ no exclusion).
    """
    exercises: list[RecommendedExercise] = list(recommendation.exercises)

    # 1. Equipment exclusion.
    if adjustment.exclude_equipment and equipment_by_exercise is not None:
        excluded = {e.lower() for e in adjustment.exclude_equipment}
        exercises = [
            ex
            for ex in exercises
            if (equipment_by_exercise.get(ex.exercise_id) or "").lower() not in excluded
        ]

    # 2. Volume scale.
    if adjustment.volume_scale is not None:
        exercises = [
            replace(
                ex,
                target_sets=_scaled_sets(
                    ex.target_sets, adjustment.volume_scale, sets_floor
                ),
            )
            for ex in exercises
        ]

    # 3. Exercise cap.
    if adjustment.max_exercises is not None:
        exercises = exercises[: adjustment.max_exercises]

    return Recommendation(exercises=exercises)
