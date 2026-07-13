"""Pydantic schemas for the freestyle Recommendation endpoints (#11).

A **Recommendation** is a generated Session proposal — Exercises with target
sets × reps × weight (CONTEXT.md). The preview (``GET``) returns the proposal so
the user can review it; **starting** it (``POST``) instantiates a real Session
pre-filled with those target Sets, returned as the existing
:class:`~app.schemas.sessions.SessionDetail` so the logging UI takes over
unchanged.

The targets are echoed back per Exercise (sets/reps/weight + the worked muscles)
so the proposal is explainable — the deterministic core (ADR-0002) shows its
reasoning rather than handing back an opaque list.
"""

import uuid

from pydantic import BaseModel, Field


class RecommendedExerciseRead(BaseModel):
    """One prescribed Exercise in a proposal: target sets × reps × weight.

    ``is_starting_point`` flags a first-guess weight (the Exercise had no usable
    history, so the weight is a starting point the user sets). ``primary_muscles``
    / ``secondary_muscles`` are the muscles it works, for the "why this Exercise"
    explainer.
    """

    exercise_id: uuid.UUID
    name: str
    target_sets: int
    target_reps: int
    target_weight_kg: float
    is_starting_point: bool
    primary_muscles: list[str]
    secondary_muscles: list[str]


class RecommendationResponse(BaseModel):
    """Today's freestyle workout proposal — the ordered Exercises to perform.

    Empty ``exercises`` means the engine had nothing to propose (no trained
    Exercises whose equipment the user has) — the UI guides the user to log a
    Session first.
    """

    exercises: list[RecommendedExerciseRead] = []


class StartRecommendationRequest(BaseModel):
    """Start a freestyle Recommendation, instantiating its Session.

    The engine regenerates the proposal server-side (deterministic, so it matches
    the preview the user reviewed) and pre-fills a Session with its target Sets.
    No body fields are required; ``exercise_count`` / ``sets_per_exercise`` let a
    caller tune the proposal size.
    """

    exercise_count: int | None = None
    sets_per_exercise: int | None = None

    model_config = {"extra": "forbid"}


class AutoregulationRead(BaseModel):
    """The autoregulation applied to today's Program day (#14, ADR-0004).

    Surfaces *why* the day looks the way it does: ``adjusted`` is true when the
    engine trimmed (or raised) volume on Readiness / Recovery; ``reason`` is the
    plain-English explanation ("Readiness 48/100 — trimmed top sets to protect
    recovery (chest)"); ``readiness`` echoes the score used (null when no
    biometric signal); ``early_deload`` is true when sustained low signals tripped
    a fatigue deload earlier than the calendar one; ``trimmed_muscles`` lists the
    muscles whose volume was cut.
    """

    adjusted: bool = False
    reason: str = ""
    readiness: float | None = None
    early_deload: bool = False
    trimmed_muscles: list[str] = []


class ProgramContext(BaseModel):
    """The active-Program context attached to a Program-drawn Recommendation.

    Present only when an active Program produced today's proposal (the "today"
    endpoint); ``None``/absent for the freestyle path. Lets the UI show "Week 5 of
    6 — Deload · Upper A" above the proposal, plus the autoregulation reason.
    """

    program_id: uuid.UUID
    program_name: str
    day_name: str
    day_index: int
    week: int
    total_weeks: int
    is_deload: bool
    autoregulation: AutoregulationRead | None = None


class TodayRecommendationResponse(RecommendationResponse):
    """Today's Recommendation: the Exercises plus the source it was drawn from.

    ``source`` is ``"program"`` when the active Program produced it (then
    ``program`` carries the week/day/deload context) or ``"freestyle"`` when no
    Program is active (``program`` is ``None``).
    """

    source: str = "freestyle"
    program: ProgramContext | None = None


class ExplicitExercise(BaseModel):
    """One slot of an explicit (WYSIWYG) start — what the client displayed."""

    exercise_id: uuid.UUID
    target_sets: int = Field(ge=1, le=10)
    target_reps: int = Field(ge=1, le=100)
    target_weight_kg: float = Field(ge=0, le=2000)

    model_config = {"extra": "forbid"}


class ExplicitStartRequest(BaseModel):
    """Start exactly the proposal the client shows (post-Swap, post-shaping).

    The preview endpoints regenerate deterministically, but the moment the user
    Swaps a slot client-side the displayed proposal diverges from what a
    regenerate would produce — so Start sends the displayed slots verbatim and
    the server instantiates them (visibility-checked; same bounds as the tunable
    preview). Equivalent authority to logging the Sets by hand — the engine's
    receipts belong to the preview, not this instantiation.
    """

    exercises: list[ExplicitExercise] = Field(min_length=1, max_length=12)

    model_config = {"extra": "forbid"}


class AdjustRequest(BaseModel):
    """A conversational adjust request — free-text the provider maps to levers.

    E.g. "make it shorter", "no barbell today", "I'm tired". The provider
    (deterministic by default, the gated LLM otherwise) only *proposes*; the
    engine validates the proposal against Principle bounds before applying it.
    """

    request: str = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


class AdjustResponse(TodayRecommendationResponse):
    """The re-shaped proposal plus what the adjust did.

    Extends the today shape (so the UI renders it identically) with ``note`` (the
    human explanation of the change) and ``applied`` (the validated levers — for
    transparency / debugging). The proposal is editable: starting it instantiates
    Sets the user overwrites, so their edits still win (ADR-0002).
    """

    note: str = ""
    applied: dict = {}


class ShapeRequest(BaseModel):
    """One-tap duration shaping: fit today's proposal into this many minutes."""

    minutes: int = Field(ge=10, le=240)

    model_config = {"extra": "forbid"}
