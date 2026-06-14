"""Daily metric rollups — maintain & read ``metric_daily`` (ADR-0009).

The dashboard/metrics read path used to aggregate raw ``health_records`` on every
wide-window load (a ``GROUP BY date_trunc('day', time)`` over ~1M HeartRate rows
spills to disk → ~1.6 s, several per load). ADR-0009 fixes that by keeping a daily
rollup (:class:`~app.models.metric_daily.MetricDaily`, one row per
``(user_id, metric_type, day)`` with ``count`` / ``sum`` / ``min`` / ``max``) and
reading it instead. This module owns the rollup's whole lifecycle:

* :func:`recompute_buckets` — the primitive: re-derive a specific set of
  ``(user, metric, day)`` buckets from ``health_records`` (delete-then-reinsert,
  so it's idempotent and self-healing; a bucket with no remaining raw rows is
  removed). This is what the **post-ingest hooks** call with only the keys a batch
  touched — a targeted recompute, never a full rebuild.
* :func:`recompute_for_rows` — convenience over :func:`recompute_buckets` that
  extracts the distinct ``(user, metric, day)`` keys from a list of just-inserted
  ``health_records`` row dicts. The Apple Health XML import and the Connector sync
  call this after a batch lands.
* :func:`backfill_all` — the **one-time backfill / rebuild**: a single
  ``GROUP BY user_id, metric_type, date_trunc('day', time)`` over every existing
  row. **Gated**: it skips when ``metric_daily`` is already populated (a cheap
  ``LIMIT 1`` probe) so a normal pod restart does NOT re-scan the ~6.6M-row table.
  Pass ``rebuild=True`` (or run ``python -m app.services.rollup --rebuild`` /
  ``ROLLUP_REBUILD=1``) to truncate and rebuild from scratch for recovery.
* :func:`fetch_rollup_series` — the read helper the dashboard/metrics endpoints use
  for day/week/month: it re-buckets the daily rows with the **same** ``date_trunc``
  the raw path used (``date_trunc(interval, day::timestamptz)``), so rollup-derived
  answers equal the old raw-aggregation answers exactly.

**Day semantics.** ``day`` is the UTC calendar day: ``date_trunc('day', time)::date``.
With the DB session in UTC (prod + tests), this is the same day the raw path's
``date_trunc('day', time)`` lands in, and re-bucketing ``day::timestamptz`` to
week/month reproduces the raw path's bucket instants — the equivalence the tests
pin. Only ``health_records`` is rolled up; ``category_records`` stay query-time
(ADR-0009).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timezone as _tz

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_UTC = _tz.utc

# Resolutions the rollup serves; ``raw`` is deliberately NOT here (it reads
# health_records directly, capped).
_ROLLUP_INTERVALS = ("day", "week", "month")


@dataclass(frozen=True)
class BackfillResult:
    """Outcome of a :func:`backfill_all` run, for logging and tests."""

    populated: int  # rows written (0 when skipped)
    skipped: bool  # True when the gate short-circuited an already-populated table


# --------------------------------------------------------------------------- #
# Targeted recompute (the ingest-hook primitive)
# --------------------------------------------------------------------------- #


async def recompute_buckets(
    session: AsyncSession,
    keys: list[tuple[int, str, date_type]],
) -> int:
    """Re-derive the given ``(user_id, metric_type, day)`` buckets from raw rows.

    Delete-then-reinsert per key so the result is idempotent and self-healing: a
    bucket whose raw rows all went away is removed (no stale row), and a bucket
    that gained rows reflects the full current truth (not a delta). Flushes within
    the caller's transaction; the caller commits.

    Targeted: only the supplied keys are touched — the rest of ``metric_daily`` is
    untouched. This is what the post-ingest hooks call with a batch's distinct keys.
    """
    if not keys:
        return 0

    # De-dup the keys (a batch hits the same (user, metric, day) many times).
    distinct = sorted(set(keys))

    # Build a VALUES list of the target keys as a CTE so the DELETE and the
    # re-aggregating INSERT both scope to exactly these (user, metric, day) tuples.
    # Parameterised positionally to stay clear of any injection.
    # Explicitly cast every VALUES component: a bare VALUES list gives the columns
    # no inferable type, so ``k.user_id = md.user_id`` would be ``text = integer``.
    params: dict[str, object] = {}
    value_rows = []
    for i, (uid, metric, day) in enumerate(distinct):
        params[f"u{i}"] = uid
        params[f"m{i}"] = metric
        params[f"d{i}"] = day
        value_rows.append(
            f"(CAST(:u{i} AS integer), CAST(:m{i} AS text), CAST(:d{i} AS date))"
        )
    values_sql = ", ".join(value_rows)

    # 1) Drop the target buckets.
    await session.execute(
        text(
            f"""
            DELETE FROM metric_daily md
            USING (VALUES {values_sql}) AS k(user_id, metric_type, day)
            WHERE md.user_id = k.user_id
              AND md.metric_type = k.metric_type
              AND md.day = k.day
            """
        ),
        params,
    )

    # 2) Re-insert fresh aggregates for any target buckets that still have raw rows.
    #    A bucket with zero remaining rows simply produces no row (correctly gone).
    await session.execute(
        text(
            f"""
            INSERT INTO metric_daily
                (user_id, metric_type, day, count, sum, min, max, unit)
            SELECT hr.user_id,
                   hr.metric_type,
                   date_trunc('day', hr.time)::date AS day,
                   count(*),
                   sum(hr.value),
                   min(hr.value),
                   max(hr.value),
                   max(hr.unit)
            FROM health_records hr
            JOIN (VALUES {values_sql}) AS k(user_id, metric_type, day)
              ON hr.user_id = k.user_id
             AND hr.metric_type = k.metric_type
             AND date_trunc('day', hr.time)::date = k.day
            GROUP BY hr.user_id, hr.metric_type, date_trunc('day', hr.time)::date
            """
        ),
        params,
    )
    return len(distinct)


def _keys_from_rows(
    rows: list[dict],
) -> list[tuple[int, str, date_type]]:
    """Extract distinct ``(user_id, metric_type, UTC-day)`` keys from row dicts.

    Rows are the same dicts handed to :func:`app.services.dedup.bulk_insert_health_records`
    (``user_id`` / ``metric_type`` / ``time``). The day is the UTC calendar day to
    match the SQL ``date_trunc('day', time)::date``.
    """
    keys: set[tuple[int, str, date_type]] = set()
    for r in rows:
        ts = r["time"]
        # Normalise to UTC before taking the date so it matches date_trunc in a
        # UTC session. A naive datetime is assumed already-UTC (the parsers emit
        # tz-aware, but be defensive).
        if ts.tzinfo is not None:
            day = ts.astimezone(_UTC).date()
        else:
            day = ts.date()
        keys.add((r["user_id"], r["metric_type"], day))
    return list(keys)


async def recompute_for_rows(session: AsyncSession, rows: list[dict]) -> int:
    """Recompute rollups for the buckets a batch of health_records rows touched.

    The post-ingest hook entry point: pass the row dicts that were just inserted;
    only their distinct ``(user, metric, day)`` buckets are recomputed.
    """
    return await recompute_buckets(session, _keys_from_rows(rows))


# --------------------------------------------------------------------------- #
# One-time backfill / full rebuild (gated)
# --------------------------------------------------------------------------- #


async def _is_populated(session: AsyncSession) -> bool:
    """Cheap probe: does ``metric_daily`` already have at least one row?"""
    row = (await session.execute(text("SELECT 1 FROM metric_daily LIMIT 1"))).first()
    return row is not None


async def backfill_all(
    session: AsyncSession, *, rebuild: bool = False
) -> BackfillResult:
    """Populate ``metric_daily`` from all of ``health_records`` in one ``GROUP BY``.

    **Gated** to be cheap to re-run: if the table is already populated and
    ``rebuild`` is False, it returns immediately WITHOUT scanning ``health_records``
    (so a normal pod boot doesn't re-aggregate the ~6.6M-row table). Pass
    ``rebuild=True`` to TRUNCATE and rebuild from scratch (the documented recovery
    path). Flushes within the caller's transaction; the caller commits.
    """
    if not rebuild and await _is_populated(session):
        logger.info("metric_daily already populated; skipping backfill (use rebuild to force)")
        return BackfillResult(populated=0, skipped=True)

    if rebuild:
        # TRUNCATE is fast and resets the table for a clean rebuild.
        await session.execute(text("TRUNCATE TABLE metric_daily"))

    result = await session.execute(
        text(
            """
            INSERT INTO metric_daily
                (user_id, metric_type, day, count, sum, min, max, unit)
            SELECT user_id,
                   metric_type,
                   date_trunc('day', time)::date AS day,
                   count(*),
                   sum(value),
                   min(value),
                   max(value),
                   max(unit)
            FROM health_records
            GROUP BY user_id, metric_type, date_trunc('day', time)::date
            ON CONFLICT (user_id, metric_type, day) DO UPDATE
                SET count = EXCLUDED.count,
                    sum = EXCLUDED.sum,
                    min = EXCLUDED.min,
                    max = EXCLUDED.max,
                    unit = EXCLUDED.unit
            """
        )
    )
    populated = result.rowcount if result.rowcount is not None else 0
    logger.info("metric_daily backfill complete: %d buckets (rebuild=%s)", populated, rebuild)
    return BackfillResult(populated=populated, skipped=False)


# --------------------------------------------------------------------------- #
# Read helper (the dashboard/metrics day/week/month path)
# --------------------------------------------------------------------------- #


async def fetch_rollup_series(
    session: AsyncSession,
    *,
    user_id: int,
    metric_type: str,
    interval: str,
    aggregate: str,
    start: date_type | None = None,
    end: date_type | None = None,
) -> list[dict]:
    """Read a day/week/month series for one metric from ``metric_daily``.

    Re-buckets the daily rows to ``interval`` with the **same** ``date_trunc`` the
    raw path used (``date_trunc(interval, day::timestamptz)``), so the result equals
    the old raw aggregation exactly. ``aggregate`` is ``"sum"`` for cumulative
    metrics (value = Σsum) or ``"avg"`` for the rest (value = Σsum / Σcount); ``min``
    is min(min), ``max`` is max(max), ``count`` is Σcount (the raw reading count).

    ``start`` / ``end`` are inclusive day bounds (a Python ``date``); ``None`` means
    unbounded. Returns dicts ``{bucket: datetime, value, min, max, count}`` ordered
    by bucket — the shape the endpoints adapt into ``MetricDataPoint``.
    """
    if interval not in _ROLLUP_INTERVALS:
        raise ValueError(f"unsupported rollup interval: {interval!r}")
    if aggregate not in ("sum", "avg"):
        raise ValueError(f"unsupported aggregate: {aggregate!r}")

    # value: Σsum for cumulative; Σsum/Σcount for an average (weighted by reading
    # count, matching avg(value) over the raw rows).
    value_expr = (
        "sum(sum)" if aggregate == "sum" else "sum(sum) / NULLIF(sum(count), 0)"
    )
    # date_trunc on a timestamptz reproduces the raw path's bucket instant; the
    # day (a DATE) is cast to timestamptz (UTC midnight in a UTC session). The
    # interval is bound but pre-validated against _ROLLUP_INTERVALS above.
    bucket_expr = "date_trunc(:interval, day::timestamptz)"

    where = ["user_id = :user_id", "metric_type = :metric_type"]
    params: dict[str, object] = {
        "interval": interval,
        "user_id": user_id,
        "metric_type": metric_type,
    }
    if start is not None:
        where.append("day >= :start")
        params["start"] = start
    if end is not None:
        where.append("day <= :end")
        params["end"] = end

    stmt = text(
        f"""
        SELECT {bucket_expr} AS bucket,
               {value_expr} AS value,
               min(min) AS min,
               max(max) AS max,
               sum(count) AS count
        FROM metric_daily
        WHERE {' AND '.join(where)}
        GROUP BY 1
        ORDER BY 1
        """
    )
    rows = (await session.execute(stmt, params)).all()
    return [
        {
            "bucket": r.bucket,
            "value": float(r.value),
            "min": float(r.min),
            "max": float(r.max),
            "count": int(r.count),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# CLI entry point (entrypoint.sh + manual recovery), mirroring the seeds
# --------------------------------------------------------------------------- #


async def _main() -> None:
    from app.database import async_session

    rebuild = "--rebuild" in sys.argv or os.environ.get("ROLLUP_REBUILD") == "1"
    async with async_session() as session:
        result = await backfill_all(session, rebuild=rebuild)
        await session.commit()
    if result.skipped:
        print("metric_daily already populated; skipped (pass --rebuild to force).")
    else:
        print(f"metric_daily backfill complete: {result.populated} buckets (rebuild={rebuild}).")


if __name__ == "__main__":
    asyncio.run(_main())
