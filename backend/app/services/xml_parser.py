"""Apple Health XML export parser.

Streams through the (potentially multi-GB) ``export.xml`` file produced by
the Apple Health app, converting elements into database records and persisting
them in batches for constant memory usage.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date as date_type, datetime, timezone
from typing import Any

from lxml import etree
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.activity_summary import ActivitySummary
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
BATCH_SIZE = 5_000

_APPLE_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([+-]\d{4})"
)

_QUANTITY_PREFIX = "HKQuantityTypeIdentifier"
_CATEGORY_PREFIX = "HKCategoryTypeIdentifier"
_WORKOUT_PREFIX = "HKWorkoutActivityType"

# Energy conversion factors
_KCAL_TO_KJ = 4.184
_CAL_TO_KJ = 0.004184  # dietary Calorie = kcal, small cal = 1/1000 kcal

# Distance conversion factors
_KM_TO_M = 1_000.0
_MI_TO_M = 1_609.344

# Duration conversion factors
_MIN_TO_SEC = 60.0
_HR_TO_SEC = 3_600.0

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
    workout_id = uuid.uuid4()

    start = _parse_apple_date(elem.get("startDate"))
    end = _parse_apple_date(elem.get("endDate"))

    activity_raw = elem.get("workoutActivityType", "")
    activity_type = _clean_type_name(activity_raw, _WORKOUT_PREFIX)

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
    health_buf: list[dict[str, Any]] = []
    category_buf: list[dict[str, Any]] = []
    workout_buf: list[dict[str, Any]] = []
    route_point_buf: list[dict[str, Any]] = []
    activity_buf: list[dict[str, Any]] = []

    total_count = 0
    source_cache = _DataSourceCache()

    try:
        context = etree.iterparse(
            file_path,
            events=("end",),
            tag=("Record", "Workout", "ActivitySummary"),
        )

        for _event, elem in context:
            tag = elem.tag

            # -- Resolve DataSource (shared across record types) -----------
            source_name = elem.get("sourceName")
            bundle_id = elem.get("sourceVersion")  # close proxy
            device_info = elem.get("device")

            if tag == "Record":
                # Obtain or create source lazily (need a session)
                async with db_session_factory() as session:
                    source_id = await source_cache.get_or_create(
                        session, source_name, bundle_id, device_info
                    )
                    await session.commit()

                result = _process_record_element(
                    elem, user_id, batch_id, source_id
                )
                if result is not None:
                    kind, data = result
                    if kind == "health":
                        health_buf.append(data)
                    else:
                        category_buf.append(data)
                    total_count += 1

            elif tag == "Workout":
                async with db_session_factory() as session:
                    source_id = await source_cache.get_or_create(
                        session, source_name, bundle_id, device_info
                    )
                    await session.commit()

                workout, route_points = _process_workout_element(
                    elem, user_id, batch_id, source_id
                )
                workout_buf.append(workout)
                route_point_buf.extend(route_points)
                total_count += 1

            elif tag == "ActivitySummary":
                summary = _process_activity_summary_element(elem, user_id)
                if summary is not None:
                    activity_buf.append(summary)
                    total_count += 1

            # -- Flush when any buffer exceeds the batch size ---------------
            buf_size = (
                len(health_buf)
                + len(category_buf)
                + len(workout_buf)
                + len(route_point_buf)
                + len(activity_buf)
            )
            if buf_size >= BATCH_SIZE:
                await _flush_buffers(
                    db_session_factory,
                    health_buf,
                    category_buf,
                    workout_buf,
                    route_point_buf,
                    activity_buf,
                )

            # -- Free memory: clear element and preceding siblings ----------
            elem.clear()
            while elem.getprevious() is not None:
                parent = elem.getparent()
                if parent is None:
                    break
                del parent[0]

        # Flush remaining records
        await _flush_buffers(
            db_session_factory,
            health_buf,
            category_buf,
            workout_buf,
            route_point_buf,
            activity_buf,
        )

        # Mark import as complete
        async with db_session_factory() as session:
            await session.execute(
                update(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .values(record_count=total_count, status="completed")
            )
            await session.commit()

        logger.info(
            "Import %s finished: %d records processed", batch_id, total_count
        )

    except Exception:
        logger.exception("Import %s failed", batch_id)
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


# ---------------------------------------------------------------------------
# Internal flush helper
# ---------------------------------------------------------------------------


async def _flush_buffers(
    db_session_factory: async_sessionmaker,
    health_buf: list[dict[str, Any]],
    category_buf: list[dict[str, Any]],
    workout_buf: list[dict[str, Any]],
    route_point_buf: list[dict[str, Any]],
    activity_buf: list[dict[str, Any]],
) -> None:
    """Persist all buffered records and clear the buffers."""
    if not any(
        [health_buf, category_buf, workout_buf, route_point_buf, activity_buf]
    ):
        return

    async with db_session_factory() as session:
        if health_buf:
            await bulk_insert_health_records(session, health_buf)
        if category_buf:
            await bulk_insert_category_records(session, category_buf)
        # Workouts must be inserted before route points (FK constraint)
        if workout_buf:
            await bulk_insert_workouts(session, workout_buf)
        if route_point_buf:
            await bulk_insert_workout_route_points(session, route_point_buf)
        if activity_buf:
            await bulk_insert_activity_summaries(session, activity_buf)
        await session.commit()

    health_buf.clear()
    category_buf.clear()
    workout_buf.clear()
    route_point_buf.clear()
    activity_buf.clear()

    logger.debug("Flushed batch to database")
