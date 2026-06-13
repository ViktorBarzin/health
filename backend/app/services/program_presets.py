"""Preset catalog — named Programs as pinned parameterizations of the generator.

ADR-0004: "a browsable catalog of named presets (GZCLP, upper/lower hypertrophy
mesocycle, PPL, 5/3/1-style) — presets are pinned parameterizations of the same
generator; no copyrighted commercial program content is reproduced." A preset is
therefore **just a fixed set of quiz answers plus an optional structural style** —
fed through the very same :mod:`app.services.program_generation` generator as a
bespoke quiz. The numbers (volume, reps, deload, …) still come from the Principles
KB for that ``(goal, experience)``; the preset only pins the *answers*, so we
reproduce no program's copyrighted text — only the generic split shape and the
science-derived parameters.

The catalog is small, hand-authored data (like the Principles seed), so it lives
in code here rather than a table. Each :class:`ProgramPreset` carries a stable
``key`` (persisted on the generated Program as ``preset_key`` for provenance), a
display name + blurb, and the quiz answers it pins.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.principle import ExperienceLevel, TrainingGoal
from app.services.program_templates import SplitStyle


@dataclass(frozen=True)
class ProgramPreset:
    """A named, pinned parameterization of the Program generator.

    ``goal`` / ``experience`` / ``days_per_week`` / ``session_minutes`` are the
    quiz answers the preset fixes; ``style`` pins the split shape where more than
    one is reasonable for the day count. Selecting the preset generates a Program
    exactly as if the user had answered the quiz this way.
    """

    key: str
    name: str
    summary: str
    goal: TrainingGoal
    experience: ExperienceLevel
    days_per_week: int
    session_minutes: int
    style: SplitStyle


# The catalog. Four structurally-distinct, well-known program *shapes* — their
# numbers come from Principles, not from the original programs' copyrighted text.
PRESETS: tuple[ProgramPreset, ...] = (
    ProgramPreset(
        key="gzclp",
        name="GZCLP — Linear Beginner",
        summary=(
            "A 3-day full-body linear-progression program for beginners chasing "
            "strength: heavy low-rep main work, science-based volume and a "
            "scheduled deload."
        ),
        goal=TrainingGoal.strength,
        experience=ExperienceLevel.beginner,
        days_per_week=3,
        session_minutes=60,
        style=SplitStyle.full_body,
    ),
    ProgramPreset(
        key="upper-lower-hypertrophy",
        name="Upper / Lower Hypertrophy",
        summary=(
            "A 4-day upper/lower split for building muscle: each muscle trained "
            "twice a week with a ramping moderate-rep volume block and a deload."
        ),
        goal=TrainingGoal.bulk,
        experience=ExperienceLevel.intermediate,
        days_per_week=4,
        session_minutes=70,
        style=SplitStyle.upper_lower,
    ),
    ProgramPreset(
        key="ppl-hypertrophy",
        name="Push / Pull / Legs",
        summary=(
            "A 6-day push/pull/legs split for higher training frequency and "
            "volume: each muscle hit twice a week, moderate reps, ramping volume "
            "and a deload."
        ),
        goal=TrainingGoal.bulk,
        experience=ExperienceLevel.intermediate,
        days_per_week=6,
        session_minutes=70,
        style=SplitStyle.push_pull_legs,
    ),
    ProgramPreset(
        key="531-strength",
        name="5/3/1-style Strength",
        summary=(
            "A 4-day upper/lower strength block: heavy low-rep main lifts, "
            "periodized over a mesocycle with a scheduled deload."
        ),
        goal=TrainingGoal.strength,
        experience=ExperienceLevel.intermediate,
        days_per_week=4,
        session_minutes=75,
        style=SplitStyle.upper_lower,
    ),
)

_BY_KEY: dict[str, ProgramPreset] = {p.key: p for p in PRESETS}


def preset_by_key(key: str) -> ProgramPreset | None:
    """Look one preset up by its stable ``key`` (``None`` if unknown)."""
    return _BY_KEY.get(key)
