"""Program persistence + query layer — binds the generator to the DB (ADR-0004).

The DB-touching glue for the Program endpoints (#13), mirroring
:mod:`app.services.recommendation_query`: the generation maths lives in the pure
core (:mod:`app.services.program_generation`); this module fetches the applicable
Principles, runs the generator, and persists the result — and reads Programs back.

Generation flow (``create_program_from_quiz``)
==============================================
1. Resolve the applicable Principles for the quiz's ``(goal, experience)`` via
   :func:`app.services.principles_query.applicable_principles` — the *only* source
   of the numbers (ADR-0004).
2. Run the pure generator → a :class:`~app.services.program_generation.GeneratedProgram`.
3. **Archive any currently-active Program** for the user (one active per user;
   prior Programs are kept, not deleted — history preserved, re-activatable).
4. Persist the new Program + its days + its ramping per-muscle weekly volume, as
   ``active``, with the generator's provenance receipt.

A preset is just a pinned :class:`~app.services.program_generation.QuizInput`
(:mod:`app.services.program_presets`), so the same flow serves both the quiz and
the catalog.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.program import (
    Program,
    ProgramDay,
    ProgramMuscleVolume,
    ProgramStatus,
)
from app.services.principles_query import applicable_principles
from app.services.program_generation import (
    GeneratedProgram,
    QuizInput,
    generate_program,
)
from app.services.program_presets import ProgramPreset


async def _generate(db: AsyncSession, quiz: QuizInput) -> GeneratedProgram:
    """Fetch the applicable Principles and run the deterministic generator.

    The Principles are scoped to the quiz's ``(goal, experience)`` — exactly the
    set the generator is allowed to compose from — so the result is fully derived
    from the cited KB.
    """
    principles = await applicable_principles(
        db, goal=quiz.goal, experience=quiz.experience
    )
    return generate_program(quiz, principles)


async def _archive_active(db: AsyncSession, user_id: int) -> None:
    """Archive the user's currently-active Program, if any (one active per user)."""
    await db.execute(
        update(Program)
        .where(Program.user_id == user_id, Program.status == ProgramStatus.active)
        .values(status=ProgramStatus.archived)
    )


def _persist(
    db: AsyncSession, user_id: int, generated: GeneratedProgram
) -> Program:
    """Map a generated Program onto ORM rows and add them to the session (active)."""
    program = Program(
        user_id=user_id,
        name=generated.name,
        preset_key=generated.preset_key,
        goal=generated.goal.value,
        experience=generated.experience.value,
        days_per_week=generated.days_per_week,
        session_minutes=generated.session_minutes,
        mesocycle_weeks=generated.mesocycle_weeks,
        total_weeks=generated.total_weeks,
        deload_week=generated.deload_week,
        rep_range_low=generated.rep_range_low,
        rep_range_high=generated.rep_range_high,
        effort_rir=generated.effort_rir,
        status=ProgramStatus.active,
        provenance=generated.provenance,
    )
    program.days = [
        ProgramDay(day_index=d.day_index, name=d.name, slots=d.slots)
        for d in generated.days
    ]
    program.muscle_volumes = [
        ProgramMuscleVolume(
            muscle=v.muscle,
            week=v.week,
            target_sets=v.target_sets,
            is_deload=v.is_deload,
        )
        for v in generated.muscle_volumes
    ]
    db.add(program)
    return program


async def create_program_from_quiz(
    db: AsyncSession, user_id: int, quiz: QuizInput
) -> Program:
    """Generate, archive any active Program, persist the new one as active.

    Returns the flushed Program with its days + volumes loaded. The number-deriving
    is entirely the generator's; this only persists. Commits are the caller's
    (the route) — we flush so the returned object has its id and relationships.
    """
    generated = await _generate(db, quiz)
    await _archive_active(db, user_id)
    program = _persist(db, user_id, generated)
    await db.flush()
    await db.refresh(program, attribute_names=["days", "muscle_volumes"])
    return program


async def create_program_from_preset(
    db: AsyncSession, user_id: int, preset: ProgramPreset
) -> Program:
    """Generate a Program from a catalog preset (a pinned set of quiz answers)."""
    quiz = QuizInput(
        goal=preset.goal,
        experience=preset.experience,
        days_per_week=preset.days_per_week,
        session_minutes=preset.session_minutes,
        style=preset.style,
        preset_key=preset.key,
        name=preset.name,
    )
    return await create_program_from_quiz(db, user_id, quiz)


async def active_program(db: AsyncSession, user_id: int) -> Program | None:
    """The user's active Program (the one driving the daily Recommendation), or None."""
    stmt = select(Program).where(
        Program.user_id == user_id, Program.status == ProgramStatus.active
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_program(
    db: AsyncSession, user_id: int, program_id: uuid.UUID
) -> Program | None:
    """One of the user's Programs by id (own only), or None."""
    stmt = select(Program).where(
        Program.id == program_id, Program.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_programs(db: AsyncSession, user_id: int) -> list[Program]:
    """The user's Programs, active first then newest-created first."""
    stmt = (
        select(Program)
        .where(Program.user_id == user_id)
        # active (a < b alphabetically: 'active' < 'archived') first, then newest.
        .order_by(Program.status.asc(), Program.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def activate_program(
    db: AsyncSession, user_id: int, program_id: uuid.UUID
) -> Program | None:
    """Make an archived Program active again (archiving the current active one).

    Returns the now-active Program, or None if it doesn't belong to the user. A
    no-op (already active) just returns it.
    """
    program = await get_program(db, user_id, program_id)
    if program is None:
        return None
    if program.status == ProgramStatus.active:
        return program
    await _archive_active(db, user_id)
    program.status = ProgramStatus.active
    await db.flush()
    await db.refresh(program, attribute_names=["days", "muscle_volumes"])
    return program


async def delete_program(
    db: AsyncSession, user_id: int, program_id: uuid.UUID
) -> bool:
    """Delete one of the user's Programs (cascades days + volumes). True if deleted."""
    program = await get_program(db, user_id, program_id)
    if program is None:
        return False
    await db.delete(program)
    await db.flush()
    return True
