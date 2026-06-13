"""PR persistence — bind the pure PR detector to the database (record of truth).

The pure :mod:`app.services.pr` decides *whether* a Set is a personal record; this
module is the only place that touches the DB for PRs, and it is a **true
reconciler**, not a forward-only writer:

* :func:`prior_bests_for` — read a user's prior bests for an Exercise from their
  **normal** Set history, optionally excluding one Set (used to feed the pure
  detector for the live-celebration "is this a PR?" question);
* :func:`reconcile_exercise_prs` — recompute every PR slot for one Exercise as
  the MAX over the user's *current* normal-Set history and sync the
  :class:`~app.models.personal_record.PersonalRecord` rows to match exactly:
  insert new slots, move existing ones up **or down**, and **delete** any slot no
  longer supported by a normal Set. This is what makes the table authoritative;
* :func:`detect_and_persist_prs` — for a just-written Set, reconcile the Exercise
  and return only the dimensions this Set newly set or improved (for the banner).

Why a full recompute-and-sync rather than an incremental advance: detection is
forward-only by nature (a Set can only *beat* a prior best), but the persisted
truth must move in both directions. Editing the record-holding Set down, flipping
the only supporting Set to a non-normal type, or deleting it must all *retract*
the records they supported — otherwise downstream analytics/progression read a
stale, never-decreasing record and the training signal is wrong. Recomputing from
the actual Set rows also makes the table self-heal after offline last-write-wins
races. Callers wire :func:`reconcile_exercise_prs` into add/edit/delete.

The e1RM history best is computed in Python (not SQL) because the estimate is the
Effort-adjusted Epley from :mod:`app.services.e1rm` — keeping one definition of
e1RM. A user's Sets for one Exercise are few, so the read+recompute is cheap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_record import PersonalRecord
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.services.e1rm import estimated_1rm
from app.services.pr import PRKind, PRResult, PriorBests
from app.services.volume import counts_for_volume


# A slot key uniquely identifies one PR row: (kind, weight_bucket). weight_bucket
# is None for the weight-independent kinds and the load for reps_at_weight.
_Slot = tuple[PRKind, float | None]


@dataclass
class _SlotBest:
    """The authoritative best for one slot: its value and the Set that holds it."""

    value: float
    achieved_set_id: uuid.UUID


def _rpe_to_rir_for_e1rm(rpe: float | None) -> int | None:
    """Convert a stored RPE back to the RIR the e1RM adjustment expects.

    Reuses the canonical inversion in :mod:`app.services.effort` (RIR = 10 − RPE,
    clamped). ``None`` (no Effort) stays ``None`` so the estimate is unadjusted.
    """
    # Imported lazily to keep this module's import graph shallow.
    from app.services.effort import rpe_to_rir

    return rpe_to_rir(rpe)


async def _normal_sets_for(
    db: AsyncSession,
    *,
    user_id: int,
    exercise_id: uuid.UUID,
) -> list[tuple[uuid.UUID, float, int, float | None]]:
    """Fetch ``(id, weight_kg, reps, rpe)`` for a user's PR-eligible Sets of an Exercise.

    PR-eligible = a ``normal`` Set (the CONTEXT.md exclusion — the SQL filters on
    the typed dimension that :func:`app.services.volume.counts_for_volume` defines
    as counting) with positive load and reps (the zero-noise guard the pure
    detector applies). Non-normal / zero-load / zero-rep Sets never seed a record.
    """
    # The set_type filter is the SQL expression of counts_for_volume's rule; the
    # assert documents that coupling so the two can't silently diverge.
    assert counts_for_volume(SetType.normal)
    stmt = (
        select(
            TrainingSet.id,
            TrainingSet.weight_kg,
            TrainingSet.reps,
            TrainingSet.rpe,
        )
        .join(TrainingSession, TrainingSet.session_id == TrainingSession.id)
        .where(
            TrainingSession.user_id == user_id,
            TrainingSet.exercise_id == exercise_id,
            TrainingSet.set_type == SetType.normal,
        )
    )
    rows = (await db.execute(stmt)).all()
    return [(sid, w, r, rpe) for (sid, w, r, rpe) in rows if w > 0 and r > 0]


async def prior_bests_for(
    db: AsyncSession,
    *,
    user_id: int,
    exercise_id: uuid.UUID,
    exclude_set_id: uuid.UUID | None = None,
) -> PriorBests:
    """Aggregate a user's prior bests for one Exercise from their normal Sets.

    Considers only ``normal`` Sets belonging to ``user_id`` for ``exercise_id``,
    ignoring ``exclude_set_id``. Returns a clean-slate :class:`PriorBests` when
    there is no qualifying history. Feeds the pure detector for the live "is this
    Set a PR?" question (it is *not* how the table is persisted — see
    :func:`reconcile_exercise_prs`).
    """
    rows = await _normal_sets_for(db, user_id=user_id, exercise_id=exercise_id)

    best_weight: float | None = None
    best_e1rm: float | None = None
    best_volume: float | None = None
    reps_by_weight: dict[float, int] = {}

    for sid, weight_kg, reps, rpe in rows:
        if exclude_set_id is not None and sid == exclude_set_id:
            continue
        if weight_kg > (best_weight or -1.0):
            best_weight = weight_kg
        volume = weight_kg * reps
        if volume > (best_volume or -1.0):
            best_volume = volume
        e1rm = estimated_1rm(weight_kg, reps, rir=_rpe_to_rir_for_e1rm(rpe))
        if e1rm > (best_e1rm or -1.0):
            best_e1rm = e1rm
        if reps > reps_by_weight.get(weight_kg, -1):
            reps_by_weight[weight_kg] = reps

    return PriorBests(
        best_weight_kg=best_weight,
        best_e1rm=best_e1rm,
        best_volume_kg=best_volume,
        reps_by_weight=reps_by_weight,
    )


def _authoritative_slots(
    rows: list[tuple[uuid.UUID, float, int, float | None]],
) -> dict[_Slot, _SlotBest]:
    """Compute the authoritative PR slots (value + holder) from normal Sets.

    The MAX over the supplied normal Sets for each dimension: one ``weight`` /
    ``e1rm`` / ``volume`` slot (``weight_bucket`` None) and one ``reps_at_weight``
    slot per distinct load. Each slot records which Set holds it (first Set to
    reach the max wins ties deterministically by iteration order). An empty input
    yields no slots — i.e. every record retracts.
    """
    slots: dict[_Slot, _SlotBest] = {}

    def consider(slot: _Slot, value: float, set_id: uuid.UUID) -> None:
        cur = slots.get(slot)
        # Strictly-greater keeps the earliest holder on a tie (stable, and avoids
        # needless achieved_set_id churn when equal Sets exist).
        if cur is None or value > cur.value:
            slots[slot] = _SlotBest(value=value, achieved_set_id=set_id)

    for sid, weight_kg, reps, rpe in rows:
        consider((PRKind.weight, None), weight_kg, sid)
        e1rm = estimated_1rm(weight_kg, reps, rir=_rpe_to_rir_for_e1rm(rpe))
        consider((PRKind.e1rm, None), e1rm, sid)
        consider((PRKind.volume, None), weight_kg * reps, sid)
        consider((PRKind.reps_at_weight, weight_kg), float(reps), sid)

    return slots


async def reconcile_exercise_prs(
    db: AsyncSession,
    *,
    user_id: int,
    exercise_id: uuid.UUID,
) -> dict[_Slot, PersonalRecord]:
    """Sync the persisted PRs for one Exercise to its current normal-Set history.

    Recomputes the authoritative slot set (:func:`_authoritative_slots`) and makes
    the ``personal_records`` rows match it **exactly**: update existing slots
    (up or down) when value or holder changed, insert new slots, and delete rows
    whose slot is no longer supported by any normal Set. This is the record of
    truth — idempotent, and the single place the table is mutated.

    Returns the resulting rows keyed by slot (the post-reconciliation state),
    which :func:`detect_and_persist_prs` diffs to drive the live celebration.
    """
    rows = await _normal_sets_for(db, user_id=user_id, exercise_id=exercise_id)
    desired = _authoritative_slots(rows)

    existing_rows = (
        await db.execute(
            select(PersonalRecord).where(
                PersonalRecord.user_id == user_id,
                PersonalRecord.exercise_id == exercise_id,
            )
        )
    ).scalars().all()
    existing: dict[_Slot, PersonalRecord] = {
        (r.kind, r.weight_bucket): r for r in existing_rows
    }

    result: dict[_Slot, PersonalRecord] = {}

    # Upsert every desired slot.
    for slot, best in desired.items():
        kind, bucket = slot
        row = existing.get(slot)
        if row is None:
            row = PersonalRecord(
                user_id=user_id,
                exercise_id=exercise_id,
                kind=kind,
                weight_bucket=bucket,
                value=best.value,
                achieved_set_id=best.achieved_set_id,
            )
            db.add(row)
        else:
            # Move up OR down — the truth tracks history in both directions.
            row.value = best.value
            row.achieved_set_id = best.achieved_set_id
        result[slot] = row

    # Retract any slot no longer supported by a normal Set.
    for slot, row in existing.items():
        if slot not in desired:
            await db.delete(row)

    await db.flush()
    return result


async def detect_and_persist_prs(
    db: AsyncSession, training_set: TrainingSet
) -> list[PRResult]:
    """Reconcile an Exercise after a Set write and return the PRs to celebrate.

    Snapshots the pre-write records, reconciles the whole Exercise to the current
    normal-Set history (which inserts/raises/lowers/retracts as needed), then
    returns only the dimensions this Set now **holds** that are genuinely new or
    improved versus the snapshot. That diff is what the UI celebrates — so editing
    a Set *down* (or flipping it non-normal) corrects the stored record without
    falsely re-firing a PR banner, while a true new best still celebrates.

    The owning Session is loaded once to resolve ``user_id`` and the Exercise.
    """
    session = (
        await db.execute(
            select(TrainingSession).where(
                TrainingSession.id == training_set.session_id
            )
        )
    ).scalar_one()
    user_id = session.user_id
    exercise_id = training_set.exercise_id
    set_id = training_set.id

    # Snapshot pre-write record values per slot, to tell new/improved from stale.
    before_rows = (
        await db.execute(
            select(PersonalRecord).where(
                PersonalRecord.user_id == user_id,
                PersonalRecord.exercise_id == exercise_id,
            )
        )
    ).scalars().all()
    before: dict[_Slot, float] = {
        (r.kind, r.weight_bucket): r.value for r in before_rows
    }

    after = await reconcile_exercise_prs(
        db, user_id=user_id, exercise_id=exercise_id
    )

    # Celebrate a slot iff THIS Set holds it post-reconciliation and it is newly
    # created or strictly higher than before (so an edit-down never celebrates).
    prs: list[PRResult] = []
    for slot, row in after.items():
        if row.achieved_set_id != set_id:
            continue
        prior_value = before.get(slot)
        if prior_value is None or row.value > prior_value:
            kind, bucket = slot
            prs.append(PRResult(kind=kind, value=row.value, at_weight_kg=bucket))

    # Stable, headline-first ordering for the banner.
    _ORDER = {
        PRKind.weight: 0,
        PRKind.e1rm: 1,
        PRKind.reps_at_weight: 2,
        PRKind.volume: 3,
    }
    prs.sort(key=lambda p: _ORDER[p.kind])
    return prs
