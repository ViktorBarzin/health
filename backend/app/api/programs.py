"""Program API — generate, browse and manage goal-driven Programs (#13, ADR-0004).

Per-user endpoints over the deterministic generator (no LLM — #14) and the
catalog of presets:

* ``GET  /api/programs/presets`` — the named-preset catalog (browse).
* ``GET  /api/programs/quiz-options`` — the enum/option sets the quiz renders.
* ``POST /api/programs/generate`` — generate from quiz answers (or a preset),
  persist as the user's one active Program (archiving any prior active), return
  the full Program with its split, volume ramp and provenance receipt.
* ``GET  /api/programs`` — the user's Programs (active first).
* ``GET  /api/programs/active`` — the active Program (404 if none).
* ``GET  /api/programs/{id}`` — one Program (own only).
* ``POST /api/programs/{id}/activate`` — re-activate an archived Program.
* ``DELETE /api/programs/{id}`` — delete a Program.

Every training number on a generated Program is derived from the Principles KB by
the generator; these routes never accept a training number, only quiz answers.
Scoped to ``get_current_user``.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.principle import ExperienceLevel, TrainingGoal
from app.models.user import User
from app.schemas.program import (
    GenerateProgramRequest,
    PresetRead,
    ProgramDetail,
    ProgramSummary,
    QuizOptions,
)
from app.services.program_generation import QuizInput
from app.services.program_presets import PRESETS, preset_by_key
from app.services.program_query import (
    activate_program,
    active_program,
    create_program_from_preset,
    create_program_from_quiz,
    delete_program,
    get_program,
    list_programs,
)
from app.services.program_templates import SUPPORTED_DAYS

router = APIRouter()

# The session-length choices the quiz offers (minutes). Within the schema bounds.
_SESSION_LENGTH_OPTIONS = [30, 45, 60, 75, 90]


@router.get("/presets", response_model=list[PresetRead])
async def list_presets(
    user: User = Depends(get_current_user),
) -> list[PresetRead]:
    """The named-preset catalog — pinned parameterizations of the generator."""
    return [
        PresetRead(
            key=p.key,
            name=p.name,
            summary=p.summary,
            goal=p.goal,
            experience=p.experience,
            days_per_week=p.days_per_week,
            session_minutes=p.session_minutes,
        )
        for p in PRESETS
    ]


@router.get("/quiz-options", response_model=QuizOptions)
async def quiz_options(user: User = Depends(get_current_user)) -> QuizOptions:
    """The option sets the guided quiz renders (so the UI hardcodes nothing)."""
    return QuizOptions(
        goals=[
            {"value": g.value, "label": g.value.title()} for g in TrainingGoal
        ],
        experience_levels=[
            {"value": e.value, "label": e.value.title()} for e in ExperienceLevel
        ],
        days_per_week=list(SUPPORTED_DAYS),
        session_minutes=_SESSION_LENGTH_OPTIONS,
    )


@router.post(
    "/generate", response_model=ProgramDetail, status_code=status.HTTP_201_CREATED
)
async def generate(
    payload: GenerateProgramRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgramDetail:
    """Generate a Program from quiz answers (or a preset) and make it active.

    Every numeric parameter is derived from the Principles KB by the deterministic
    generator. Generating archives any currently-active Program (one active per
    user; prior ones are kept). Returns the full Program (split, volume ramp,
    provenance receipt).
    """
    if payload.preset_key:
        preset = preset_by_key(payload.preset_key)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unknown preset"
            )
        program = await create_program_from_preset(db, user.id, preset)
    else:
        quiz = QuizInput(
            goal=payload.goal,
            experience=payload.experience,
            days_per_week=payload.days_per_week,
            session_minutes=payload.session_minutes,
        )
        program = await create_program_from_quiz(db, user.id, quiz)
    await db.commit()
    return ProgramDetail.model_validate(program)


@router.get("", response_model=list[ProgramSummary])
async def list_user_programs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProgramSummary]:
    """The user's Programs, active first then newest-created."""
    programs = await list_programs(db, user.id)
    return [ProgramSummary.model_validate(p) for p in programs]


@router.get("/active", response_model=ProgramDetail)
async def get_active(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgramDetail:
    """The user's active Program (404 when they have none — the UI shows the quiz)."""
    program = await active_program(db, user.id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active Program"
        )
    return ProgramDetail.model_validate(program)


@router.get("/{program_id}", response_model=ProgramDetail)
async def get_one(
    program_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgramDetail:
    """One of the user's Programs by id (own only; 404 otherwise)."""
    program = await get_program(db, user.id, program_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Program not found"
        )
    return ProgramDetail.model_validate(program)


@router.post("/{program_id}/activate", response_model=ProgramDetail)
async def activate(
    program_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgramDetail:
    """Re-activate an archived Program (archiving the currently-active one)."""
    program = await activate_program(db, user.id, program_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Program not found"
        )
    await db.commit()
    return ProgramDetail.model_validate(program)


@router.delete("/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(
    program_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one of the user's Programs (cascades its days + volume rows)."""
    deleted = await delete_program(db, user.id, program_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Program not found"
        )
    await db.commit()
