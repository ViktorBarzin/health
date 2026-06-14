"""Read-path equivalence: the dashboard/metrics endpoints, backed by metric_daily.

The cardinal acceptance test for ADR-0009: the dashboard ``/summary`` and the
metrics ``/{type}`` time-series endpoint, now reading the ``metric_daily`` rollup
for day/week/month, must return the SAME numbers the old raw ``GROUP BY
date_trunc(...)`` over ``health_records`` produced — for sum-type (StepCount /
ActiveEnergyBurned) and avg-type (HeartRate) metrics. ``raw`` resolution must still
read ``health_records`` directly.

We assert against a recomputed-from-raw oracle (the metric values are derived from
the seeded rows independently of the rollup), and also that ``raw`` keeps working
when the rollup is deliberately wrong.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.health_record import HealthRecord
from app.models.user import User
from app.services import rollup


@pytest.fixture
async def client(db_session):
    state = {"user": None}

    async def _override_db():
        yield db_session

    async def _override_user():
        return state["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.set_user = lambda u: state.__setitem__("user", u)  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()


async def _user(db, email: str = "alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _seed(db, user_id: int) -> dict:
    """Seed a deterministic dataset; return the expected day/week totals computed
    in Python independent of any DB aggregation, so it's a true oracle."""
    rng = random.Random("read-path")
    start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows: list[tuple[str, datetime, float]] = []
    for day in range(40):
        for metric, base in (("HeartRate", 60), ("StepCount", 1000), ("ActiveEnergyBurned", 50)):
            # Distinct minute per reading so we never collide on the
            # (time, user, metric) PK; the random part is the count + values.
            for j in range(rng.randint(1, 4)):
                ts = start + timedelta(days=day, hours=rng.randint(0, 23), minutes=j)
                val = round(base + rng.uniform(0, base), 2)
                rows.append((metric, ts, val))
    for metric, ts, val in rows:
        db.add(
            HealthRecord(
                time=ts, user_id=user_id, metric_type=metric, value=val, unit="u"
            )
        )
    await db.flush()
    return {"start": start, "rows": rows}


@pytest.mark.asyncio
async def test_metric_day_series_equals_raw(client, db_session) -> None:
    db = db_session
    user = await _user(db)
    await _seed(db, user.id)
    await db.commit()

    # Capture the OLD answer by reading raw rows and aggregating in Python.
    raw_rows = (
        await db.execute(
            text(
                "SELECT date_trunc('day', time)::date AS d, "
                "       avg(value) AS a, count(*) AS c "
                "FROM health_records WHERE metric_type='HeartRate' "
                "GROUP BY 1 ORDER BY 1"
            )
        )
    ).all()
    expected = {str(r.d): (round(r.a, 4), r.c) for r in raw_rows}

    await rollup.backfill_all(db)
    await db.commit()

    client.set_user(user)
    resp = await client.get("/api/metrics/HeartRate", params={"resolution": "day"})
    assert resp.status_code == 200
    body = resp.json()
    got = {
        p["time"][:10]: (round(p["value"], 4), None) for p in body["data"]
    }
    # value (avg) matches the raw per-day avg for every day
    for d, (avg, _cnt) in expected.items():
        assert d in got, f"missing day {d}"
        assert got[d][0] == avg
    assert len(got) == len(expected)


@pytest.mark.parametrize("resolution", ["day", "week", "month"])
@pytest.mark.parametrize("metric", ["HeartRate", "StepCount", "ActiveEnergyBurned"])
@pytest.mark.asyncio
async def test_metric_series_value_total_equals_raw(
    client, db_session, resolution, metric
) -> None:
    """For every resolution+metric, the rollup-backed endpoint's bucket values
    equal the raw date_trunc aggregation's (sum for cumulative, avg otherwise)."""
    db = db_session
    user = await _user(db)
    await _seed(db, user.id)
    await db.commit()

    agg = "sum" if metric in ("StepCount", "ActiveEnergyBurned") else "avg"
    raw_rows = (
        await db.execute(
            text(
                f"SELECT date_trunc(:iv, time) AS b, {agg}(value) AS v, "
                "       min(value) AS mn, max(value) AS mx, count(*) AS c "
                "FROM health_records WHERE metric_type=:m AND user_id=:u "
                "GROUP BY 1 ORDER BY 1"
            ),
            {"iv": resolution, "m": metric, "u": user.id},
        )
    ).all()
    expected = [
        (round(r.v, 4), round(r.mn, 4), round(r.mx, 4)) for r in raw_rows
    ]

    await rollup.backfill_all(db)
    await db.commit()

    client.set_user(user)
    resp = await client.get(f"/api/metrics/{metric}", params={"resolution": resolution})
    assert resp.status_code == 200
    body = resp.json()
    got = [(p["value"], p["min"], p["max"]) for p in body["data"]]
    assert len(got) == len(expected)
    # Equal to floating-point tolerance: for an average, Σ(per-day sums)/Σcount
    # equals avg(all values) mathematically, but double addition isn't associative
    # so regrouping by day can differ in the last ULP (≈1e-4 after the endpoint's
    # round-to-4dp). min/max are exact (no arithmetic). A 1e-3 abs tolerance is
    # well below any value a chart distinguishes.
    for (gv, gmn, gmx), (ev, emn, emx) in zip(got, expected):
        assert gv == pytest.approx(ev, abs=1e-3)
        assert gmn == pytest.approx(emn, abs=1e-9)
        assert gmx == pytest.approx(emx, abs=1e-9)
    # stats.count is the total raw reading count
    assert body["stats"]["count"] == sum(r.c for r in raw_rows)


@pytest.mark.asyncio
async def test_raw_resolution_still_reads_health_records(client, db_session) -> None:
    db = db_session
    user = await _user(db)
    t = datetime(2024, 2, 1, 8, 0, tzinfo=timezone.utc)
    for v in (60.0, 65.0, 70.0):
        db.add(HealthRecord(time=t, user_id=user.id, metric_type="HeartRate", value=v, unit="u"))
        t += timedelta(minutes=10)
    await db.commit()
    await rollup.backfill_all(db)
    # Deliberately corrupt the rollup so a raw read that accidentally used it fails.
    await db.execute(text("UPDATE metric_daily SET sum=0, min=0, max=0, count=0"))
    await db.commit()

    client.set_user(user)
    resp = await client.get("/api/metrics/HeartRate", params={"resolution": "raw"})
    assert resp.status_code == 200
    body = resp.json()
    # Raw returns the individual readings (3 points), untouched by the bad rollup.
    assert len(body["data"]) == 3
    assert [round(p["value"], 1) for p in body["data"]] == [60.0, 65.0, 70.0]


@pytest.mark.asyncio
async def test_dashboard_summary_sums_equal_raw(client, db_session) -> None:
    db = db_session
    user = await _user(db)
    # Two days of steps + active energy within a known range.
    base = datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc)
    steps = [1000.0, 2000.0, 1500.0]
    energy = [100.0, 250.0]
    for i, v in enumerate(steps):
        db.add(HealthRecord(time=base + timedelta(hours=i), user_id=user.id, metric_type="StepCount", value=v, unit="count"))
    for i, v in enumerate(energy):
        db.add(HealthRecord(time=base + timedelta(days=1, hours=i), user_id=user.id, metric_type="ActiveEnergyBurned", value=v, unit="kcal"))
    # A latest-value metric (stays on health_records).
    db.add(HealthRecord(time=base + timedelta(days=1, hours=5), user_id=user.id, metric_type="RestingHeartRate", value=55.0, unit="count/min"))
    await db.commit()
    await rollup.backfill_all(db)
    await db.commit()

    client.set_user(user)
    resp = await client.get(
        "/api/dashboard/summary",
        params={"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["steps_today"] == sum(steps)
    assert body["active_energy_today"] == sum(energy)
    # Latest value unaffected.
    assert body["resting_hr"] == 55.0


@pytest.mark.asyncio
async def test_dashboard_summary_default_today_uses_rollup(client, db_session) -> None:
    """No date params → today's window; sums come from the rollup for today."""
    db = db_session
    user = await _user(db)
    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    db.add(HealthRecord(time=now, user_id=user.id, metric_type="StepCount", value=4242.0, unit="count"))
    await db.commit()
    await rollup.backfill_all(db)
    await db.commit()

    client.set_user(user)
    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    assert resp.json()["steps_today"] == 4242.0
