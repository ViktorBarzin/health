"""Bulk-insert helpers with ON CONFLICT DO NOTHING for idempotent imports."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_summary import ActivitySummary
from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.models.workout import Workout
from app.models.workout_route_point import WorkoutRoutePoint

logger = logging.getLogger(__name__)


async def _bulk_upsert(
    session: AsyncSession,
    model: type,
    rows: list[dict[str, Any]],
    *,
    conflict_target: list[str] | None = None,
) -> int:
    """Insert *rows* into *model*'s table, silently skipping conflicts.

    Returns the number of rows in the batch (not necessarily inserted, since
    conflicts are ignored).
    """
    if not rows:
        return 0

    table = inspect(model).local_table
    stmt = pg_insert(table).values(rows)

    if conflict_target:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_target)
    else:
        stmt = stmt.on_conflict_do_nothing()

    await session.execute(stmt)
    return len(rows)


# ------------------------------------------------------------------
# Public helpers -- one per entity type
# ------------------------------------------------------------------


async def bulk_insert_health_records(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert HealthRecord dicts with conflict dedup.

    The unique constraint is (user_id, metric_type, time, value, source_id).
    """
    return await _bulk_upsert(
        session,
        HealthRecord,
        records,
        conflict_target=["user_id", "metric_type", "time", "value", "source_id"],
    )


async def bulk_insert_category_records(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert CategoryRecord dicts with conflict dedup.

    The composite PK is (time, user_id, category_type).
    """
    return await _bulk_upsert(
        session,
        CategoryRecord,
        records,
        conflict_target=["time", "user_id", "category_type"],
    )


async def bulk_insert_workouts(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert Workout dicts (PK = id UUID, so duplicates are rare)."""
    return await _bulk_upsert(
        session,
        Workout,
        records,
        conflict_target=["id"],
    )


async def bulk_insert_workout_route_points(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert WorkoutRoutePoint dicts with conflict dedup.

    The composite PK is (time, workout_id).
    """
    return await _bulk_upsert(
        session,
        WorkoutRoutePoint,
        records,
        conflict_target=["time", "workout_id"],
    )


async def bulk_insert_activity_summaries(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert ActivitySummary dicts with conflict dedup.

    The composite PK is (date, user_id).
    """
    return await _bulk_upsert(
        session,
        ActivitySummary,
        records,
        conflict_target=["date", "user_id"],
    )
