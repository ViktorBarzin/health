"""Apple Health XML export parser.

Streams through the (potentially multi-GB) ``export.xml`` file produced by
the Apple Health app, converting elements into database records and persisting
them in batches for constant memory usage.

Uses a producer-consumer pipeline: the parser (producer) never blocks on DB
writes — completed batches go onto a bounded ``asyncio.Queue``.  A pool of
consumer tasks drain the queue into the DB concurrently, with independent
table inserts running in parallel via ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Any

from lxml import etree
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.data_source import DataSource
from app.models.import_batch import ImportBatch
from app.services.dedup import (
    bulk_insert_activity_summaries,
    bulk_insert_category_records,
    bulk_insert_health_records,
    bulk_insert_workout_route_points,
    bulk_insert_workouts,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BATCH_SIZE = 25_000
MAX_QUEUE_DEPTH = 8
NUM_CONSUMERS = 3

_APPLE_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([+-]\d{4})"
)

_QUANTITY_PREFIX = "HKQuantityTypeIdentifier"
_CATEGORY_PREFIX = "HKCategoryTypeIdentifier"
_WORKOUT_PREFIX = "HKWorkoutActivityType"

# Energy conversion factors
_KCAL_TO_KJ = 4.184
_CAL_TO_KJ = 0.004184  # dietary Calorie = kcal, small cal = 1/1000 kcal

# Fixed namespace for deterministic workout UUIDs
_WORKOUT_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# Distance conversion factors
_KM_TO_M = 1_000.0
_MI_TO_M = 1_609.344

# Duration conversion factors
_MIN_TO_SEC = 60.0
_HR_TO_SEC = 3_600.0

# ---------------------------------------------------------------------------
# BatchPayload
# ---------------------------------------------------------------------------


@dataclass
class BatchPayload:
    """A self-contained batch of parsed records ready for DB insertion."""

    health: list[dict[str, Any]] = field(default_factory=list)
    category: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)
    route_points: list[dict[str, Any]] = field(default_factory=list)
    activity: list[dict[str, Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return (
            len(self.health)
            + len(self.category)
            + len(self.workouts)
            + len(self.route_points)
            + len(self.activity)
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_apple_date(date_str: str | None) -> datetime | None:
    """Parse the Apple Health date format ``2024-01-01 08:00:00 -0500``.

    Returns a timezone-aware :class:`datetime` or ``None`` when the input is
    missing / unparseable.
    """
    if not date_str:
        return None
    m = _APPLE_DATE_RE.match(date_str.strip())
    if not m:
        logger.warning("Unparseable date string: %r", date_str)
        return None
    iso = f"{m.group(1)}T{m.group(2)}{m.group(3)}"
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        logger.warning("Invalid ISO date: %s", iso)
        return None


def _parse_apple_date_only(date_str: str | None) -> date_type | None:
    """Parse a ``dateComponents`` string (``2024-01-01``) into a date."""
    if not date_str:
        return None
    try:
        return date_type.fromisoformat(date_str.strip())
    except ValueError:
        logger.warning("Unparseable date-only string: %r", date_str)
        return None


def _clean_type_name(raw_type: str, prefix: str) -> str:
    """Strip the HK prefix from a type identifier.

    >>> _clean_type_name("HKQuantityTypeIdentifierStepCount",
    ...                  "HKQuantityTypeIdentifier")
    'StepCount'
    """
    if raw_type.startswith(prefix):
        return raw_type[len(prefix):]
    return raw_type


def _clean_category_value(raw_value: str) -> str:
    """Derive a human-readable label from a raw HK category value string.

    Example::

        "HKCategoryValueSleepAnalysisAsleepDeep" -> "Asleep Deep"
        "HKCategoryValueAppleStandHourStood"     -> "Stood"
        "HKCategoryValueNotApplicable"           -> "Not Applicable"

    Strategy: strip the longest known ``HKCategoryValue*`` prefix, then split
    on CamelCase boundaries.
    """
    if not raw_value:
        return ""
    # Remove the generic "HKCategoryValue" prefix
    cleaned = raw_value
    if cleaned.startswith("HKCategoryValue"):
        cleaned = cleaned[len("HKCategoryValue"):]
    # Try to strip a secondary "topic" segment that ends before the real value
    # e.g. "SleepAnalysisAsleepDeep" -> keep the whole thing but split it
    # We insert spaces before uppercase letters that follow a lowercase letter
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", cleaned)
    return spaced.strip()


def _safe_float(value: str | None) -> float | None:
    """Convert a string to float, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: str | None) -> int | None:
    """Convert a string to int, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _convert_to_kj(value: float | None, unit: str | None) -> float | None:
    """Convert an energy value to kilojoules.

    Supports ``kcal``, ``Cal`` (dietary Calorie = kcal), and ``kJ``.
    """
    if value is None or unit is None:
        return None
    unit_lower = unit.strip().lower()
    if unit_lower in ("kcal", "cal"):
        return value * _KCAL_TO_KJ
    if unit_lower == "kj":
        return value
    # Unrecognised unit -- store raw with a warning
    logger.debug("Unknown energy unit %r; storing raw value", unit)
    return value


def _convert_to_meters(value: float | None, unit: str | None) -> float | None:
    """Convert a distance value to meters."""
    if value is None or unit is None:
        return None
    unit_lower = unit.strip().lower()
    if unit_lower == "km":
        return value * _KM_TO_M
    if unit_lower in ("mi", "mile", "miles"):
        return value * _MI_TO_M
    if unit_lower in ("m", "meter", "meters"):
        return value
    logger.debug("Unknown distance unit %r; storing raw value", unit)
    return value


def _convert_duration_to_seconds(
    value: float | None, unit: str | None
) -> float | None:
    """Convert a duration to seconds."""
    if value is None or unit is None:
        return None
    unit_lower = unit.strip().lower()
    if unit_lower in ("min", "minute", "minutes"):
        return value * _MIN_TO_SEC
    if unit_lower in ("hr", "hour", "hours"):
        return value * _HR_TO_SEC
    if unit_lower in ("s", "sec", "second", "seconds"):
        return value
    logger.debug("Unknown duration unit %r; storing raw value", unit)
    return value


# ---------------------------------------------------------------------------
# DataSource cache
# ---------------------------------------------------------------------------


class _DataSourceCache:
    """In-memory cache mapping ``(name, bundle_id)`` to a database ``id``.

    Avoids repeated SELECTs for the same source device during a single import
    run.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str | None], int] = {}

    async def warm(self, session: AsyncSession) -> None:
        """Pre-load all existing data sources into the cache."""
        result = await session.execute(select(DataSource))
        for source in result.scalars():
            self._cache[(source.name, source.bundle_id)] = source.id

    def lookup(self, name: str | None, bundle_id: str | None) -> int | None:
        """Fast-path cache check that requires no DB session."""
        if not name:
            return None
        key = (name, bundle_id)
        return self._cache.get(key)

    async def get_or_create(
        self,
        session: AsyncSession,
        name: str | None,
        bundle_id: str | None = None,
        device_info: str | None = None,
    ) -> int | None:
        if not name:
            return None

        key = (name, bundle_id)
        if key in self._cache:
            return self._cache[key]

        # Try to find existing
        stmt = select(DataSource).where(
            DataSource.name == name,
            DataSource.bundle_id == bundle_id
            if bundle_id is not None
            else DataSource.bundle_id.is_(None),
        )
        result = await session.execute(stmt)
        source = result.scalar_one_or_none()

        if source is None:
            source = DataSource(
                name=name, bundle_id=bundle_id, device_info=device_info
            )
            session.add(source)
            await session.flush()  # assign id

        self._cache[key] = source.id
        return source.id


# ---------------------------------------------------------------------------
# Element processors
# ---------------------------------------------------------------------------


def _process_record_element(
    elem: etree._Element,
    user_id: int,
    batch_id: str,
    source_id: int | None,
) -> tuple[str, dict[str, Any]] | None:
    """Convert a ``<Record>`` element into a categorised dict.

    Returns ``("health", dict)`` or ``("category", dict)`` or ``None`` if the
    element cannot be processed.
    """
    record_type = elem.get("type", "")

    start = _parse_apple_date(elem.get("startDate"))
    if start is None:
        return None

    end = _parse_apple_date(elem.get("endDate"))

    if record_type.startswith(_QUANTITY_PREFIX):
        raw_value = _safe_float(elem.get("value"))
        if raw_value is None:
            return None
        return (
            "health",
            {
                "time": start,
                "end_time": end,
                "user_id": user_id,
                "metric_type": _clean_type_name(record_type, _QUANTITY_PREFIX),
                "value": raw_value,
                "unit": elem.get("unit", ""),
                "source_id": source_id,
                "batch_id": batch_id,
            },
        )

    if record_type.startswith(_CATEGORY_PREFIX):
        raw_value = elem.get("value", "")
        return (
            "category",
            {
                "time": start,
                "end_time": end,
                "user_id": user_id,
                "category_type": _clean_type_name(
                    record_type, _CATEGORY_PREFIX
                ),
                "value": raw_value,
                "value_label": _clean_category_value(raw_value),
                "source_id": source_id,
                "batch_id": batch_id,
            },
        )

    # Unknown record type -- skip gracefully
    return None


def _process_workout_element(
    elem: etree._Element,
    user_id: int,
    batch_id: str,
    source_id: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Convert a ``<Workout>`` element into a workout dict and route points."""
    start = _parse_apple_date(elem.get("startDate"))
    end = _parse_apple_date(elem.get("endDate"))

    activity_raw = elem.get("workoutActivityType", "")
    activity_type = _clean_type_name(activity_raw, _WORKOUT_PREFIX)

    # Deterministic UUID from the workout's natural key so re-imports
    # produce the same ID and ON CONFLICT dedup works correctly.
    # Must match the UniqueConstraint: (user_id, time, activity_type).
    dedup_key = f"{user_id}:{start.isoformat() if start else ''}:{activity_type}"
    workout_id = uuid.uuid5(_WORKOUT_NS, dedup_key)

    duration_val = _safe_float(elem.get("duration"))
    duration_unit = elem.get("durationUnit", "min")
    duration_sec = _convert_duration_to_seconds(duration_val, duration_unit)

    distance_val = _safe_float(elem.get("totalDistance"))
    distance_unit = elem.get("totalDistanceUnit", "km")
    total_distance_m = _convert_to_meters(distance_val, distance_unit)

    energy_val = _safe_float(elem.get("totalEnergyBurned"))
    energy_unit = elem.get("totalEnergyBurnedUnit", "kcal")
    total_energy_kj = _convert_to_kj(energy_val, energy_unit)

    # Collect any nested metadata entries
    metadata: dict[str, str] = {}
    for meta_elem in elem.iter("MetadataEntry"):
        key = meta_elem.get("key")
        val = meta_elem.get("value")
        if key:
            metadata[key] = val or ""

    workout = {
        "id": workout_id,
        "user_id": user_id,
        "time": start,
        "end_time": end,
        "activity_type": activity_type,
        "duration_sec": duration_sec,
        "total_distance_m": total_distance_m,
        "total_energy_kj": total_energy_kj,
        "source_id": source_id,
        "batch_id": batch_id,
        "metadata": metadata if metadata else None,
    }

    # Parse route points from nested <WorkoutRoute>/<Location> elements
    route_points: list[dict[str, Any]] = []
    for route in elem.iter("WorkoutRoute"):
        for loc in route.iter("Location"):
            pt_time = _parse_apple_date(loc.get("date"))
            lat = _safe_float(loc.get("latitude"))
            lon = _safe_float(loc.get("longitude"))
            alt = _safe_float(loc.get("altitude"))
            if pt_time is not None and lat is not None and lon is not None:
                route_points.append(
                    {
                        "time": pt_time,
                        "workout_id": workout_id,
                        "latitude": lat,
                        "longitude": lon,
                        "altitude_m": alt,
                    }
                )

    return workout, route_points


def _process_activity_summary_element(
    elem: etree._Element,
    user_id: int,
) -> dict[str, Any] | None:
    """Convert an ``<ActivitySummary>`` element into a dict."""
    d = _parse_apple_date_only(elem.get("dateComponents"))
    if d is None:
        return None

    energy_val = _safe_float(elem.get("activeEnergyBurned"))
    energy_unit = elem.get("activeEnergyBurnedUnit", "kcal")
    goal_val = _safe_float(elem.get("activeEnergyBurnedGoal"))

    return {
        "date": d,
        "user_id": user_id,
        "active_energy_burned_kj": _convert_to_kj(energy_val, energy_unit),
        "active_energy_goal_kj": _convert_to_kj(goal_val, energy_unit),
        "exercise_minutes": _safe_float(elem.get("appleExerciseTime")),
        "exercise_goal_minutes": _safe_float(
            elem.get("appleExerciseTimeGoal")
        ),
        "stand_hours": _safe_int(elem.get("appleStandHours")),
        "stand_goal_hours": _safe_int(elem.get("appleStandHoursGoal")),
    }


# ---------------------------------------------------------------------------
# Producer / Consumer pipeline
# ---------------------------------------------------------------------------


async def _producer(
    file_path: str,
    user_id: int,
    batch_id: str,
    db_session_factory: async_sessionmaker,
    queue: asyncio.Queue[BatchPayload | None],
    num_consumers: int,
    cancelled: list[bool],
    source_cache: _DataSourceCache,
) -> int:
    """Parse the XML file and enqueue batches for consumers.

    Returns the total number of records parsed.
    """
    batch = BatchPayload()
    total_count = 0
    health_count = 0
    category_count = 0
    workout_count = 0
    route_point_count = 0
    activity_count = 0
    skipped_workouts = 0

    # Use recover=True to tolerate malformed XML (Apple Health exports
    # sometimes contain unescaped characters in attribute values).
    context = etree.iterparse(
        file_path,
        events=("end",),
        tag=("Record", "Workout", "ActivitySummary"),
        recover=True,
    )

    for _event, elem in context:
        tag = elem.tag

        # -- Resolve DataSource (shared across record types) ---------------
        source_name = elem.get("sourceName")
        bundle_id = elem.get("sourceVersion")  # close proxy
        device_info = elem.get("device")

        # Fast path: check in-memory cache before touching DB
        source_id = source_cache.lookup(source_name, bundle_id)
        if source_id is None and source_name:
            async with db_session_factory() as session:
                source_id = await source_cache.get_or_create(
                    session, source_name, bundle_id, device_info
                )
                await session.commit()

        if tag == "Record":
            result = _process_record_element(
                elem, user_id, batch_id, source_id
            )
            if result is not None:
                kind, data = result
                if kind == "health":
                    batch.health.append(data)
                    health_count += 1
                else:
                    batch.category.append(data)
                    category_count += 1
                total_count += 1

        elif tag == "Workout":
            workout, route_points = _process_workout_element(
                elem, user_id, batch_id, source_id
            )
            if workout["time"] is None:
                logger.warning(
                    "Skipping workout with unparseable startDate: %s",
                    elem.get("startDate"),
                )
                skipped_workouts += 1
            else:
                batch.workouts.append(workout)
                batch.route_points.extend(route_points)
                workout_count += 1
                route_point_count += len(route_points)
                total_count += 1

        elif tag == "ActivitySummary":
            summary = _process_activity_summary_element(elem, user_id)
            if summary is not None:
                batch.activity.append(summary)
                activity_count += 1
                total_count += 1

        # -- Yield to event loop periodically so consumers can work ----------
        if total_count > 0 and total_count % 2000 == 0:
            await asyncio.sleep(0)

        # -- Enqueue when batch is full ------------------------------------
        if len(batch) >= BATCH_SIZE:
            await queue.put(batch)
            batch = BatchPayload()
            if cancelled[0]:
                break

        # -- Free memory: clear element and preceding siblings -------------
        elem.clear()
        while elem.getprevious() is not None:
            parent = elem.getparent()
            if parent is None:
                break
            del parent[0]

    # Enqueue any remaining records
    if len(batch) > 0 and not cancelled[0]:
        await queue.put(batch)

    # Send poison pills so each consumer knows to stop
    for _ in range(num_consumers):
        await queue.put(None)

    logger.info(
        "Parsing complete: %d health, %d category, %d workouts (%d route pts), "
        "%d activity summaries, %d total (%d workouts skipped)",
        health_count, category_count, workout_count, route_point_count,
        activity_count, total_count, skipped_workouts,
    )

    return total_count


async def _consumer(
    consumer_id: int,
    db_session_factory: async_sessionmaker,
    queue: asyncio.Queue[BatchPayload | None],
    progress: list[int],
) -> None:
    """Pull batches from the queue and flush them to the DB."""
    while True:
        batch = await queue.get()
        if batch is None:
            queue.task_done()
            return
        try:
            await _flush_batch(db_session_factory, batch)
            progress[0] += len(batch)
        finally:
            queue.task_done()


async def _flush_batch(
    db_session_factory: async_sessionmaker,
    batch: BatchPayload,
) -> None:
    """Persist one batch using concurrent table inserts.

    Independent tables (health, category, activity) are written in parallel.
    Workouts are inserted separately so that a workout failure doesn't cancel
    the independent inserts via ``asyncio.gather``.
    """
    coros: list = []

    if batch.health:
        coros.append(_insert_table(db_session_factory, bulk_insert_health_records, batch.health))
    if batch.category:
        coros.append(_insert_table(db_session_factory, bulk_insert_category_records, batch.category))
    if batch.activity:
        coros.append(_insert_table(db_session_factory, bulk_insert_activity_summaries, batch.activity))

    if coros:
        await asyncio.gather(*coros)

    # Workouts separately so failures don't cancel independent inserts
    if batch.workouts:
        try:
            await _insert_workouts_and_routes(db_session_factory, batch.workouts, batch.route_points)
        except Exception:
            logger.exception(
                "Failed to insert %d workouts (%d route points) — "
                "health/category/activity records from this batch were saved",
                len(batch.workouts), len(batch.route_points),
            )

    logger.debug("Flushed batch to database")


async def _insert_table(db_session_factory: async_sessionmaker, insert_fn, rows: list[dict[str, Any]]) -> None:
    """Insert rows into a single table using its own session."""
    async with db_session_factory() as session:
        await insert_fn(session, rows)
        await session.commit()


async def _insert_workouts_and_routes(
    db_session_factory: async_sessionmaker,
    workouts: list[dict[str, Any]],
    route_points: list[dict[str, Any]],
) -> None:
    """Insert workouts first, then route points (FK dependency)."""
    async with db_session_factory() as session:
        await bulk_insert_workouts(session, workouts)
        await session.commit()

    if route_points:
        async with db_session_factory() as session:
            await bulk_insert_workout_route_points(session, route_points)
            await session.commit()


async def _progress_reporter(
    db_session_factory: async_sessionmaker,
    batch_id: str,
    progress: list[int],
    cancelled: list[bool],
    interval: float = 2.0,
) -> None:
    """Periodically write the current progress count to import_batches.

    Also polls the batch status — when it reads ``"cancelling"`` it sets the
    shared *cancelled* flag so the producer can exit early.
    """
    last_reported = -1
    try:
        while True:
            await asyncio.sleep(interval)
            current = progress[0]
            try:
                async with db_session_factory() as session:
                    if current != last_reported:
                        await session.execute(
                            update(ImportBatch)
                            .where(ImportBatch.id == batch_id)
                            .values(record_count=current)
                        )
                        await session.commit()
                        last_reported = current

                    # Check for cancellation request
                    result = await session.execute(
                        select(ImportBatch.status).where(
                            ImportBatch.id == batch_id
                        )
                    )
                    status = result.scalar_one_or_none()
                    if status == "cancelling":
                        cancelled[0] = True
                        return
            except Exception:
                logger.debug("Progress reporter update failed", exc_info=True)
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Main parser entry point
# ---------------------------------------------------------------------------


async def parse_health_export(
    file_path: str,
    user_id: int,
    batch_id: str,
    db_session_factory: async_sessionmaker,
) -> int:
    """Stream-parse an Apple Health ``export.xml`` and persist all records.

    Parameters
    ----------
    file_path:
        Absolute path to the XML file on disk.
    user_id:
        The owning user's primary key.
    batch_id:
        UUID (as string) of the :class:`ImportBatch` row for this import.
    db_session_factory:
        An ``async_sessionmaker`` used to create fresh sessions for each
        flush batch.

    Returns
    -------
    int
        Total number of records processed.
    """
    queue: asyncio.Queue[BatchPayload | None] = asyncio.Queue(
        maxsize=MAX_QUEUE_DEPTH
    )
    total_count = 0
    progress: list[int] = [0]
    cancelled: list[bool] = [False]
    reporter_task: asyncio.Task | None = None

    try:
        # Pre-warm the DataSource cache to avoid per-record DB lookups
        source_cache = _DataSourceCache()
        async with db_session_factory() as session:
            await source_cache.warm(session)

        # Start consumer tasks
        consumer_tasks = [
            asyncio.create_task(
                _consumer(i, db_session_factory, queue, progress),
                name=f"db-consumer-{i}",
            )
            for i in range(NUM_CONSUMERS)
        ]

        producer_task = asyncio.create_task(
            _producer(
                file_path, user_id, batch_id, db_session_factory,
                queue, NUM_CONSUMERS, cancelled, source_cache,
            ),
            name="xml-producer",
        )

        reporter_task = asyncio.create_task(
            _progress_reporter(db_session_factory, batch_id, progress, cancelled),
            name="progress-reporter",
        )

        # Wait for producer or any consumer to finish/fail.
        # FIRST_EXCEPTION ensures we detect consumer crashes early instead of
        # the producer deadlocking on a full queue.
        all_tasks = [producer_task, *consumer_tasks]
        done, pending = await asyncio.wait(
            all_tasks, return_when=asyncio.FIRST_EXCEPTION
        )

        # Check for exceptions in completed tasks
        for task in done:
            if task.exception() is not None:
                # Cancel everything still running
                for p in pending:
                    p.cancel()
                reporter_task.cancel()
                # Re-raise the first failure
                raise task.exception()  # type: ignore[misc]

        # If producer finished first (normal path), wait for consumers to
        # drain the queue
        if producer_task in done:
            total_count = producer_task.result()
            for task in consumer_tasks:
                if not task.done():
                    await task

        # Check consumers for late exceptions
        for task in consumer_tasks:
            if task.exception() is not None:
                reporter_task.cancel()
                raise task.exception()  # type: ignore[misc]

        # Stop the progress reporter
        reporter_task.cancel()
        try:
            await reporter_task
        except asyncio.CancelledError:
            pass

        # Mark import as complete or cancelled
        final_status = "cancelled" if cancelled[0] else "completed"
        async with db_session_factory() as session:
            await session.execute(
                update(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .values(record_count=total_count, status=final_status)
            )
            await session.commit()

        logger.info(
            "Import %s finished (%s): %d records processed",
            batch_id, final_status, total_count,
        )

    except Exception:
        logger.exception("Import %s failed", batch_id)
        if reporter_task is not None:
            reporter_task.cancel()
        # Best-effort status update
        try:
            async with db_session_factory() as session:
                await session.execute(
                    update(ImportBatch)
                    .where(ImportBatch.id == batch_id)
                    .values(record_count=total_count, status="failed")
                )
                await session.commit()
        except Exception:
            logger.exception("Could not update batch status to 'failed'")
        raise

    return total_count
