"""Bulk-insert helpers with ON CONFLICT DO NOTHING for idempotent imports.

Uses PostgreSQL COPY for high-volume tables (health_records, category_records,
activity_summaries, workout_route_points) via a temp-table staging pattern.
Workouts use parameterised INSERT due to the JSONB metadata column.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workout import Workout

logger = logging.getLogger(__name__)


_MAX_PARAMS = 32_000  # asyncpg hard limit is 32767; leave margin


# ------------------------------------------------------------------
# COPY-based bulk insert (fast path for high-volume tables)
# ------------------------------------------------------------------


async def _copy_upsert(
    session: AsyncSession,
    table_name: str,
    columns: list[str],
    records: list[tuple],
    *,
    conflict_target: str | None = None,
) -> int:
    """Bulk-insert via COPY into a temp table, then INSERT ... ON CONFLICT.

    This avoids asyncpg's parameter limit and is substantially faster than
    parameterised INSERT for large batches (3-5x measured improvement).

    Parameters
    ----------
    session:
        An active async SQLAlchemy session.
    table_name:
        The target table name.
    columns:
        Ordered column names matching the tuple positions in *records*.
    records:
        Row data as a list of tuples (one tuple per row).
    conflict_target:
        SQL fragment for ON CONFLICT, e.g.
        ``"(time, user_id, metric_type)"``.
        If ``None``, uses bare ``ON CONFLICT DO NOTHING``.
    """
    if not records:
        return 0

    conn = await session.connection()
    raw = await conn.get_raw_connection()
    asyncpg_conn = raw.dbapi_connection.driver_connection

    tmp = f"_tmp_{table_name}"
    col_list = ", ".join(columns)

    # Create an unlogged temp table matching the target schema (structure only).
    # Avoid ON COMMIT DROP because the raw asyncpg connection may auto-commit
    # each statement, which would drop the table before COPY runs.
    await asyncpg_conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    await asyncpg_conn.execute(
        f"CREATE TEMP TABLE {tmp} (LIKE {table_name} INCLUDING DEFAULTS)"
    )

    # COPY rows into the temp table
    await asyncpg_conn.copy_records_to_table(
        tmp, records=records, columns=columns
    )

    # Move from temp into the real table, skipping conflicts
    if conflict_target:
        conflict_clause = f"ON CONFLICT {conflict_target} DO NOTHING"
    else:
        conflict_clause = "ON CONFLICT DO NOTHING"

    await asyncpg_conn.execute(
        f"INSERT INTO {table_name} ({col_list}) SELECT {col_list} FROM {tmp} {conflict_clause}"
    )

    await asyncpg_conn.execute(f"DROP TABLE IF EXISTS {tmp}")

    return len(records)


# ------------------------------------------------------------------
# Parameterised INSERT fallback (for tables with complex types like JSONB)
# ------------------------------------------------------------------


async def _bulk_upsert(
    session: AsyncSession,
    model: type,
    rows: list[dict[str, Any]],
    *,
    conflict_target: list[str] | None = None,
) -> int:
    """Insert *rows* into *model*'s table, silently skipping conflicts.

    Automatically chunks into multiple INSERT statements to stay within
    asyncpg's 32 767 query-parameter limit.

    Returns the number of rows in the batch (not necessarily inserted, since
    conflicts are ignored).
    """
    if not rows:
        return 0

    table = inspect(model).local_table
    num_cols = len(rows[0])
    chunk_size = max(1, _MAX_PARAMS // num_cols)

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = pg_insert(table).values(chunk)

        if conflict_target:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_target)
        else:
            stmt = stmt.on_conflict_do_nothing()

        await session.execute(stmt)

    return len(rows)


# ------------------------------------------------------------------
# Public helpers -- one per entity type
# ------------------------------------------------------------------

_HEALTH_COLS = [
    "time", "user_id", "metric_type", "value", "unit",
    "end_time", "source_id", "batch_id",
]


async def bulk_insert_health_records(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert HealthRecord dicts using COPY, skipping conflicts."""
    rows = [
        tuple(r[c] for c in _HEALTH_COLS)
        for r in records
    ]
    return await _copy_upsert(
        session,
        "health_records",
        _HEALTH_COLS,
        rows,
    )


_CATEGORY_COLS = [
    "time", "user_id", "category_type", "value", "value_label",
    "end_time", "source_id", "batch_id",
]


async def bulk_insert_category_records(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert CategoryRecord dicts using COPY, skipping conflicts."""
    rows = [
        tuple(r[c] for c in _CATEGORY_COLS)
        for r in records
    ]
    return await _copy_upsert(
        session,
        "category_records",
        _CATEGORY_COLS,
        rows,
        conflict_target="(time, user_id, category_type)",
    )


_ACTIVITY_COLS = [
    "date", "user_id", "active_energy_burned_kj", "active_energy_goal_kj",
    "exercise_minutes", "exercise_goal_minutes", "stand_hours", "stand_goal_hours",
]


async def bulk_insert_activity_summaries(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert ActivitySummary dicts using COPY, skipping conflicts."""
    rows = [
        tuple(r[c] for c in _ACTIVITY_COLS)
        for r in records
    ]
    return await _copy_upsert(
        session,
        "activity_summaries",
        _ACTIVITY_COLS,
        rows,
        conflict_target="(date, user_id)",
    )


# Workouts keep parameterised INSERT (JSONB column)

async def bulk_insert_workouts(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert Workout dicts, deduplicating on the natural key."""
    # Serialize metadata dicts to JSON strings for asyncpg
    for r in records:
        if "metadata" in r and isinstance(r["metadata"], dict):
            r["metadata"] = json.dumps(r["metadata"])
    return await _bulk_upsert(
        session,
        Workout,
        records,
        conflict_target=["user_id", "time", "activity_type"],
    )


_ROUTE_POINT_COLS = ["time", "workout_id", "latitude", "longitude", "altitude_m"]


async def bulk_insert_workout_route_points(
    session: AsyncSession,
    records: list[dict[str, Any]],
) -> int:
    """Bulk-insert WorkoutRoutePoint dicts using COPY, skipping conflicts."""
    rows = [tuple(r[c] for c in _ROUTE_POINT_COLS) for r in records]
    return await _copy_upsert(
        session,
        "workout_route_points",
        _ROUTE_POINT_COLS,
        rows,
        conflict_target="(time, workout_id)",
    )
