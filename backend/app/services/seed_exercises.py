"""Seed the shared Exercise library from the vendored free-exercise-db dataset.

The dataset (github.com/yuhonas/free-exercise-db, public domain) is vendored as
``app/data/free_exercise_db.json`` pinned to a commit so seeding is reproducible
and offline-friendly — no network fetch, no image binaries in the repo. Images
are referenced by jsDelivr CDN URL built from the dataset's relative image paths.

Seeding is idempotent: it upserts global Exercises keyed on the dataset ``id``
(stored as ``slug`` with ``user_id IS NULL``), so re-running adds nothing
duplicated and flows through any changed fields. It is safe to run on every boot
(invoked from ``entrypoint.sh`` after ``alembic upgrade head``) and runnable
manually via ``python -m app.services.seed_exercises``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "free_exercise_db.json"
SOURCE_NAME = "free-exercise-db"

# jsDelivr serves the dataset repo's images straight from GitHub at a pinned ref,
# so the repo carries zero image bytes. The dataset stores relative paths like
# ``3_4_Sit-Up/0.jpg``; this prefix + the pinned SHA yields a stable CDN URL.
_SHA_FILE = DATA_FILE.with_suffix(".SHA")
_PINNED_REF = _SHA_FILE.read_text().strip() if _SHA_FILE.exists() else "main"
_CDN_PREFIX = f"https://cdn.jsdelivr.net/gh/yuhonas/free-exercise-db@{_PINNED_REF}/exercises/"


def _cdn_image_url(relative_path: str) -> str:
    """Map a dataset-relative image path to its pinned jsDelivr CDN URL."""
    return _CDN_PREFIX + relative_path.lstrip("/")


@dataclass(frozen=True)
class SeedResult:
    """Outcome of one seed run, for logging and tests."""

    inserted: int
    updated: int
    total: int


def _load_dataset(path: Path = DATA_FILE) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _muscle(label: str) -> Muscle | None:
    """Map a dataset muscle label to the typed enum, ignoring unknowns."""
    try:
        return Muscle(label)
    except ValueError:
        return None


def _desired_muscles(record: dict) -> list[tuple[Muscle, MuscleRole]]:
    """The (muscle, role) pairs a dataset record should map to, de-duplicated.

    A muscle listed as primary wins over the same muscle also appearing as
    secondary, so no muscle is mapped twice for one Exercise.
    """
    pairs: dict[Muscle, MuscleRole] = {}
    for label in record.get("primaryMuscles", []) or []:
        m = _muscle(label)
        if m is not None:
            pairs[m] = MuscleRole.primary
    for label in record.get("secondaryMuscles", []) or []:
        m = _muscle(label)
        if m is not None and m not in pairs:
            pairs[m] = MuscleRole.secondary
    return list(pairs.items())


def _apply_fields(exercise: Exercise, record: dict) -> None:
    """Copy the scalar/JSON fields from a dataset record onto an Exercise row."""
    exercise.name = record["name"]
    exercise.category = record.get("category")
    exercise.force = record.get("force")
    exercise.level = record.get("level")
    exercise.mechanic = record.get("mechanic")
    exercise.equipment = record.get("equipment")
    exercise.instructions = list(record.get("instructions") or [])
    exercise.images = [_cdn_image_url(p) for p in (record.get("images") or [])]
    exercise.source = SOURCE_NAME


def _sync_muscles(exercise: Exercise, record: dict) -> None:
    """Reconcile an Exercise's muscle rows to match the dataset record.

    Idempotent: existing rows that still apply are kept, gone ones removed, new
    ones added — so re-seeding never accumulates duplicate mappings.
    """
    desired = dict(_desired_muscles(record))
    existing = {m.muscle: m for m in exercise.muscles}

    for muscle, link in list(existing.items()):
        if muscle not in desired:
            exercise.muscles.remove(link)
        elif link.role != desired[muscle]:
            link.role = desired[muscle]

    for muscle, role in desired.items():
        if muscle not in existing:
            exercise.muscles.append(ExerciseMuscle(muscle=muscle, role=role))


async def seed_exercises(
    session: AsyncSession, dataset: list[dict] | None = None
) -> SeedResult:
    """Upsert the global Exercise library from the dataset; return the tally.

    Keys on the dataset ``id`` as ``slug`` among global rows (``user_id IS
    NULL``). Custom Exercises (non-NULL ``user_id``) are never touched.
    """
    records = dataset if dataset is not None else _load_dataset()

    # One query for all existing global rows (with muscles eager-loaded via the
    # relationship's selectin) keyed by slug — avoids a per-record round trip.
    result = await session.execute(
        select(Exercise).where(Exercise.user_id.is_(None))
    )
    by_slug: dict[str, Exercise] = {ex.slug: ex for ex in result.scalars().all()}

    inserted = updated = 0
    for record in records:
        slug = record["id"]
        exercise = by_slug.get(slug)
        if exercise is None:
            exercise = Exercise(slug=slug, user_id=None)
            session.add(exercise)
            by_slug[slug] = exercise
            inserted += 1
        else:
            updated += 1
        _apply_fields(exercise, record)
        _sync_muscles(exercise, record)

    await session.commit()
    return SeedResult(inserted=inserted, updated=updated, total=len(records))


async def _main() -> None:
    async with async_session() as session:
        result = await seed_exercises(session)
    print(
        f"Seeded Exercise library from {SOURCE_NAME}: "
        f"{result.inserted} inserted, {result.updated} updated, "
        f"{result.total} total."
    )


if __name__ == "__main__":
    asyncio.run(_main())
