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
