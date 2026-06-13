"""Fitbod import — the DB glue that turns a parsed CSV into Sessions/Sets.

Two phases, both driven from the pure :mod:`app.services.fitbod_parser` +
:mod:`app.services.matcher`:

* :func:`preview_fitbod_import` — parse + match, **no writes**. Returns a summary
  (session/set counts, how many names auto-resolved, the skip tally) and the list
  of unresolved names for the manual-match UI. Read-only.
* :func:`commit_fitbod_import` — write the data idempotently. Accepts a
  ``resolutions`` map (raw Fitbod name → chosen Exercise id) for the names the
  user matched/created in the UI; merges it over the auto-matches. Creates a
  Fitbod **Source**, an :class:`~app.models.import_batch.ImportBatch` audit row,
  the :class:`~app.models.training_session.TrainingSession`/``TrainingSet`` rows,
  and reconciles personal records for every touched Exercise.

Idempotency (CONTEXT.md "Import": re-running never duplicates) is at the
**Session grain**, keyed on a deterministic Session id — not a separate
fingerprint table. An imported Fitbod workout is an *immutable historical
record* identified by its timestamp:

* a Session's id = ``uuid5(_SESSION_NS, f"{user_id}|{started_at_iso}")`` — every
  set row in one Fitbod workout shares the Date timestamp, so the timestamp is
  the Session's natural key, scoped to the user (so one user's imports never
  collide with another's).

A Session whose id already exists for this user is **skipped whole** — we never
backfill sets into it. So re-importing the same CSV adds nothing, and importing
a later export adds only the workouts not yet imported. Skipping the whole
Session (rather than diffing sets) is both the right semantics for a finished
historical record *and* what keeps the ``(session_id, order_index)`` unique
constraint safe: a set-level backfill would shift order_index across runs
whenever the resolution set changed (e.g. import-skipping-unmatched, then
re-import with the name resolved) and collide. Set ids are still deterministic
(``uuid5(_SET_NS, …)``) for stable identity, but dedup never relies on them.

Unresolved names with no manual resolution are **skipped** (not written as
garbage), counted in ``unresolved_skipped``; the order_index within a Session is
assigned over the *kept* sets so it stays 0-based and gap-free.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.exercise import Exercise
from app.models.import_batch import ImportBatch
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.services.fitbod_parser import parse_fitbod_csv
from app.services.matcher import ExerciseNameIndex
from app.services.pr_service import reconcile_exercise_prs

# The Source name for imported Fitbod data (CONTEXT.md "Source").
FITBOD_SOURCE_NAME = "Fitbod"

# Stable namespaces for the deterministic ids (random once, fixed forever — must
# never change or re-imports would stop deduplicating against old data).
_SESSION_NS = uuid.UUID("0c5d3b2a-7e4f-4a1b-9c6d-2f8a1e3b5c7d")
_SET_NS = uuid.UUID("9a8b7c6d-5e4f-4321-8765-fedcba098765")


def _session_id(user_id: int, started_at_iso: str) -> uuid.UUID:
    return uuid.uuid5(_SESSION_NS, f"{user_id}|{started_at_iso}")


def _set_id(
    session_id: uuid.UUID,
    order_index: int,
    exercise_id: uuid.UUID,
    weight_kg: float,
    reps: int,
    set_type: SetType,
) -> uuid.UUID:
    key = (
        f"{session_id}|{order_index}|{exercise_id}|"
        f"{weight_kg}|{reps}|{set_type.value}"
    )
    return uuid.uuid5(_SET_NS, key)


@dataclass
class ImportPreview:
    """Read-only summary of what a Fitbod CSV would import."""

    session_count: int
    set_count: int
    skipped_rows: int
    # Names that auto-resolved to a library Exercise, and those that didn't.
    matched_names: dict[str, uuid.UUID] = field(default_factory=dict)
    unresolved_names: list[str] = field(default_factory=list)
    # How many kept Sets carry each raw Fitbod name (UI context).
    set_counts: dict[str, int] = field(default_factory=dict)

    @property
    def matched_count(self) -> int:
        return len(self.matched_names)


@dataclass
class ImportResult:
    """Outcome of a committed Fitbod import."""

    batch_id: uuid.UUID
    sessions_created: int
    sets_created: int
    unresolved_skipped: int
    skipped_rows: int


async def _visible_exercise_index(
    db: AsyncSession, user: User
) -> ExerciseNameIndex:
    """Build a name index over the Exercises this user can see (global ∪ own).

    Mirrors the library visibility rule (:mod:`app.api.exercises`). Entries are
    sorted by name so the index's normalised-collision tie-break is deterministic.
    """
    rows = (
        await db.execute(
            select(Exercise.id, Exercise.name)
            .where((Exercise.user_id.is_(None)) | (Exercise.user_id == user.id))
            .order_by(Exercise.name)
        )
    ).all()
    return ExerciseNameIndex([(r[0], r[1]) for r in rows])


async def preview_fitbod_import(
    db: AsyncSession, *, user: User, csv_text: str
) -> ImportPreview:
    """Parse + match a Fitbod CSV without writing anything.

    Raises :class:`app.services.fitbod_parser.FitbodParseError` if the file isn't
    a recognisable Fitbod export.
    """
    parsed = parse_fitbod_csv(csv_text)
    index = await _visible_exercise_index(db, user)
    matched, unresolved = index.resolve_all(parsed.exercise_names)
    return ImportPreview(
        set_counts=parsed.set_counts_by_name(),
        session_count=len(parsed.sessions),
        set_count=parsed.set_count,
        skipped_rows=parsed.skipped_rows,
        matched_names=matched,
        unresolved_names=unresolved,
    )


async def _get_or_create_source(db: AsyncSession) -> DataSource:
    """Get-or-create the shared Fitbod :class:`DataSource` (no bundle id)."""
    source = (
        await db.execute(
            select(DataSource).where(
                DataSource.name == FITBOD_SOURCE_NAME,
                DataSource.bundle_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = DataSource(name=FITBOD_SOURCE_NAME, bundle_id=None)
        db.add(source)
        await db.flush()
    return source


def _resolution_for(
    name: str,
    auto: dict[str, uuid.UUID],
    manual: dict[str, uuid.UUID],
) -> uuid.UUID | None:
    """Resolve a raw Fitbod name to an Exercise id: manual override wins."""
    if name in manual:
        return manual[name]
    return auto.get(name)


async def commit_fitbod_import(
    db: AsyncSession,
    *,
    user: User,
    csv_text: str,
    filename: str,
    resolutions: dict[str, uuid.UUID] | None = None,
) -> ImportResult:
    """Idempotently import a Fitbod CSV into the user's Sessions/Sets.

    ``resolutions`` maps raw Fitbod exercise names the user matched in the UI to
    the chosen Exercise id (a library Exercise or a custom one they created);
    these override the auto-matches. Names resolving to neither are skipped
    (counted, never written as a garbage Set). Re-running adds only what's
    missing (deterministic ids — see module docstring).

    Records an :class:`ImportBatch` audit row and reconciles personal records for
    every Exercise touched. Flushes within the caller's transaction; the caller
    commits.
    """
    manual = dict(resolutions or {})
    parsed = parse_fitbod_csv(csv_text)
    index = await _visible_exercise_index(db, user)
    auto, _ = index.resolve_all(parsed.exercise_names)

    # Register the Fitbod Source (CONTEXT.md "Source") so imported provenance is
    # recorded in the shared sources registry alongside Apple Health's. The
    # Session/Set tables carry no source FK (only sensor records do), so the
    # attribution is the registry row + the import-batch audit trail below.
    await _get_or_create_source(db)

    # Validate manual resolutions point at Exercises this user may use, so a
    # bogus/foreign id can't be smuggled in. Drop any that aren't visible.
    if manual:
        visible_ids = set(
            (
                await db.execute(
                    select(Exercise.id).where(
                        Exercise.id.in_(list(manual.values())),
                        (Exercise.user_id.is_(None))
                        | (Exercise.user_id == user.id),
                    )
                )
            ).scalars().all()
        )
        manual = {n: i for n, i in manual.items() if i in visible_ids}

    # Pre-compute Session ids and load which already exist for this user. An
    # imported Fitbod workout is an **immutable historical record** keyed on its
    # timestamp, so a Session that already exists is skipped WHOLE — we never
    # backfill sets into it. Dedup is therefore at the Session grain: re-running
    # adds only workouts not yet imported, and leaves existing ones untouched.
    # (Backfilling into an existing Session would shift order_index across runs
    # whenever the resolution set changed and collide on the
    # (session_id, order_index) unique constraint — the whole-Session skip avoids
    # that entirely and matches the "finished, historical" semantics.)
    session_ids = [
        _session_id(user.id, s.started_at.isoformat()) for s in parsed.sessions
    ]
    existing_session_ids = set(
        (
            await db.execute(
                select(TrainingSession.id).where(
                    TrainingSession.id.in_(session_ids),
                    TrainingSession.user_id == user.id,
                )
            )
        ).scalars().all()
    )

    sessions_created = 0
    sets_created = 0
    unresolved_skipped = 0
    touched_exercises: set[uuid.UUID] = set()

    for parsed_session, sid in zip(parsed.sessions, session_ids, strict=True):
        if sid in existing_session_ids:
            # Already imported on a prior run — leave it exactly as it is.
            continue

        # Build the Set rows. order_index counts the *resolvable* sets only, so
        # it stays 0-based and gap-free even when some Fitbod names were skipped.
        new_sets: list[TrainingSet] = []
        order = 0
        for pset in parsed_session.sets:
            ex_id = _resolution_for(pset.exercise_name, auto, manual)
            if ex_id is None:
                unresolved_skipped += 1
                continue
            set_type = SetType.warmup if pset.is_warmup else SetType.normal
            new_sets.append(
                TrainingSet(
                    id=_set_id(
                        sid, order, ex_id, pset.weight_kg, pset.reps, set_type
                    ),
                    session_id=sid,
                    exercise_id=ex_id,
                    order_index=order,
                    weight_kg=pset.weight_kg,
                    reps=pset.reps,
                    set_type=set_type,
                )
            )
            order += 1
            touched_exercises.add(ex_id)

        # A new Session with no resolvable sets (every set unresolved) is not
        # created at all — no empty hull.
        if not new_sets:
            continue

        db.add(
            TrainingSession(
                id=sid,
                user_id=user.id,
                started_at=parsed_session.started_at,
                # Imported Sessions are historical → already finished.
                ended_at=parsed_session.started_at,
            )
        )
        sessions_created += 1
        for tset in new_sets:
            db.add(tset)
            sets_created += 1

    await db.flush()

    # Reconcile PRs once per touched Exercise (cheap; a user's sets per exercise
    # are few). Non-normal/zero-load sets are excluded by the reconciler itself.
    for ex_id in touched_exercises:
        await reconcile_exercise_prs(db, user_id=user.id, exercise_id=ex_id)

    batch = ImportBatch(
        user_id=user.id,
        filename=filename,
        status="completed",
        record_count=sets_created,
        error_message=None,
    )
    db.add(batch)
    await db.flush()

    return ImportResult(
        batch_id=batch.id,
        sessions_created=sessions_created,
        sets_created=sets_created,
        unresolved_skipped=unresolved_skipped,
        skipped_rows=parsed.skipped_rows,
    )
