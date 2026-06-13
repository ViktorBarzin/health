"""Freestyle Recommendation API — "generate me a workout" (#11).

Two per-user, deterministic endpoints over the engine cores (ADR-0002 — no LLM
here; the LLM adjust layer is #14):

* ``GET  /api/recommendations/freestyle`` — preview today's proposal (Exercises
  with target sets × reps × weight) so the user can review it before committing;
* ``POST /api/recommendations/freestyle/start`` — instantiate a real Session
  pre-filled with the proposal's target Sets, returned as the standard
  :class:`~app.schemas.sessions.SessionDetail` so the existing logging UI drives
  it. The user logs against it and any edits overwrite the targets (user edits
  always win — there is no separate prescribed state).

Both regenerate from the same deterministic core, so the started Session matches
the previewed proposal for unchanged data. Scoped to ``get_current_user``.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import _detail
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.recommendation import (
    ProgramContext,
    RecommendationResponse,
    RecommendedExerciseRead,
    StartRecommendationRequest,
    TodayRecommendationResponse,
)
from app.schemas.sessions import SessionDetail
from app.services.program_recommendation import ProgramRecommendation
from app.services.recommendation import (
    DEFAULT_EXERCISE_COUNT,
    DEFAULT_SETS_PER_EXERCISE,
)
from app.services.recommendation_query import (
    instantiate_session,
    recommend_for_user,
    recommend_today,
)

router = APIRouter()

# Bounds on the tunable proposal size — a sane gym session, not an all-day plan.
_MAX_EXERCISES = 12
_MAX_SETS = 10


def _to_response(recommendation) -> RecommendationResponse:
    """Map the pure-core proposal to the wire response."""
    return RecommendationResponse(
        exercises=[
            RecommendedExerciseRead(
                exercise_id=item.exercise_id,
                name=item.name,
                target_sets=item.target_sets,
                target_reps=item.target_reps,
                target_weight_kg=item.target_weight_kg,
                is_starting_point=item.is_starting_point,
                primary_muscles=list(item.primary_muscles),
                secondary_muscles=list(item.secondary_muscles),
            )
            for item in recommendation.exercises
        ]
    )


@router.get("/freestyle", response_model=RecommendationResponse)
async def preview_freestyle(
    exercise_count: int = Query(
        default=DEFAULT_EXERCISE_COUNT, ge=1, le=_MAX_EXERCISES
    ),
    sets_per_exercise: int = Query(
        default=DEFAULT_SETS_PER_EXERCISE, ge=1, le=_MAX_SETS
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendationResponse:
    """Preview today's freestyle proposal: Exercises × target sets/reps/weight.

    Generated deterministically from the caller's training history, Recovery, and
    Gym Profile equipment. Empty when the user has no trained Exercises the
    engine can equip.
    """
    now = datetime.now(timezone.utc)
    recommendation = await recommend_for_user(
        db,
        user.id,
        now=now,
        exercise_count=exercise_count,
        sets_per_exercise=sets_per_exercise,
    )
    return _to_response(recommendation)


@router.post(
    "/freestyle/start",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def start_freestyle(
    payload: StartRecommendationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Start a freestyle Recommendation: instantiate its Session with target Sets.

    Regenerates the proposal (deterministic — matches the preview) and creates a
    Session pre-filled with its target Sets, returned as the standard
    ``SessionDetail`` so the user logs against it in the existing UI. Their edits
    overwrite the prescribed values.
    """
    now = datetime.now(timezone.utc)
    count = payload.exercise_count or DEFAULT_EXERCISE_COUNT
    sets = payload.sets_per_exercise or DEFAULT_SETS_PER_EXERCISE
    count = max(1, min(count, _MAX_EXERCISES))
    sets = max(1, min(sets, _MAX_SETS))

    recommendation = await recommend_for_user(
        db, user.id, now=now, exercise_count=count, sets_per_exercise=sets
    )
    session = await instantiate_session(db, user.id, recommendation)
    return _detail(session)


def _program_context(program_rec: ProgramRecommendation) -> ProgramContext:
    """Map the Program-recommendation context to its wire shape."""
    return ProgramContext(
        program_id=program_rec.program_id,
        program_name=program_rec.program_name,
        day_name=program_rec.day_name,
        day_index=program_rec.day_index,
        week=program_rec.week,
        total_weeks=program_rec.total_weeks,
        is_deload=program_rec.is_deload,
    )


@router.get("/today", response_model=TodayRecommendationResponse)
async def preview_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TodayRecommendationResponse:
    """Preview today's Recommendation: from the active Program, else freestyle.

    When the user has an active Program, this is the Program's prescription for the
    next due training day (with the week/day/deload context); otherwise it falls
    back to the deterministic freestyle generator. The unified daily entry point.
    """
    now = datetime.now(timezone.utc)
    recommendation, program_rec = await recommend_today(db, user.id, now=now)
    base = _to_response(recommendation)
    if program_rec is not None:
        return TodayRecommendationResponse(
            exercises=base.exercises,
            source="program",
            program=_program_context(program_rec),
        )
    return TodayRecommendationResponse(exercises=base.exercises, source="freestyle")


@router.post(
    "/today/start",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def start_today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Start today's Recommendation (Program-drawn or freestyle): instantiate a Session.

    Regenerates deterministically server-side (matching the preview) and creates a
    Session pre-filled with the target Sets, returned as the standard
    ``SessionDetail`` so the existing logging UI drives it — exactly the #11
    instantiate path, whether the source was the Program or freestyle.
    """
    now = datetime.now(timezone.utc)
    recommendation, _ = await recommend_today(db, user.id, now=now)
    session = await instantiate_session(db, user.id, recommendation)
    return _detail(session)
