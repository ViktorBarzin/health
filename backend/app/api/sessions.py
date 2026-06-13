"""Session/Set logging API — the live gym-logging core (online).

A **Session** is a gym workout the user logs live: a per-user, ordered list of
**Sets**, each referencing exactly one **Exercise** from the shared library.
Everything here is scoped to ``get_current_user`` — a user only ever sees or
mutates their own Sessions and Sets (a Set is reached only via its parent
Session, so the Session ownership check guards the Sets too).

Effort travels the wire as RIR (the one-tap chip 0–4) and is stored as its
RPE-equivalent; ``set_type`` defaults to ``normal``. Set order is an explicit,
gap-free 0-based ``order_index`` maintained here.

Out of scope for this slice: offline sync (#6), rest timer / supersets / plate
calc (#7), PR detection (#8).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.exercise import Exercise
from app.models.personal_record import PersonalRecord
from app.models.training_session import TrainingSession, TrainingSet
from app.models.user import User
from app.schemas.sessions import (
    PersonalRecordRead,
    PRReadout,
    SessionCreate,
    SessionDetail,
    SessionSummary,
    SetCreate,
    SetRead,
    SetReorder,
    SetUpdate,
    SetWriteResult,
)
from app.services.effort import rir_to_rpe
from app.services.pr_service import detect_and_persist_prs
from app.services.volume import session_volume

router = APIRouter()


async def _get_owned_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> TrainingSession:
    """Load a Session owned by ``user``, or raise 404.

    The 404 (not 403) for someone else's Session is deliberate: it does not leak
    that the id exists. Sets (``selectin`` on the relationship) come along loaded
    and ordered by ``order_index``.
    """
    stmt = select(TrainingSession).where(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user.id,
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return session


async def _assert_exercise_visible(
    db: AsyncSession, exercise_id: uuid.UUID, user: User
) -> None:
    """Ensure the Exercise exists and is visible to the user (global or own).

    Mirrors the Exercise library visibility rule so a Set can't reference another
    user's private custom Exercise.
    """
    stmt = select(Exercise.id).where(
        Exercise.id == exercise_id,
        (Exercise.user_id.is_(None)) | (Exercise.user_id == user.id),
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found"
        )


def _summary(session: TrainingSession) -> SessionSummary:
    """Build a list-view summary, computing set count + counted volume."""
    return SessionSummary(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        set_count=len(session.sets),
        total_volume_kg=session_volume(session.sets),
    )


def _detail(session: TrainingSession) -> SessionDetail:
    """Build a detail view: summary fields plus the ordered Sets."""
    return SessionDetail(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        set_count=len(session.sets),
        total_volume_kg=session_volume(session.sets),
        sets=[SetRead.model_validate(s) for s in session.sets],
    )


@router.post("/", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
async def start_session(
    payload: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Start (create) a Session for the caller, optionally backdated."""
    session = TrainingSession(user_id=user.id)
    if payload.started_at is not None:
        session.started_at = payload.started_at
    db.add(session)
    await db.flush()
    await db.refresh(session, attribute_names=["sets"])
    return _detail(session)


@router.get("/", response_model=list[SessionSummary])
async def list_sessions(
    active: bool | None = Query(
        default=None, description="Filter to active (true) or finished (false)."
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionSummary]:
    """List the caller's Sessions, newest first; optionally only active ones."""
    stmt = select(TrainingSession).where(TrainingSession.user_id == user.id)
    if active is True:
        stmt = stmt.where(TrainingSession.ended_at.is_(None))
    elif active is False:
        stmt = stmt.where(TrainingSession.ended_at.isnot(None))
    stmt = (
        stmt.order_by(TrainingSession.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sessions = (await db.execute(stmt)).scalars().all()
    return [_summary(s) for s in sessions]


@router.get("/prs", response_model=list[PersonalRecordRead])
async def list_personal_records(
    exercise_id: uuid.UUID = Query(
        description="Return the caller's PRs for this Exercise."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PersonalRecordRead]:
    """List the caller's authoritative PRs for one Exercise.

    The queryable record-of-truth (one row per dimension, plus one per weight for
    the reps-at-weight kind). Static ``/prs`` is declared before ``/{session_id}``
    so it is not captured by the UUID path param.
    """
    rows = (
        await db.execute(
            select(PersonalRecord)
            .where(
                PersonalRecord.user_id == user.id,
                PersonalRecord.exercise_id == exercise_id,
            )
            .order_by(PersonalRecord.kind, PersonalRecord.weight_bucket)
        )
    ).scalars().all()
    return [PersonalRecordRead.model_validate(r) for r in rows]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Fetch one of the caller's Sessions with its Sets in order."""
    session = await _get_owned_session(db, session_id, user)
    return _detail(session)


@router.post("/{session_id}/finish", response_model=SessionDetail)
async def finish_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Mark a Session finished (sets ``ended_at`` to now); idempotent if already."""
    session = await _get_owned_session(db, session_id, user)
    if session.ended_at is None:
        session.ended_at = func.now()
    await db.flush()
    await db.refresh(session, attribute_names=["sets", "ended_at"])
    return _detail(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one of the caller's Sessions (its Sets cascade)."""
    session = await _get_owned_session(db, session_id, user)
    await db.delete(session)
    await db.flush()


def _write_result(training_set: TrainingSet, prs: list) -> SetWriteResult:
    """Build the add/edit response: the Set plus any PRs the write achieved."""
    result = SetWriteResult.model_validate(training_set)
    result.prs = [
        PRReadout(kind=p.kind, value=p.value, at_weight_kg=p.at_weight_kg)
        for p in prs
    ]
    return result


@router.post(
    "/{session_id}/sets",
    response_model=SetWriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def add_set(
    session_id: uuid.UUID,
    payload: SetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SetWriteResult:
    """Append a Set to one of the caller's Sessions, detecting any PRs.

    The new Set takes the next ``order_index`` (current max + 1, or 0 for the
    first). Effort RIR is stored as its RPE-equivalent. After the Set lands, the
    server runs authoritative PR detection (:mod:`app.services.pr_service`) and
    returns any records beaten in ``prs`` so the UI can celebrate; the offline
    client celebrates immediately from its own mirror of the same algorithm and
    this reconciles it.
    """
    session = await _get_owned_session(db, session_id, user)
    await _assert_exercise_visible(db, payload.exercise_id, user)

    next_index = (
        max((s.order_index for s in session.sets), default=-1) + 1
    )
    new_set = TrainingSet(
        session_id=session.id,
        exercise_id=payload.exercise_id,
        order_index=next_index,
        weight_kg=payload.weight_kg,
        reps=payload.reps,
        rpe=rir_to_rpe(payload.effort_rir),
        set_type=payload.set_type,
    )
    db.add(new_set)
    await db.flush()
    prs = await detect_and_persist_prs(db, new_set)
    await db.refresh(new_set, attribute_names=["exercise"])
    return _write_result(new_set, prs)


async def _get_owned_set(
    db: AsyncSession, session_id: uuid.UUID, set_id: uuid.UUID, user: User
) -> TrainingSet:
    """Load a Set that belongs to one of the caller's Sessions, or 404."""
    stmt = (
        select(TrainingSet)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSet.id == set_id,
            TrainingSet.session_id == session_id,
            TrainingSession.user_id == user.id,
        )
    )
    training_set = (await db.execute(stmt)).scalar_one_or_none()
    if training_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Set not found"
        )
    return training_set


@router.patch("/{session_id}/sets/{set_id}", response_model=SetWriteResult)
async def update_set(
    session_id: uuid.UUID,
    set_id: uuid.UUID,
    payload: SetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SetWriteResult:
    """Edit a Set's weight, reps, Effort, and/or set type, re-detecting PRs.

    Only fields present in the request body change. ``effort_rir`` is treated
    explicitly: sending it (even ``null``) rewrites the stored RPE; omitting it
    leaves Effort untouched. Because an edit can turn a Set into a PR (e.g.
    correcting a weight upward, or flipping a warmup to normal), the same
    authoritative detection runs after the edit and any records are returned in
    ``prs``.
    """
    training_set = await _get_owned_set(db, session_id, set_id, user)
    fields = payload.model_dump(exclude_unset=True)

    if "weight_kg" in fields:
        training_set.weight_kg = fields["weight_kg"]
    if "reps" in fields:
        training_set.reps = fields["reps"]
    if "set_type" in fields and fields["set_type"] is not None:
        training_set.set_type = fields["set_type"]
    if "effort_rir" in fields:
        training_set.rpe = rir_to_rpe(fields["effort_rir"])

    await db.flush()
    prs = await detect_and_persist_prs(db, training_set)
    await db.refresh(training_set, attribute_names=["exercise"])
    return _write_result(training_set, prs)


@router.delete(
    "/{session_id}/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_set(
    session_id: uuid.UUID,
    set_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a Set and close the gap it leaves in the Session's order.

    Remaining Sets after the deleted index shift down by one so ``order_index``
    stays 0-based and gap-free.
    """
    training_set = await _get_owned_set(db, session_id, set_id, user)
    removed_index = training_set.order_index
    await db.delete(training_set)
    await db.flush()

    # Compact: every later Set moves down one slot. Done in id order to avoid a
    # transient duplicate on the (session_id, order_index) unique constraint.
    later = (
        await db.execute(
            select(TrainingSet)
            .where(
                TrainingSet.session_id == session_id,
                TrainingSet.order_index > removed_index,
            )
            .order_by(TrainingSet.order_index)
        )
    ).scalars().all()
    for s in later:
        s.order_index -= 1
    await db.flush()


@router.put("/{session_id}/sets/order", response_model=SessionDetail)
async def reorder_sets(
    session_id: uuid.UUID,
    payload: SetReorder,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Reorder a Session's Sets to match the given list of Set ids.

    The body must list exactly the Session's current Set ids (a permutation);
    anything else is a 400. Reindexing is two-phase — first bump every row out of
    the way (into a high range), then assign the final 0..n-1 indices — so the
    unique ``(session_id, order_index)`` constraint never trips mid-update.
    """
    session = await _get_owned_session(db, session_id, user)
    current_ids = {s.id for s in session.sets}
    requested_ids = list(payload.set_ids)

    if set(requested_ids) != current_ids or len(requested_ids) != len(current_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="set_ids must list exactly the Session's current Sets",
        )

    by_id = {s.id: s for s in session.sets}
    # Phase 1: move all rows to a non-colliding high range.
    for offset, sid in enumerate(requested_ids):
        by_id[sid].order_index = len(requested_ids) + offset
    await db.flush()
    # Phase 2: assign the final compact order.
    for new_index, sid in enumerate(requested_ids):
        by_id[sid].order_index = new_index
    await db.flush()

    await db.refresh(session, attribute_names=["sets"])
    return _detail(session)
