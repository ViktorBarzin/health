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

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.services.review_query import evaluate_active_program
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
    SessionFinish,
    SessionSummary,
    SetCreate,
    SetRead,
    SetReorder,
    SetUpdate,
    SetWriteResult,
    SupersetGroupRequest,
)
from app.services.effort import rir_to_rpe
from app.services.pr_service import detect_and_persist_prs, reconcile_exercise_prs
from app.services.volume import session_volume

router = APIRouter()

_review_logger = logging.getLogger("app.review")


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
    """Start (create) a Session for the caller, optionally backdated.

    The offline logger (ADR-0005, #6) may supply the Session ``id`` it minted at
    the gym. If a Session with that id already exists **for this user**, this is
    a replay of an already-applied create — return it unchanged (idempotent)
    instead of erroring on the primary key.

    A client id is matched only within the caller's own Sessions (the security
    contract). The ``id`` column is a *global* primary key, though, so an id that
    happens to exist under ANOTHER user would trip ``training_sessions_pkey`` on
    insert. v4-UUID randomness makes that astronomically unlikely, but we guard
    it: a cross-user id is a clean 409 (a non-wedging 4xx the sync engine drops),
    never a 500 (transient → the op would retry forever).
    """
    if payload.id is not None:
        owned = (
            await db.execute(
                select(TrainingSession).where(
                    TrainingSession.id == payload.id,
                    TrainingSession.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if owned is not None:
            await db.refresh(owned, attribute_names=["sets"])
            return _detail(owned)
        # Not ours — make sure it isn't someone else's before we INSERT, so a
        # global-PK clash is a clean 409 instead of an IntegrityError/500.
        clashes = (
            await db.execute(
                select(TrainingSession.id).where(TrainingSession.id == payload.id)
            )
        ).scalar_one_or_none()
        if clashes is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Session with this id already exists.",
            )

    session = TrainingSession(user_id=user.id)
    if payload.id is not None:
        session.id = payload.id
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
    payload: SessionFinish | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Mark a Session finished; idempotent if already finished.

    ``ended_at`` defaults to the server clock, but the offline logger (ADR-0005)
    may supply the moment the user tapped *finish* — which is more correct when
    the finish syncs later, and avoids the displayed end time flickering from the
    optimistic value to ``now()`` on reconcile. Honoured only on the first
    finish (idempotent: a replay leaves the already-set ``ended_at`` untouched).
    """
    session = await _get_owned_session(db, session_id, user)
    if session.ended_at is None:
        session.ended_at = (
            payload.ended_at
            if payload is not None and payload.ended_at is not None
            else func.now()
        )
    await db.flush()
    await db.refresh(session, attribute_names=["sets", "ended_at"])
    # A finished Session is the Block Review's trigger moment (ADR-0011):
    # evaluate now (gated + damped inside) so next week's targets move while
    # the workout is still fresh. Best-effort — finishing never breaks.
    try:
        await evaluate_active_program(
            db, user.id, now=datetime.now(timezone.utc)
        )
    except Exception:
        _review_logger.exception("block review evaluation failed on finish")
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

    Idempotent replay (ADR-0005, #6): when the offline logger supplies the Set
    ``id`` it minted at the gym and a Set with that id already lives in this
    Session, the queued create is being replayed after a flaky response — return
    the existing Set (with its authoritative PRs) unchanged, rather than
    inserting a duplicate or tripping the ``(session_id, order_index)`` unique
    constraint.

    ``id`` is a *global* primary key, so a supplied id that already exists in a
    DIFFERENT Session (not found by the in-Session replay check) would trip
    ``training_sets_pkey`` on insert. v4-UUID randomness makes that astronomically
    unlikely, but we guard it as a clean 409 (a non-wedging 4xx the sync engine
    drops) rather than letting it surface as a 500 (which the engine retries
    forever).
    """
    session = await _get_owned_session(db, session_id, user)

    if payload.id is not None:
        existing = next((s for s in session.sets if s.id == payload.id), None)
        if existing is not None:
            prs = await detect_and_persist_prs(db, existing)
            await db.refresh(existing, attribute_names=["exercise"])
            return _write_result(existing, prs)
        # Not in this Session — ensure the id isn't taken by another Session
        # before we INSERT, so a global-PK clash is a clean 409, not a 500.
        clashes = (
            await db.execute(
                select(TrainingSet.id).where(TrainingSet.id == payload.id)
            )
        ).scalar_one_or_none()
        if clashes is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Set with this id already exists.",
            )

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
        superset_group=payload.superset_group,
    )
    if payload.id is not None:
        new_set.id = payload.id
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
    # Superset grouping: present (even as null) rewrites it; null clears it.
    if "superset_group" in fields:
        training_set.superset_group = fields["superset_group"]

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
    """Delete a Set, reconcile its Exercise's PRs, and close the order gap.

    Deleting a Set can retract a record it held (the record-of-truth must move
    down too), so we reconcile the affected Exercise after removal. Remaining Sets
    after the deleted index then shift down by one so ``order_index`` stays
    0-based and gap-free.
    """
    training_set = await _get_owned_set(db, session_id, set_id, user)
    removed_index = training_set.order_index
    # Capture the Exercise before deletion so we can reconcile its PRs after.
    exercise_id = training_set.exercise_id
    await db.delete(training_set)
    await db.flush()

    # Retract/recompute any PR the deleted Set supported.
    await reconcile_exercise_prs(db, user_id=user.id, exercise_id=exercise_id)

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

    **Tolerant** (ADR-0005, #6): the offline logger may replay a reorder whose
    ``set_ids`` no longer exactly matches the Session — an id the server has
    since lost (a Set deleted while the reorder sat in the queue), or one it
    never had. Demanding an exact permutation (the old 400) meant the sync engine
    treated the rejection as permanent and **silently dropped the reorder**,
    losing the user's intent. So instead we reindex what we're given: take the
    valid named ids in the requested order (ignoring unknown ids and duplicates),
    then append any current Sets the list didn't name, preserving their order.
    The result is always a gap-free 0..n-1 permutation of the Session's *actual*
    Sets.

    Reindexing is two-phase — first bump every row into a high non-colliding
    range, then assign the final 0..n-1 indices — so the unique
    ``(session_id, order_index)`` constraint never trips mid-update.
    """
    session = await _get_owned_session(db, session_id, user)
    by_id = {s.id: s for s in session.sets}

    # Valid named ids, in the requested order, de-duplicated (first wins).
    seen: set[uuid.UUID] = set()
    ordered_ids: list[uuid.UUID] = []
    for sid in payload.set_ids:
        if sid in by_id and sid not in seen:
            seen.add(sid)
            ordered_ids.append(sid)
    # Append any current Sets the request didn't name, in their existing order,
    # so no Set is ever orphaned without an index (or silently dropped).
    for s in sorted(session.sets, key=lambda s: s.order_index):
        if s.id not in seen:
            ordered_ids.append(s.id)

    # Phase 1: move all rows to a non-colliding high range.
    for offset, sid in enumerate(ordered_ids):
        by_id[sid].order_index = len(ordered_ids) + offset
    await db.flush()
    # Phase 2: assign the final compact order.
    for new_index, sid in enumerate(ordered_ids):
        by_id[sid].order_index = new_index
    await db.flush()

    await db.refresh(session, attribute_names=["sets"])
    return _detail(session)


@router.post("/{session_id}/supersets", response_model=SessionDetail)
async def group_superset(
    session_id: uuid.UUID,
    payload: SupersetGroupRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Group the given Sets of a Session into one Superset (alternation group).

    All ``set_ids`` must belong to the Session and span at least two distinct
    Exercises (a Superset is two or more Exercises in alternation — CONTEXT.md).
    A fresh per-Session group id (max existing + 1) is assigned to every named
    Set, so an existing standalone or differently-grouped Set is re-tagged into
    this Superset. The display grouping/alternation is then derived client-side
    from these tags (``lib/superset.ts``).
    """
    session = await _get_owned_session(db, session_id, user)
    by_id = {s.id: s for s in session.sets}
    requested = list(payload.set_ids)

    if any(sid not in by_id for sid in requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="set_ids must all belong to this Session",
        )
    if len({by_id[sid].exercise_id for sid in requested}) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a Superset needs at least two distinct Exercises",
        )

    next_group = (
        max((s.superset_group for s in session.sets if s.superset_group is not None),
            default=-1)
        + 1
    )
    for sid in requested:
        by_id[sid].superset_group = next_group
    await db.flush()
    await db.refresh(session, attribute_names=["sets"])
    return _detail(session)


@router.delete("/{session_id}/supersets/{group}", response_model=SessionDetail)
async def ungroup_superset(
    session_id: uuid.UUID,
    group: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    """Disband a Superset: clear the group tag from every Set carrying it.

    Idempotent — clearing a group that no Set carries simply changes nothing.
    """
    session = await _get_owned_session(db, session_id, user)
    for s in session.sets:
        if s.superset_group == group:
            s.superset_group = None
    await db.flush()
    await db.refresh(session, attribute_names=["sets"])
    return _detail(session)
