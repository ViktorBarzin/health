"""Pydantic schemas for the training-analytics endpoints (#10).

Three read-only views over a user's logged Sets, all derived from existing tables
(no new storage): per-muscle **Recovery** (freshness), per-muscle **weekly
volume**, and per-Exercise **estimated-1RM trend**. Muscle and role travel as their
enum string values (``"chest"``, ``"primary"``) so the SVG body-map can key
straight off them.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.exercise import MuscleRole


class MuscleRecovery(BaseModel):
    """One muscle group's current Recovery score.

    ``recovery`` is 0–100 (100 = fully recovered/fresh). ``muscle`` is the muscle
    enum value. Every muscle in the catalog is returned (untrained ones at 100),
    so the heatmap can colour the whole body without a separate "which muscles
    exist" call.
    """

    muscle: str
    recovery: float


class RecoveryResponse(BaseModel):
    """The full per-muscle Recovery snapshot plus the model parameters used.

    Surfacing ``half_life_hours`` / ``as_of`` keeps the view explainable (ADR-0002)
    and lets the client show "as of now, 48 h half-life" without hard-coding it.
    """

    as_of: datetime
    half_life_hours: float
    muscles: list[MuscleRecovery]


class MuscleVolume(BaseModel):
    """One muscle group's set count and volume-load over the trailing window.

    Split by ``role`` (primary/secondary) so the client can show "primary working
    sets" distinctly from secondary contribution.
    """

    muscle: str
    role: MuscleRole
    set_count: int
    volume_load: float


class VolumeResponse(BaseModel):
    """Per-muscle weekly volume over a trailing window of ``weeks`` weeks."""

    weeks: int
    muscles: list[MuscleVolume]


class E1rmPoint(BaseModel):
    """One estimated-1RM datapoint: the Set's time and its e1RM (kg).

    ``e1rm`` is the Effort-adjusted Epley estimate (:mod:`app.services.e1rm`) for a
    single normal Set; ``time`` is the owning Session's ``started_at``.
    """

    time: datetime
    e1rm: float


class E1rmTrendResponse(BaseModel):
    """The estimated-1RM trend for one Exercise: chronological points + best.

    ``best_e1rm`` is the peak over the window (the e1RM PR), handy for a reference
    line on the chart. Empty ``points`` ⇒ no qualifying Sets in the window.
    """

    exercise_id: uuid.UUID
    points: list[E1rmPoint]
    best_e1rm: float | None = None


class TrainedExercise(BaseModel):
    """An Exercise the user has logged normal Sets for — the e1RM-trend picker row."""

    id: uuid.UUID
    name: str
