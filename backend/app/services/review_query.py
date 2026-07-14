"""Block Review query/apply layer (ADR-0011) — binds the pure engine to the DB.

Assembles :class:`~app.services.block_review.ReviewInputs` from Prescriptions +
performed Sets (via the pure Adherence core), runs :func:`review`, and applies
the changes as a **versioned, receipted revision**: future accumulation weeks'
volume rows move, chronically-failed slots get a replacement pinned (picked by
the Swap ranking), and at block end the **succession** generates the follow-on
Program (same Goal; days/week may step down when the block's day-completion
says the schedule didn't fit; week 1 starts from achieved volume).

Trigger discipline (evaluate-on-read, no scheduler): callers invoke
:func:`evaluate_active_program` from the Today preview and the finish path; a
``reviewed_at`` gate plus a new-finished-Session check make that cheap and
idempotent. All damping beyond the gate lives in the pure engine.

Honesty note (documented limitation): Adherence measures **started** Sessions —
a day never started leaves no Prescription, so it can't drag a muscle's
completion down; whole-block day-completion is measured separately and feeds
the succession's days/week decision.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.exercise import ExerciseMuscle, MuscleRole
from app.models.prescription import Prescription
from app.models.program import (
    Program,
    ProgramDay,
    ProgramMuscleVolume,
    ProgramRevision,
    RevisionTrigger,
)
from app.models.training_session import TrainingSession, TrainingSet
from app.models.principle import ExperienceLevel, TrainingGoal
from app.services.program_generation import QuizInput
from app.services.adherence import (
    PerformedSet,
    PrescribedSlot,
    SessionAdherence,
    aggregate_by_muscle,
    session_adherence,
)
from app.services.block_review import (
    MuscleWeekSignal,
    ReviewChange,
    ReviewInputs,
    SlotSignal,
    review,
)
from app.services.effort import rpe_to_rir
from app.services.principles_query import principle_by_key
from app.services.program_query import active_program, create_program_from_quiz
from app.services.readiness_query import readiness_for_user
from app.services.swap_query import alternatives_for_exercise

#: Re-evaluation is gated to at most once per this interval (plus a new
#: finished Session requirement) — evaluate-on-read stays near-free.
_REVIEW_MIN_INTERVAL = dt.timedelta(hours=6)

#: Fallback weekly per-muscle band when the volume Principle is unavailable.
_FALLBACK_BOUNDS = (10, 20)

#: 7-day Readiness average at/above which a volume RAISE is allowed.
_READINESS_OK = 45.0

#: Block-level day-completion below which succession steps days/week down.
_DAY_COMPLETION_FLOOR = 0.7

#: Day counts the split templates support (mirrors program generation).
_MIN_DAYS = 3


def _week_number(created_at: dt.datetime, at: dt.datetime) -> int:
    """1-based training-week number of ``at`` relative to the Program start."""
    a, b = at, created_at
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    days = max(0.0, (a - b).total_seconds() / 86400.0)
    return int(days // 7) + 1


async def _prescribed_sessions(
    db: AsyncSession, program: Program, *, weeks: list[int]
) -> dict[int, list[tuple[Prescription, SessionAdherence]]]:
    """Finished, prescribed Sessions of this Program bucketed by training week."""
    stmt = (
        select(Prescription, TrainingSession.started_at)
        .join(TrainingSession, TrainingSession.id == Prescription.session_id)
        .where(
            Prescription.program_id == program.id,
            TrainingSession.ended_at.isnot(None),
        )
        .order_by(TrainingSession.started_at)
    )
    rows = (await db.execute(stmt)).all()
    wanted = set(weeks)
    picked: list[tuple[Prescription, dt.datetime]] = [
        (p, started)
        for p, started in rows
        if _week_number(program.created_at, started) in wanted
    ]
    if not picked:
        return {}

    set_rows = (
        (
            await db.execute(
                select(TrainingSet).where(
                    TrainingSet.session_id.in_([p.session_id for p, _ in picked])
                )
            )
        )
        .scalars()
        .all()
    )
    by_session: dict[uuid.UUID, list[PerformedSet]] = defaultdict(list)
    for s in set_rows:
        by_session[s.session_id].append(
            PerformedSet(
                exercise_id=s.exercise_id,
                weight_kg=s.weight_kg,
                reps=s.reps,
                set_type=s.set_type.value if hasattr(s.set_type, "value") else str(s.set_type),
                rir=rpe_to_rir(s.rpe),
            )
        )

    out: dict[int, list[tuple[Prescription, SessionAdherence]]] = defaultdict(list)
    for p, started in picked:
        slots = [
            PrescribedSlot(
                exercise_id=uuid.UUID(sl["exercise_id"]),
                target_sets=int(sl["target_sets"]),
                target_reps=int(sl["target_reps"]),
                target_weight_kg=float(sl["target_weight_kg"]),
                muscle=sl.get("muscle"),
            )
            for sl in (p.slots or [])
        ]
        adherence = session_adherence(slots, by_session.get(p.session_id, []))
        out[_week_number(program.created_at, started)].append((p, adherence))
    return out


async def _primary_muscle_resolver(
    db: AsyncSession, exercise_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not exercise_ids:
        return {}
    rows = (
        await db.execute(
            select(ExerciseMuscle.exercise_id, ExerciseMuscle.muscle).where(
                ExerciseMuscle.exercise_id.in_(exercise_ids),
                ExerciseMuscle.role == MuscleRole.primary,
            )
        )
    ).all()
    out: dict[uuid.UUID, str] = {}
    for r in rows:
        out.setdefault(
            r.exercise_id,
            r.muscle.value if hasattr(r.muscle, "value") else str(r.muscle),
        )
    return out


def _slot_failed(adherence: SessionAdherence, index: int) -> tuple[bool, uuid.UUID | None]:
    if index >= len(adherence.slots):
        return False, None
    slot = adherence.slots[index]
    failed = slot.hard_failures >= 1 or slot.completion <= 0.5
    return failed, slot.exercise_id


async def _bounds(db: AsyncSession, muscles: set[str]) -> dict[str, tuple[int, int]]:
    lo, hi = _FALLBACK_BOUNDS
    principle = await principle_by_key(db, "volume-dose-response")
    if principle is not None:
        param = (principle.params or {}).get("sets_per_muscle_per_week", {})
        lo = int(param.get("min", lo))
        hi = int(param.get("max", hi))
    return {m: (lo, hi) for m in muscles}


async def _build_inputs(
    db: AsyncSession, user_id: int, program: Program, *, now: dt.datetime
) -> ReviewInputs | None:
    current_week = _week_number(program.created_at, now)
    complete = [w for w in (current_week - 1, current_week - 2) if w >= 1]
    if len(complete) < 2:
        return None
    by_week = await _prescribed_sessions(db, program, weeks=complete)

    all_sessions = [a for pairs in by_week.values() for _, a in pairs]
    exercise_ids = {
        s.exercise_id for a in all_sessions for s in a.slots
    }
    resolver = await _primary_muscle_resolver(db, exercise_ids)

    weeks_signals: list[tuple[MuscleWeekSignal, ...]] = []
    for wk in complete:  # newest first: complete[0] = current_week - 1
        pairs = by_week.get(wk, [])
        muscles = aggregate_by_muscle([a for _, a in pairs], resolver=resolver)
        weeks_signals.append(
            tuple(
                MuscleWeekSignal(
                    muscle=m.muscle,
                    completion=m.completion,
                    hard_failures=m.hard_failures,
                    soft_shortfalls=m.soft_shortfalls,
                    prescribed_sets=m.prescribed_sets,
                )
                for m in sorted(muscles.values(), key=lambda x: x.muscle)
            )
        )

    # Next accumulation week's targets (nothing to tune during/after deload).
    future_weeks = sorted(
        {
            v.week
            for v in program.muscle_volumes
            if v.week > current_week and not v.is_deload
        }
    )
    next_targets: dict[str, int] = {}
    if future_weeks:
        nxt = future_weeks[0]
        next_targets = {
            v.muscle: v.target_sets
            for v in program.muscle_volumes
            if v.week == nxt
        }

    # Slot failure streaks (newest-first consecutive run on the same Exercise),
    # walked per Program day over that day's prescribed Sessions.
    day_sessions: dict[int, list[tuple[Prescription, SessionAdherence]]] = defaultdict(list)
    for pairs in by_week.values():
        for p, a in pairs:
            if p.day_index is not None:
                day_sessions[p.day_index].append((p, a))
    slot_signals: list[SlotSignal] = []
    for day in program.days:
        history = sorted(
            day_sessions.get(day.day_index, []),
            key=lambda pa: pa[1].slots[0].exercise_id.int if pa[1].slots else 0,
        )
        # Order by Session recency: prescriptions carry created_at.
        history = sorted(
            day_sessions.get(day.day_index, []),
            key=lambda pa: pa[0].created_at,
            reverse=True,
        )
        for idx, slot in enumerate(day.slots):
            streak = 0
            streak_exercise: uuid.UUID | None = None
            for _, adherence in history:
                failed, ex = _slot_failed(adherence, idx)
                if not failed:
                    break
                if streak_exercise is None:
                    streak_exercise = ex
                elif ex != streak_exercise:
                    break
                streak += 1
            if streak > 0:
                slot_signals.append(
                    SlotSignal(
                        day_index=day.day_index,
                        slot_index=idx,
                        muscle=str(slot.get("muscle", "")),
                        exercise_id=streak_exercise,
                        consecutive_failures=streak,
                    )
                )

    readiness = await readiness_for_user(db, user_id, now=now)
    readiness_ok = readiness.score is None or readiness.score >= _READINESS_OK

    # Cooldowns: anything already moved this training week (from the receipts).
    week_start = program.created_at + dt.timedelta(weeks=current_week - 1)
    revisions = (
        (
            await db.execute(
                select(ProgramRevision).where(
                    ProgramRevision.program_id == program.id,
                    ProgramRevision.created_at >= week_start,
                )
            )
        )
        .scalars()
        .all()
    )
    muscles_cooling: set[str] = set()
    slots_cooling: set[tuple[int, int]] = set()
    for rev in revisions:
        for ch in rev.changes or []:
            if ch.get("lever") == "volume" and ch.get("muscle"):
                muscles_cooling.add(ch["muscle"])
            if ch.get("lever") == "rotation":
                slots_cooling.add((ch.get("day_index"), ch.get("slot_index")))

    muscles = {s.muscle for wk in weeks_signals for s in wk} | set(next_targets)
    return ReviewInputs(
        weeks=tuple(weeks_signals),
        slots=tuple(slot_signals),
        next_week_targets=next_targets,
        bounds=await _bounds(db, muscles),
        readiness_ok=readiness_ok,
        muscles_on_cooldown=frozenset(muscles_cooling),
        slots_on_cooldown=frozenset(slots_cooling),
    )


async def _apply_changes(
    db: AsyncSession,
    program: Program,
    changes: list[ReviewChange],
    *,
    current_week: int,
) -> list[dict]:
    """Apply engine changes to the Program; return the receipt entries."""
    receipts: list[dict] = []
    for ch in changes:
        entry = {
            "lever": ch.lever,
            "muscle": ch.muscle,
            "day_index": ch.day_index,
            "slot_index": ch.slot_index,
            "from": ch.from_value,
            "to": ch.to_value,
            "reason": ch.reason,
            "principle_key": ch.principle_key,
        }
        if ch.lever == "volume" and ch.muscle is not None:
            delta = int(ch.to_value) - int(ch.from_value)  # type: ignore[arg-type]
            for row in program.muscle_volumes:
                if (
                    row.muscle == ch.muscle
                    and row.week > current_week
                    and not row.is_deload
                ):
                    row.target_sets = max(1, row.target_sets + delta)
        elif ch.lever == "rotation" and ch.day_index is not None:
            day = next(
                (d for d in program.days if d.day_index == ch.day_index), None
            )
            if day is None or ch.slot_index is None or ch.slot_index >= len(day.slots):
                continue
            slots = list(day.slots)
            slot = dict(slots[ch.slot_index])
            slot["exercise_id"] = ch.to_value
            slots[ch.slot_index] = slot
            day.slots = slots
            flag_modified(day, "slots")
        receipts.append(entry)
    return receipts


async def _record_revision(
    db: AsyncSession,
    program: Program,
    receipts: list[dict],
    *,
    trigger: RevisionTrigger,
) -> None:
    program.version = (program.version or 1) + 1
    db.add(
        ProgramRevision(
            program_id=program.id,
            version=program.version,
            trigger=trigger,
            changes=receipts,
        )
    )
    await db.flush()


async def evaluate_active_program(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> list[dict]:
    """The evaluate-on-read entry point: gate, review, apply, receipt.

    Returns the applied receipt entries (empty when nothing changed) so a
    caller can surface "what just changed".
    """
    program = await active_program(db, user_id)
    if program is None:
        return []

    current_week = _week_number(program.created_at, now)
    if current_week > program.total_weeks:
        return await _succeed_block(db, user_id, program, now=now)

    if (
        program.reviewed_at is not None
        and now - program.reviewed_at < _REVIEW_MIN_INTERVAL
    ):
        return []

    # Anything new to learn from since the last look?
    newest_finished = (
        await db.execute(
            select(TrainingSession.ended_at)
            .join(Prescription, Prescription.session_id == TrainingSession.id)
            .where(
                Prescription.program_id == program.id,
                TrainingSession.ended_at.isnot(None),
            )
            .order_by(TrainingSession.ended_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if program.reviewed_at is not None and (
        newest_finished is None or newest_finished <= program.reviewed_at
    ):
        program.reviewed_at = now
        await db.flush()
        return []

    inputs = await _build_inputs(db, user_id, program, now=now)
    program.reviewed_at = now
    if inputs is None:
        await db.flush()
        return []

    changes = review(inputs)
    resolved: list[ReviewChange] = []
    for ch in changes:
        if ch.lever != "rotation":
            resolved.append(ch)
            continue
        replacement = await _pick_replacement(db, user_id, program, ch, now=now)
        if replacement is not None:
            resolved.append(replacement)
    if not resolved:
        await db.flush()
        return []

    receipts = await _apply_changes(db, program, resolved, current_week=current_week)
    await _record_revision(
        db, program, receipts, trigger=RevisionTrigger.continuous_review
    )
    return receipts


async def _pick_replacement(
    db: AsyncSession,
    user_id: int,
    program: Program,
    change: ReviewChange,
    *,
    now: dt.datetime,
) -> ReviewChange | None:
    """Fill a rotation's replacement via the Swap ranking; drop when none fits."""
    if change.from_value is None:
        return None
    outgoing = uuid.UUID(str(change.from_value))
    blocked: set[uuid.UUID] = set()
    day = next((d for d in program.days if d.day_index == change.day_index), None)
    if day is not None:
        for sl in day.slots:
            pin = sl.get("exercise_id")
            if pin:
                blocked.add(uuid.UUID(pin))
    alternatives = await alternatives_for_exercise(
        db, user_id, outgoing, now=now, blocked_ids=frozenset(blocked), limit=1
    )
    if not alternatives:
        return None
    incoming = alternatives[0]
    return ReviewChange(
        lever=change.lever,
        muscle=change.muscle,
        day_index=change.day_index,
        slot_index=change.slot_index,
        from_value=change.from_value,
        to_value=str(incoming.exercise_id),
        reason=f"{change.reason} — replacing with {incoming.name}",
        principle_key=change.principle_key,
    )


async def _succeed_block(
    db: AsyncSession, user_id: int, program: Program, *, now: dt.datetime
) -> list[dict]:
    """Block over → generate the follow-on Program (the structural review).

    Same Goal/experience/session length. Days/week steps down one (never below
    the template minimum) when the block's day-completion says the schedule
    didn't fit; week 1's per-muscle volume starts from what was actually
    performed in the last complete accumulation week (clamped into the band) so
    the new block starts where the user IS, not where the old plan hoped.
    """
    # Day completion over the whole block: finished prescribed Sessions vs plan.
    finished = (
        await db.execute(
            select(Prescription.id)
            .join(TrainingSession, TrainingSession.id == Prescription.session_id)
            .where(
                Prescription.program_id == program.id,
                TrainingSession.ended_at.isnot(None),
            )
        )
    ).all()
    expected = program.days_per_week * max(1, program.mesocycle_weeks)
    day_completion = len(finished) / expected if expected else 1.0

    days = program.days_per_week
    changes: list[dict] = []
    if day_completion < _DAY_COMPLETION_FLOOR and days > _MIN_DAYS:
        days -= 1
        changes.append(
            {
                "lever": "days_per_week",
                "from": program.days_per_week,
                "to": days,
                "reason": (
                    f"completed {round(day_completion * 100)}% of planned "
                    "sessions this block — stepping the schedule down to fit "
                    "real availability"
                ),
                "principle_key": "training-frequency",
            }
        )

    goal = program.goal if isinstance(program.goal, TrainingGoal) else TrainingGoal(program.goal)
    experience = (
        program.experience
        if isinstance(program.experience, ExperienceLevel)
        else ExperienceLevel(program.experience)
    )
    quiz = QuizInput(
        goal=goal,
        experience=experience,
        days_per_week=days,
        session_minutes=program.session_minutes,
        name=program.name,
        preset_key=program.preset_key,
    )
    successor = await create_program_from_quiz(db, user_id, quiz)
    successor.parent_program_id = program.id

    # Start where the user actually is: last complete accumulation week's
    # performed sets per muscle, clamped into the band and never above the
    # generated week-2 target (ramps stay monotonic).
    last_acc_week = max(1, program.total_weeks - 1)
    by_week = await _prescribed_sessions(db, program, weeks=[last_acc_week])
    pairs = by_week.get(last_acc_week, [])
    if pairs:
        resolver = await _primary_muscle_resolver(
            db,
            {s.exercise_id for _, a in pairs for s in a.slots},
        )
        achieved = aggregate_by_muscle([a for _, a in pairs], resolver=resolver)
        bounds = await _bounds(db, set(achieved))
        week2 = {
            v.muscle: v.target_sets
            for v in successor.muscle_volumes
            if v.week == 2 and not v.is_deload
        }
        for row in successor.muscle_volumes:
            if row.week != 1 or row.is_deload:
                continue
            got = achieved.get(row.muscle)
            if got is None:
                continue
            lo, hi = bounds.get(row.muscle, _FALLBACK_BOUNDS)
            new_start = max(lo, min(hi, got.performed_sets))
            cap = week2.get(row.muscle)
            if cap is not None:
                new_start = min(new_start, cap)
            if new_start != row.target_sets:
                changes.append(
                    {
                        "lever": "volume_start",
                        "muscle": row.muscle,
                        "from": row.target_sets,
                        "to": new_start,
                        "reason": (
                            f"{row.muscle}: last block ended at "
                            f"{got.performed_sets} performed sets/week — the "
                            "new block starts there"
                        ),
                        "principle_key": "volume-dose-response",
                    }
                )
                row.target_sets = new_start

    successor.reviewed_at = now
    receipts = [
        {
            "lever": "block_succession",
            "from": str(program.id),
            "to": str(successor.id),
            "reason": "block complete — generated the follow-on Program",
            "principle_key": None,
        }
    ] + changes
    await _record_revision(
        db, successor, receipts, trigger=RevisionTrigger.block_review
    )
    return receipts


async def adherence_weeks(
    db: AsyncSession, user_id: int, *, now: dt.datetime, weeks: int = 4
) -> list[dict]:
    """Per-week, per-muscle Adherence for the active Program (newest first).

    The strip/receipts surface: what was prescribed vs performed each training
    week (the current, partial week included and flagged). Read-only.
    """
    program = await active_program(db, user_id)
    if program is None:
        return []
    current_week = _week_number(program.created_at, now)
    wanted = [w for w in range(current_week - weeks + 1, current_week + 1) if w >= 1]
    by_week = await _prescribed_sessions(db, program, weeks=wanted)
    all_sessions = [a for pairs in by_week.values() for _, a in pairs]
    resolver = await _primary_muscle_resolver(
        db, {s.exercise_id for a in all_sessions for s in a.slots}
    )
    out: list[dict] = []
    for wk in sorted(wanted, reverse=True):
        pairs = by_week.get(wk, [])
        muscles = aggregate_by_muscle([a for _, a in pairs], resolver=resolver)
        out.append(
            {
                "week": wk,
                "current": wk == current_week,
                "sessions": len(pairs),
                "muscles": [
                    {
                        "muscle": m.muscle,
                        "prescribed_sets": m.prescribed_sets,
                        "performed_sets": m.performed_sets,
                        "completion": round(m.completion, 3),
                        "hard_failures": m.hard_failures,
                    }
                    for m in sorted(muscles.values(), key=lambda x: x.muscle)
                ],
            }
        )
    return out
