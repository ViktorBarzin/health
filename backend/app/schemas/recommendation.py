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

from pydantic import BaseModel


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


class ProgramContext(BaseModel):
    """The active-Program context attached to a Program-drawn Recommendation.

    Present only when an active Program produced today's proposal (the "today"
    endpoint); ``None``/absent for the freestyle path. Lets the UI show "Week 5 of
    6 — Deload · Upper A" above the proposal.
    """

    program_id: uuid.UUID
    program_name: str
    day_name: str
    day_index: int
    week: int
    total_weeks: int
    is_deload: bool


class TodayRecommendationResponse(RecommendationResponse):
    """Today's Recommendation: the Exercises plus the source it was drawn from.

    ``source`` is ``"program"`` when the active Program produced it (then
    ``program`` carries the week/day/deload context) or ``"freestyle"`` when no
    Program is active (``program`` is ``None``).
    """

    source: str = "freestyle"
    program: ProgramContext | None = None
