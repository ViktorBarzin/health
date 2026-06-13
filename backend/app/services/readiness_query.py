"""Readiness query layer — binds the pure Readiness core to a user's metrics.

The DB-touching glue for the Readiness signal (#14), mirroring
:mod:`app.services.recommendation_query` / :mod:`app.services.analytics`: the
maths lives in the pure core (:mod:`app.services.readiness`); this module only
fetches the right metric rows, reduces them to one **daily** value per metric
over a trailing window, and feeds them in. ``now`` is injected by the caller (the
route passes request time) so the binding stays as deterministic as the core.

Where the metrics come from (Apple Health vocabulary)
=====================================================
* **HRV** — ``health_records`` rows with ``metric_type =
  'HeartRateVariabilitySDNN'`` (ms). Apple records several intraday samples; we
  take the **daily mean** so one busy measurement day doesn't dominate.
* **Resting heart rate** — ``health_records`` rows with ``metric_type =
  'RestingHeartRate'`` (bpm), daily mean (usually one/day already).
* **Sleep** — ``category_records`` with ``category_type = 'SleepAnalysis'`` and
  an ``%Asleep%`` value; the asleep intervals are summed into **hours per night**
  bucketed by the interval's end day, exactly the dashboard's sleep aggregation.

The most-recent daily value of each series is "today"; the earlier days form the
trailing **baseline** the pure core compares against. The window
(:data:`_BASELINE_WINDOW_DAYS`) is wide enough for a stable personal baseline but
recent enough to track fitness changes — 28 days, a standard 4-week trend window.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.services.readiness import (
    MetricSample,
    Readiness,
    ReadinessInputs,
    compute_readiness,
)

# Apple Health metric_type / category values for the three Readiness inputs.
_HRV_METRIC = "HeartRateVariabilitySDNN"
_RHR_METRIC = "RestingHeartRate"
_SLEEP_CATEGORY = "SleepAnalysis"
_SLEEP_ASLEEP_PATTERN = "%Asleep%"

#: Trailing window for the personal baseline — 28 days (4 weeks): a stable
#: baseline that still tracks longer-term fitness changes.
_BASELINE_WINDOW_DAYS = 28


async def _daily_metric_series(
    db: AsyncSession,
    user_id: int,
    metric_type: str,
    *,
    now: dt.datetime,
) -> list[MetricSample]:
    """One mean value per UTC day for a ``health_records`` metric over the window.

    Returns ascending-by-day samples (anchored at each day's start) so the pure
    core sees the most-recent day last. A daily mean smooths Apple's multiple
    intraday samples into a single "that day's value".
    """
    window_start = now - dt.timedelta(days=_BASELINE_WINDOW_DAYS)
    day = func.date_trunc("day", HealthRecord.time)
    stmt = (
        select(day.label("bucket"), func.avg(HealthRecord.value).label("value"))
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric_type,
            HealthRecord.time >= window_start,
            HealthRecord.time <= now,
        )
        .group_by("bucket")
        .order_by("bucket")
    )
    rows = (await db.execute(stmt)).all()
    return [MetricSample(at=r.bucket, value=float(r.value)) for r in rows]


async def _daily_sleep_series(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> list[MetricSample]:
    """Hours asleep per night over the window (summed asleep intervals by end day).

    Mirrors the dashboard's sleep aggregation: sum ``end_time − time`` over
    ``%Asleep%`` ``SleepAnalysis`` intervals, bucketed by the night's end day.
    Ascending by day.
    """
    window_start = now - dt.timedelta(days=_BASELINE_WINDOW_DAYS)
    anchor = func.coalesce(CategoryRecord.end_time, CategoryRecord.time)
    hours = func.extract("epoch", anchor - CategoryRecord.time) / 3600.0
    bucket = func.date_trunc("day", anchor)
    stmt = (
        select(bucket.label("bucket"), func.sum(hours).label("hours"))
        .where(
            CategoryRecord.user_id == user_id,
            CategoryRecord.category_type == _SLEEP_CATEGORY,
            CategoryRecord.value.like(_SLEEP_ASLEEP_PATTERN),
            CategoryRecord.end_time.is_not(None),
            anchor >= window_start,
            anchor <= now,
        )
        .group_by("bucket")
        .order_by("bucket")
    )
    rows = (await db.execute(stmt)).all()
    return [MetricSample(at=r.bucket, value=float(r.hours)) for r in rows]


async def readiness_inputs_for_user(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> ReadinessInputs:
    """Assemble the user's HRV / resting-HR / sleep daily series for the window."""
    hrv = await _daily_metric_series(db, user_id, _HRV_METRIC, now=now)
    rhr = await _daily_metric_series(db, user_id, _RHR_METRIC, now=now)
    sleep = await _daily_sleep_series(db, user_id, now=now)
    return ReadinessInputs(hrv=hrv, resting_hr=rhr, sleep_hours=sleep)


async def readiness_for_user(
    db: AsyncSession, user_id: int, *, now: dt.datetime
) -> Readiness:
    """Today's Readiness for a user — fetch their metric series, run the core.

    ``now`` is injected so a fixed DB state yields a fixed signal. Returns the
    pure core's :class:`~app.services.readiness.Readiness` (an
    ``insufficient_data`` result when the user has no usable biometric history).
    """
    inputs = await readiness_inputs_for_user(db, user_id, now=now)
    return compute_readiness(inputs, now=now)


async def recent_daily_readiness(
    db: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    days: int,
) -> list[float | None]:
    """Readiness for each of the last ``days`` days (most-recent last).

    Used by the early-deload trigger: it recomputes Readiness "as of" each day's
    morning over the trailing ``days`` window, so a sustained low stretch can be
    detected. ``None`` for a day with no usable signal. Pulls the full metric
    series once, then evaluates the pure core per day against the data available
    up to that day (no extra queries per day).
    """
    inputs = await readiness_inputs_for_user(db, user_id, now=now)
    out: list[float | None] = []
    for back in range(days - 1, -1, -1):
        as_of = now - dt.timedelta(days=back)
        # Only samples on/before this day's evaluation instant are "known" then.
        sliced = ReadinessInputs(
            hrv=[s for s in inputs.hrv if s.at <= as_of],
            resting_hr=[s for s in inputs.resting_hr if s.at <= as_of],
            sleep_hours=[s for s in inputs.sleep_hours if s.at <= as_of],
        )
        result = compute_readiness(sliced, now=as_of)
        out.append(result.score)
    return out
