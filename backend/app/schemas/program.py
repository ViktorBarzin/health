"""Pydantic schemas for the Program endpoints (#13, ADR-0004).

A **Program** is a generated multi-week schedule (CONTEXT.md). The wire shape
exposes the split days, the ramping per-muscle weekly volume, and the
**provenance** receipt (each generated number → its Principle key) so the overview
can already show "why this number" and #14 can deep-link to the full citation.

Generation is driven by the guided quiz (:class:`GenerateProgramRequest`) or a
catalog preset; both feed the same deterministic generator. Every numeric
parameter is Principle-derived — these schemas never let a client supply a
training number, only the quiz answers.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.principle import ExperienceLevel, TrainingGoal
from app.models.program import ProgramStatus
from app.services.program_templates import SUPPORTED_DAYS


# Session-length bounds (minutes): a gym visit, not an all-day plan. The quiz UI
# offers a few presets within this; the API clamps defensively.
_MIN_SESSION_MIN = 20
_MAX_SESSION_MIN = 120


class GenerateProgramRequest(BaseModel):
    """The guided-quiz answers, or a preset selection, that generate a Program.

    Supply ``preset_key`` to generate from the catalog (the other fields are then
    ignored — the preset pins them); otherwise supply the quiz answers. Every
    training *number* is derived from Principles server-side, never sent here.
    """

    preset_key: str | None = None
    goal: TrainingGoal | None = None
    experience: ExperienceLevel | None = None
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    session_minutes: int | None = Field(
        default=None, ge=_MIN_SESSION_MIN, le=_MAX_SESSION_MIN
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _require_quiz_or_preset(self) -> "GenerateProgramRequest":
        """Either a preset, or the full quiz (goal/experience/days/length)."""
        if self.preset_key:
            return self
        missing = [
            name
            for name, val in (
                ("goal", self.goal),
                ("experience", self.experience),
                ("days_per_week", self.days_per_week),
                ("session_minutes", self.session_minutes),
            )
            if val is None
        ]
        if missing:
            raise ValueError(
                "provide preset_key, or all of: " + ", ".join(missing)
            )
        if self.days_per_week not in SUPPORTED_DAYS:
            raise ValueError(
                f"days_per_week must be one of {list(SUPPORTED_DAYS)}"
            )
        return self


class ParamProvenance(BaseModel):
    """One generated parameter's receipt: which Principle it came from + the value."""

    principle_key: str
    value: float
    unit: str | None = None
    min: float | None = None
    max: float | None = None


class ProgramDayRead(BaseModel):
    """One training day in the split: its name and ordered muscle slots."""

    day_index: int
    name: str
    # The raw slot dicts ({"muscle": "chest"}, …) the generator produced.
    slots: list[dict] = []

    model_config = {"from_attributes": True}


class MuscleVolumeRead(BaseModel):
    """A per-muscle weekly volume target for one week (ramps, then deloads)."""

    muscle: str
    week: int
    target_sets: int
    is_deload: bool

    model_config = {"from_attributes": True}


class ProgramSummary(BaseModel):
    """List-view shape for a Program: the header without the day/volume detail."""

    id: uuid.UUID
    name: str
    preset_key: str | None = None
    goal: TrainingGoal
    experience: ExperienceLevel
    days_per_week: int
    session_minutes: int
    mesocycle_weeks: int
    total_weeks: int
    deload_week: int
    rep_range_low: int
    rep_range_high: int
    effort_rir: int
    status: ProgramStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ProgramDetail(ProgramSummary):
    """Detail-view shape: the Program plus its split days, volume ramp, provenance."""

    days: list[ProgramDayRead] = []
    muscle_volumes: list[MuscleVolumeRead] = []
    provenance: dict[str, ParamProvenance] = {}


class PresetRead(BaseModel):
    """One catalog preset, for the browse list."""

    key: str
    name: str
    summary: str
    goal: TrainingGoal
    experience: ExperienceLevel
    days_per_week: int
    session_minutes: int


class QuizOptions(BaseModel):
    """The enum/option sets the quiz UI renders (so nothing is hardcoded client-side)."""

    goals: list[dict]
    experience_levels: list[dict]
    days_per_week: list[int]
    session_minutes: list[int]
