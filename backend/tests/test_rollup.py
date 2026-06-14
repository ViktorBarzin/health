"""Daily metric-rollup service (ADR-0009): backfill, idempotency, recompute, read.

End-to-end over real Postgres. The cardinal property is **rollup answers == raw
answers**: the values derived from ``metric_daily`` must equal the values the old
``GROUP BY date_trunc(...)`` over ``health_records`` produced, for both sum-type
(StepCount/ActiveEnergyBurned) and avg-type (HeartRate) metrics, across
day/week/month. Everything else (gating, targeted recompute after ingest) protects
that property under churn.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.models.health_record import HealthRecord
from app.models.metric_daily import MetricDaily
from app.models.user import User
from app.services import rollup


async def _user(db, email: str = "alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _add(
    db,
    *,
    user_id: int,
    metric_type: str,
    time: datetime,
    value: float,
    unit: str = "count",
) -> None:
    db.add(
        HealthRecord(
            time=time,
            user_id=user_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
        )
    )


def _bucketed_keys(rows: list[HealthRecord]) -> set[tuple[int, str, object]]:
    """The (user, metric, UTC-day) keys a set of raw rows touches."""
    return {
        (r.user_id, r.metric_type, r.time.astimezone(timezone.utc).date())
        for r in rows
    }


# --------------------------------------------------------------------------- #
# Backfill correctness: rollup count/sum/min/max == raw aggregation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_backfill_matches_raw_aggregation(db_session) -> None:
    db = db_session
    user = await _user(db)
    # Two days of HeartRate readings with known stats.
    d1 = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    for v in (60.0, 70.0, 80.0):  # day 1: count 3, sum 210, min 60, max 80
        await _add(db, user_id=user.id, metric_type="HeartRate", time=d1, value=v, unit="count/min")
        d1 += timedelta(hours=1)
    d2 = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)
    for v in (90.0, 100.0):  # day 2: count 2, sum 190, min 90, max 100
        await _add(db, user_id=user.id, metric_type="HeartRate", time=d2, value=v, unit="count/min")
        d2 += timedelta(hours=1)
    await db.commit()

    await rollup.backfill_all(db)
    await db.commit()

    rows = (
        await db.execute(
            select(MetricDaily)
            .where(MetricDaily.user_id == user.id)
            .order_by(MetricDaily.day)
        )
    ).scalars().all()
    assert len(rows) == 2
    r1, r2 = rows
    assert (r1.count, r1.sum, r1.min, r1.max) == (3, 210.0, 60.0, 80.0)
    assert r1.unit == "count/min"
    assert (r2.count, r2.sum, r2.min, r2.max) == (2, 190.0, 90.0, 100.0)


@pytest.mark.asyncio
async def test_backfill_separates_user_and_metric(db_session) -> None:
    db = db_session
    alice = await _user(db, "alice@example.com")
    bob = await _user(db, "bob@example.com")
    t = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    await _add(db, user_id=alice.id, metric_type="HeartRate", time=t, value=60.0)
    await _add(db, user_id=alice.id, metric_type="StepCount", time=t, value=1000.0)
    await _add(db, user_id=bob.id, metric_type="HeartRate", time=t, value=80.0)
    await db.commit()

    await rollup.backfill_all(db)
    await db.commit()

    rows = (await db.execute(select(MetricDaily))).scalars().all()
    keyed = {(r.user_id, r.metric_type): r for r in rows}
    assert len(rows) == 3
    assert keyed[(alice.id, "HeartRate")].sum == 60.0
    assert keyed[(alice.id, "StepCount")].sum == 1000.0
    assert keyed[(bob.id, "HeartRate")].sum == 80.0


# --------------------------------------------------------------------------- #
# Idempotency + gating
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_gated(db_session) -> None:
    db = db_session
    user = await _user(db)
    t = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    await _add(db, user_id=user.id, metric_type="HeartRate", time=t, value=60.0)
    await db.commit()

    res1 = await rollup.backfill_all(db)
    await db.commit()
    assert res1.populated == 1
    assert res1.skipped is False

    # A second run with the table already populated must SKIP — it must not
    # re-scan health_records (the whole point of the gate). Same rows, no dupes.
    res2 = await rollup.backfill_all(db)
    await db.commit()
    assert res2.skipped is True
    rows = (await db.execute(select(MetricDaily))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_rebuild_forces_full_recompute(db_session) -> None:
    db = db_session
    user = await _user(db)
    t = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    await _add(db, user_id=user.id, metric_type="HeartRate", time=t, value=60.0)
    await db.commit()
    await rollup.backfill_all(db)
    await db.commit()

    # Poison the rollup row to simulate drift, then force a rebuild.
    await db.execute(
        text("UPDATE metric_daily SET sum = 999, max = 999")
    )
    await db.commit()

    res = await rollup.backfill_all(db, rebuild=True)
    await db.commit()
    assert res.skipped is False
    row = (await db.execute(select(MetricDaily))).scalar_one()
    assert row.sum == 60.0  # rebuilt from the raw truth, drift gone
    assert row.max == 60.0


# --------------------------------------------------------------------------- #
# Targeted recompute (the ingest hook primitive)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_recompute_buckets_upserts_only_targeted_keys(db_session) -> None:
    db = db_session
    user = await _user(db)
    day_a = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    day_b = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)
    await _add(db, user_id=user.id, metric_type="HeartRate", time=day_a, value=60.0)
    await _add(db, user_id=user.id, metric_type="HeartRate", time=day_b, value=90.0)
    await db.commit()
    await rollup.backfill_all(db)
    await db.commit()

    # New reading lands on day_a only; recompute that bucket alone.
    await _add(db, user_id=user.id, metric_type="HeartRate", time=day_a + timedelta(hours=1), value=80.0)
    await db.commit()
    await rollup.recompute_buckets(
        db, [(user.id, "HeartRate", day_a.date())]
    )
    await db.commit()

    rows = {
        r.day: r
        for r in (await db.execute(select(MetricDaily))).scalars().all()
    }
    assert rows[day_a.date()].count == 2
    assert rows[day_a.date()].sum == 140.0
    # day_b untouched.
    assert rows[day_b.date()].count == 1
    assert rows[day_b.date()].sum == 90.0


@pytest.mark.asyncio
async def test_recompute_deletes_bucket_when_no_rows_remain(db_session) -> None:
    db = db_session
    user = await _user(db)
    t = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    await _add(db, user_id=user.id, metric_type="HeartRate", time=t, value=60.0)
    await db.commit()
    await rollup.backfill_all(db)
    await db.commit()

    # Delete all raw rows for the day, then recompute — the bucket must vanish.
    await db.execute(text("DELETE FROM health_records"))
    await db.commit()
    await rollup.recompute_buckets(db, [(user.id, "HeartRate", t.date())])
    await db.commit()

    rows = (await db.execute(select(MetricDaily))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_recompute_for_rows_extracts_keys(db_session) -> None:
    """The ingest-hook convenience: recompute from a batch's row dicts."""
    db = db_session
    user = await _user(db)
    t = datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
    rows = [
        {"user_id": user.id, "metric_type": "StepCount", "time": t, "value": 500.0, "unit": "count"},
        {"user_id": user.id, "metric_type": "StepCount", "time": t + timedelta(hours=2), "value": 700.0, "unit": "count"},
    ]
    for r in rows:
        await _add(db, user_id=r["user_id"], metric_type=r["metric_type"], time=r["time"], value=r["value"])
    await db.commit()

    await rollup.recompute_for_rows(db, rows)
    await db.commit()

    row = (await db.execute(select(MetricDaily))).scalar_one()
    assert row.metric_type == "StepCount"
    assert row.count == 2
    assert row.sum == 1200.0


# --------------------------------------------------------------------------- #
# CARDINAL: rollup-derived series == raw-aggregated series (day/week/month)
# --------------------------------------------------------------------------- #


async def _raw_series(db, user_id, metric_type, interval, aggregate):
    """The OLD raw-aggregation path, reproduced verbatim for the equivalence oracle."""
    bucket = func.date_trunc(interval, HealthRecord.time).label("bucket")
    agg = func.sum if aggregate == "sum" else func.avg
    stmt = (
        select(
            bucket,
            agg(HealthRecord.value).label("v"),
            func.min(HealthRecord.value).label("mn"),
            func.max(HealthRecord.value).label("mx"),
            func.count().label("cnt"),
        )
        .where(
            HealthRecord.user_id == user_id,
            HealthRecord.metric_type == metric_type,
        )
        .group_by(text("1"))
        .order_by(text("1"))
    )
    rows = (await db.execute(stmt)).all()
    return [(r.bucket, r.v, r.mn, r.mx, r.cnt) for r in rows]


@pytest.mark.parametrize("interval", ["day", "week", "month"])
@pytest.mark.parametrize(
    "metric_type,aggregate",
    [
        ("HeartRate", "avg"),
        ("StepCount", "sum"),
        ("ActiveEnergyBurned", "sum"),
    ],
)
@pytest.mark.asyncio
async def test_rollup_series_equals_raw_series(
    db_session, interval, metric_type, aggregate
) -> None:
    db = db_session
    user = await _user(db)
    rng = random.Random(f"{interval}-{metric_type}")

    # ~90 days of irregular multi-per-day readings spanning month + week boundaries.
    # Timestamps are made unique per reading (distinct minute) so we never collide
    # on the health_records (time, user, metric) PK — the random part is the count
    # per day (some days empty) and the values.
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    for day in range(90):
        n = rng.randint(0, 5)  # some days empty
        for j in range(n):
            ts = start + timedelta(days=day, hours=rng.randint(0, 23), minutes=j)
            await _add(
                db,
                user_id=user.id,
                metric_type=metric_type,
                time=ts,
                value=round(rng.uniform(40, 200), 2),
            )
    await db.commit()

    await rollup.backfill_all(db)
    await db.commit()

    expected = await _raw_series(db, user.id, metric_type, interval, aggregate)
    actual = await rollup.fetch_rollup_series(
        db,
        user_id=user.id,
        metric_type=metric_type,
        interval=interval,
        aggregate=aggregate,
    )
    assert len(actual) == len(expected)
    assert len(actual) > 0  # the dataset actually exercised the path
    for p, (e_bucket, e_val, e_min, e_max, e_cnt) in zip(actual, expected):
        assert p["bucket"] == e_bucket  # same bucket instant (the re-bucket math)
        assert p["count"] == e_cnt
        # min/max are exact; the value (sum or Σsum/Σcount) is equal to float
        # tolerance — double addition isn't associative across the day regroup.
        assert p["min"] == pytest.approx(e_min, abs=1e-9)
        assert p["max"] == pytest.approx(e_max, abs=1e-9)
        assert p["value"] == pytest.approx(e_val, abs=1e-3)
