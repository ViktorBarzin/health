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
    Muscle.middle_back,
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


# Authored templates keyed by (days_per_week, style). EVERY entry trains each
# muscle it touches >= 2x/week — the ``training-frequency`` floor — and
# :func:`app.services.program_generation.generate_program` re-asserts that floor at
# runtime against the chosen template (so a non-compliant template can never ship).
# A split that can't meet 2x/week at a given day count is simply NOT offered: at
# 3 days/week only full-body does (PPL@3 would train each muscle once), so PPL is
# offered only where the day count supports 2x (>=6 days).
_TEMPLATES: dict[tuple[int, SplitStyle], tuple[DayTemplate, ...]] = {
    # --- 2 days: full body twice ------------------------------------------- #
    (2, SplitStyle.full_body): _full_body(2),
    # --- 3 days: full body thrice (the only 2x-compliant 3-day split) ------ #
    (3, SplitStyle.full_body): _full_body(3),
    # --- 4 days: upper/lower twice ----------------------------------------- #
    (4, SplitStyle.upper_lower): (
        DayTemplate(name="Upper A", muscles=_UPPER),
        DayTemplate(name="Lower A", muscles=_LOWER),
        DayTemplate(name="Upper B", muscles=_UPPER),
        DayTemplate(name="Lower B", muscles=_LOWER),
    ),
    # --- 5 days: upper/lower twice + a full-body day ----------------------- #
    # Symmetric U/L/U/L + Full: every major muscle is trained on two Upper or two
    # Lower days (plus the Full day), in EARLY slots, so the session-length slot
    # cap can't drop a muscle below 2x/week (an asymmetric PPL+U/L 5-day could).
    (5, SplitStyle.upper_lower): (
        DayTemplate(name="Upper A", muscles=_UPPER),
        DayTemplate(name="Lower A", muscles=_LOWER),
        DayTemplate(name="Upper B", muscles=_UPPER),
        DayTemplate(name="Lower B", muscles=_LOWER),
        DayTemplate(name="Full Body", muscles=_FULL),
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
    5: SplitStyle.upper_lower,
    6: SplitStyle.push_pull_legs,
}

#: The day counts the catalog of splits supports. The quiz constrains to these.
SUPPORTED_DAYS: tuple[int, ...] = tuple(sorted(_DEFAULT_STYLE))

#: The major muscles the ``training-frequency`` floor is enforced on — the
#: compound-movement primary movers a split is structurally built around, which
#: the frequency dose-response literature (Schoenfeld 2016) studies. Accessory /
#: incidental muscles (abdominals, calves, forearms, traps, neck, abductors,
#: adductors) are intentionally NOT floor-enforced: they get incidental work and
#: are not what a split's frequency is organised around, so requiring 2x/week of
#: them would force artificial slots. The generator asserts the floor for these.
MAJOR_MUSCLES: frozenset[str] = frozenset(
    {
        Muscle.chest.value,
        Muscle.lats.value,
        Muscle.middle_back.value,
        Muscle.shoulders.value,
        Muscle.biceps.value,
        Muscle.triceps.value,
        Muscle.quadriceps.value,
        Muscle.hamstrings.value,
        Muscle.glutes.value,
    }
)


def major_muscle_frequencies(
    days: "tuple[DayTemplate, ...] | list",
) -> dict[str, int]:
    """Count how many of ``days`` train each MAJOR muscle (for the floor check).

    Accepts the authored :class:`DayTemplate` tuple (``.muscles`` are
    :class:`~app.models.exercise.Muscle`) or any day objects exposing ``.muscles``
    as muscle-value strings. Only :data:`MAJOR_MUSCLES` are counted.
    """
    counts: dict[str, int] = {}
    for day in days:
        seen_today: set[str] = set()
        for m in day.muscles:
            value = m.value if hasattr(m, "value") else str(m)
            if value in MAJOR_MUSCLES and value not in seen_today:
                seen_today.add(value)
                counts[value] = counts.get(value, 0) + 1
    return counts


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
