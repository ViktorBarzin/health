"""PR persistence — bind the pure PR detector to the database (record of truth).

The pure :mod:`app.services.pr` decides *whether* a Set is a personal record; this
module is the only place that touches the DB for PRs. It does two things:

* :func:`prior_bests_for` — read a user's prior bests for an Exercise from their
  **normal** Set history (the non-normal exclusion is inherited from
  :mod:`app.services.volume` via the pure detector and enforced in SQL here),
  optionally excluding one Set (the candidate being evaluated);
* :func:`detect_and_persist_prs` — run detection for a just-logged Set and upsert
  the authoritative :class:`~app.models.personal_record.PersonalRecord` rows.

Why recompute prior-bests-from-history every call rather than trust an
incremental "is this bigger than the stored record?": it makes the server the
**reconciler**. Offline clients detect PRs optimistically; on sync the server
re-derives the truth from the actual Set rows, so a deleted set, an edited set,
or a lost last-write-wins race never leaves a false or duplicate PR. The upsert
is keyed on the per-slot unique index, so a Set processed twice is idempotent.

The e1RM history best is computed in Python (not SQL) because the estimate is the
Effort-adjusted Epley from :mod:`app.services.e1rm` — keeping one definition of
e1RM rather than re-encoding the formula in SQL. The candidate Set counts are
typically small (a user's sets for one exercise), so the read is cheap.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_record import PersonalRecord
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.e1rm import estimated_1rm
from app.services.pr import PRResult, PriorBests, detect_prs
from app.services.volume import counts_for_volume


async def prior_bests_for(
    db: AsyncSession,
    *,
    user_id: int,
    exercise_id: uuid.UUID,
    exclude_set_id: uuid.UUID | None = None,
) -> PriorBests:
    """Aggregate a user's prior bests for one Exercise from their normal Sets.

    Considers only ``normal`` Sets (CONTEXT.md exclusion) belonging to ``user_id``
    for ``exercise_id``, ignoring ``exclude_set_id`` (the candidate). Returns a
    clean-slate :class:`PriorBests` when there is no qualifying history.
    """
    stmt = (
        select(TrainingSet.weight_kg, TrainingSet.reps, TrainingSet.rpe)
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.exercise_id == exercise_id,
            TrainingSet.set_type == SetType.normal,
        )
    )
    if exclude_set_id is not None:
        stmt = stmt.where(TrainingSet.id != exclude_set_id)

    rows = (await db.execute(stmt)).all()

    best_weight: float | None = None
    best_e1rm: float | None = None
    best_volume: float | None = None
    reps_by_weight: dict[float, int] = {}

    for weight_kg, reps, rpe in rows:
        # Defensive: skip zero-load/zero-rep rows so they never seed a 0 best.
        if weight_kg <= 0 or reps <= 0:
            continue
        if best_weight is None or weight_kg > best_weight:
            best_weight = weight_kg
        volume = weight_kg * reps
        if best_volume is None or volume > best_volume:
            best_volume = volume
        # e1RM here uses the stored RPE converted back to RIR so the history best
        # is Effort-adjusted consistently with detection (rpe None → no adjust).
        rir = _rpe_to_rir_for_e1rm(rpe)
        e1rm = estimated_1rm(weight_kg, reps, rir=rir)
        if best_e1rm is None or e1rm > best_e1rm:
            best_e1rm = e1rm
        prior_reps = reps_by_weight.get(weight_kg)
        if prior_reps is None or reps > prior_reps:
            reps_by_weight[weight_kg] = reps

    return PriorBests(
        best_weight_kg=best_weight,
        best_e1rm=best_e1rm,
        best_volume_kg=best_volume,
        reps_by_weight=reps_by_weight,
    )


def _rpe_to_rir_for_e1rm(rpe: float | None) -> int | None:
    """Convert a stored RPE back to the RIR the e1RM adjustment expects.

    Reuses the canonical inversion in :mod:`app.services.effort` (RIR = 10 − RPE,
    clamped). ``None`` (no Effort) stays ``None`` so the estimate is unadjusted.
    """
    # Imported lazily to keep this module's import graph shallow and avoid any
    # chance of a cycle through the models package.
    from app.services.effort import rpe_to_rir

    return rpe_to_rir(rpe)


async def detect_and_persist_prs(
    db: AsyncSession, training_set: TrainingSet
) -> list[PRResult]:
    """Detect and persist the authoritative PRs a just-logged Set achieves.

    Reads the user's prior bests (excluding this Set), runs the pure detector, and
    upserts a :class:`PersonalRecord` per beaten dimension. Returns the PRs hit
    (for the API response → the live celebration). A non-qualifying Set
    (non-normal, zero load/reps, or beats nothing) persists nothing and returns
    ``[]``.

    The owning Session is loaded to resolve ``user_id``; callers already hold the
    Set so this is one extra cheap lookup.
    """
    session = (
        await db.execute(
            select(TrainingSession).where(
                TrainingSession.id == training_set.session_id
            )
        )
    ).scalar_one()
    user_id = session.user_id

    # Non-normal Sets short-circuit before any history read.
    if not counts_for_volume(training_set.set_type):
        return []

    rir = _rpe_to_rir_for_e1rm(training_set.rpe)
    prior = await prior_bests_for(
        db,
        user_id=user_id,
        exercise_id=training_set.exercise_id,
        exclude_set_id=training_set.id,
    )
    prs = detect_prs(
        weight_kg=training_set.weight_kg,
        reps=training_set.reps,
        set_type=training_set.set_type,
        rir=rir,
        prior=prior,
    )
    for pr in prs:
        await _upsert_record(
            db,
            user_id=user_id,
            exercise_id=training_set.exercise_id,
            pr=pr,
            achieved_set_id=training_set.id,
        )
    await db.flush()
    return prs


async def _upsert_record(
    db: AsyncSession,
    *,
    user_id: int,
    exercise_id: uuid.UUID,
    pr: PRResult,
    achieved_set_id: uuid.UUID,
) -> None:
    """Insert or advance the PersonalRecord for one (user, exercise, slot).

    The slot is (kind, weight_bucket) — ``weight_bucket`` is the at-weight for the
    reps-at-weight kind and NULL otherwise. A read-then-write upsert (rather than
    ``ON CONFLICT`` on the partial indexes) keeps the logic obvious and lets us
    advance ``value`` only when strictly beaten. Detection already guarantees the
    value beats the prior best, but we re-check against the stored row to stay
    correct if two sets in one batch target the same slot.
    """
    bucket = pr.at_weight_kg  # None for weight/e1rm/volume

    stmt = select(PersonalRecord).where(
        PersonalRecord.user_id == user_id,
        PersonalRecord.exercise_id == exercise_id,
        PersonalRecord.kind == pr.kind,
    )
    # NULL vs value comparison must use IS NULL, not = NULL.
    if bucket is None:
        stmt = stmt.where(PersonalRecord.weight_bucket.is_(None))
    else:
        stmt = stmt.where(PersonalRecord.weight_bucket == bucket)

    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        db.add(
            PersonalRecord(
                user_id=user_id,
                exercise_id=exercise_id,
                kind=pr.kind,
                weight_bucket=bucket,
                value=pr.value,
                achieved_set_id=achieved_set_id,
            )
        )
    elif pr.value > existing.value:
        existing.value = pr.value
        existing.achieved_set_id = achieved_set_id
