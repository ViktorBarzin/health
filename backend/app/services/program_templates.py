"""Split templates — the structural shapes a Program's training week takes.

A **split** is the structural choice the generator makes from ``days_per_week``
(CONTEXT.md "Program": "split structure"). It is *not* a number derived from a
Principle — it is a generic, well-known strength-training layout (full-body,
upper/lower, push/pull/legs). These templates carry **no copyrighted program
content**: just which muscle groups land on which training day, drawn from the
dataset :class:`~app.models.exercise.Muscle` enum.

Each template is a list of :class:`DayTemplate` (the training days of one weekly
microcycle), each a name plus an ordered list of muscle **slots** the
Recommendation later fills with concrete Exercises. The templates are authored so
that at every supported day count each *major* muscle group is trained at least
twice per week — the :data:`~app.models.principle` frequency floor
(``training-frequency`` ≥ 2×/week); :mod:`app.services.program_generation`
asserts that floor against the chosen template (a violation would be a template
bug, pinned by a test).

A :class:`SplitStyle` lets a preset pin a particular shape (e.g. PPL at 6
days/week) where more than one is reasonable; without a style the default for the
day count is used.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.models.exercise import Muscle


class SplitStyle(str, enum.Enum):
    """A structural split family a preset may pin (else the day-count default)."""

    full_body = "full_body"
    upper_lower = "upper_lower"
    push_pull_legs = "push_pull_legs"


@dataclass(frozen=True)
class DayTemplate:
    """One training day's shape: a name and the ordered muscle slots to fill."""

    name: str
    # Ordered muscle slots. A muscle may appear once per day; the generator caps
    # how many slots a day keeps by the session-length budget.
    muscles: tuple[Muscle, ...]


# The muscle vocabulary the slots draw from. "Back" is split across the dataset's
# lats / middle_back; "legs" across quadriceps / hamstrings / glutes / calves.
_PUSH = (Muscle.chest, Muscle.shoulders, Muscle.triceps)
_PULL = (Muscle.lats, Muscle.middle_back, Muscle.biceps)
_LEGS = (Muscle.quadriceps, Muscle.hamstrings, Muscle.glutes, Muscle.calves)
_UPPER = (
    Muscle.chest,
    Muscle.lats,
    Muscle.shoulders,
    Muscle.biceps,
    Muscle.triceps,
)
_LOWER = (Muscle.quadriceps, Muscle.hamstrings, Muscle.glutes, Muscle.calves)
_FULL = (
    Muscle.quadriceps,
    Muscle.chest,
    Muscle.lats,
    Muscle.hamstrings,
    Muscle.shoulders,
    Muscle.abdominals,
)


def _full_body(n: int) -> tuple[DayTemplate, ...]:
    """``n`` full-body days, suffixed A/B/C… so each day reads distinctly."""
    return tuple(
        DayTemplate(name=f"Full Body {chr(ord('A') + i)}", muscles=_FULL)
        for i in range(n)
    )


# Authored templates keyed by (days_per_week, style). Every entry trains each
# major muscle >= 2x/week (the frequency floor) — pinned by a generation test.
_TEMPLATES: dict[tuple[int, SplitStyle], tuple[DayTemplate, ...]] = {
    # --- 2 days: full body twice ------------------------------------------- #
    (2, SplitStyle.full_body): _full_body(2),
    # --- 3 days: full body thrice (default) or PPL ------------------------- #
    (3, SplitStyle.full_body): _full_body(3),
    (3, SplitStyle.push_pull_legs): (
        DayTemplate(name="Push", muscles=_PUSH),
        DayTemplate(name="Pull", muscles=_PULL),
        DayTemplate(name="Legs", muscles=_LEGS),
    ),
    # --- 4 days: upper/lower twice ----------------------------------------- #
    (4, SplitStyle.upper_lower): (
        DayTemplate(name="Upper A", muscles=_UPPER),
        DayTemplate(name="Lower A", muscles=_LOWER),
        DayTemplate(name="Upper B", muscles=_UPPER),
        DayTemplate(name="Lower B", muscles=_LOWER),
    ),
    # --- 5 days: PPL + upper/lower ----------------------------------------- #
    (5, SplitStyle.push_pull_legs): (
        DayTemplate(name="Push", muscles=_PUSH),
        DayTemplate(name="Pull", muscles=_PULL),
        DayTemplate(name="Legs", muscles=_LEGS),
        DayTemplate(name="Upper", muscles=_UPPER),
        DayTemplate(name="Lower", muscles=_LOWER),
    ),
    # --- 6 days: PPL twice ------------------------------------------------- #
    (6, SplitStyle.push_pull_legs): (
        DayTemplate(name="Push A", muscles=_PUSH),
        DayTemplate(name="Pull A", muscles=_PULL),
        DayTemplate(name="Legs A", muscles=_LEGS),
        DayTemplate(name="Push B", muscles=_PUSH),
        DayTemplate(name="Pull B", muscles=_PULL),
        DayTemplate(name="Legs B", muscles=_LEGS),
    ),
}

# The default style chosen for each day count when a preset pins none.
_DEFAULT_STYLE: dict[int, SplitStyle] = {
    2: SplitStyle.full_body,
    3: SplitStyle.full_body,
    4: SplitStyle.upper_lower,
    5: SplitStyle.push_pull_legs,
    6: SplitStyle.push_pull_legs,
}

#: The day counts the catalog of splits supports. The quiz constrains to these.
SUPPORTED_DAYS: tuple[int, ...] = tuple(sorted(_DEFAULT_STYLE))


def split_for(
    days_per_week: int, style: SplitStyle | None = None
) -> tuple[DayTemplate, ...]:
    """The split template for a day count (and optional pinned style).

    Falls back to the day count's default style when ``style`` is ``None`` or no
    template exists for the requested ``(days, style)`` pair. Day counts outside
    :data:`SUPPORTED_DAYS` clamp to the nearest supported count, so the generator
    always has a valid split (the quiz UI only offers supported counts; this is a
    defensive clamp). Returns the authored, frequency-floor-satisfying day list.
    """
    days = min(SUPPORTED_DAYS, key=lambda d: (abs(d - days_per_week), d))
    chosen_style = style or _DEFAULT_STYLE[days]
    template = _TEMPLATES.get((days, chosen_style))
    if template is None:
        template = _TEMPLATES[(days, _DEFAULT_STYLE[days])]
    return template
