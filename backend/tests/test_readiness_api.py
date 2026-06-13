"""Readiness API — GET /api/readiness, end-to-end over real Postgres.

The pure core's numeric behaviour is pinned in :mod:`tests.test_readiness`; here
we assert the WIRING: that the query layer reads HRV / resting-HR from
``health_records`` and sleep from ``category_records``, reduces them to daily
series, runs the core, and serves the score + components — and that a user with
no biometric history gets an honest ``insufficient_data`` result, scoped per
user.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.models.user import User

NOW = datetime.now(timezone.utc)


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


async def _metric(
    db, user: User, metric_type: str, *, days_ago: float, value: float
) -> None:
    db.add(
        HealthRecord(
            time=NOW - timedelta(days=days_ago),
            user_id=user.id,
            metric_type=metric_type,
            value=value,
            unit="x",
        )
    )


async def _sleep_night(db, user: User, *, days_ago: float, hours: float) -> None:
    start = NOW - timedelta(days=days_ago)
    db.add(
        CategoryRecord(
            time=start,
            user_id=user.id,
            category_type="SleepAnalysis",
            value="HKCategoryValueSleepAnalysisAsleepCore",
            end_time=start + timedelta(hours=hours),
        )
    )


async def _seed_baseline_hrv(db, user: User, *, recent: float) -> None:
    """14 baseline HRV days at 55ms plus a recent reading."""
    for d in range(2, 16):
        await _metric(db, user, "HeartRateVariabilitySDNN", days_ago=d, value=55.0)
    await _metric(db, user, "HeartRateVariabilitySDNN", days_ago=0.3, value=recent)


# --------------------------------------------------------------------------- #
# Insufficient data
# --------------------------------------------------------------------------- #


async def test_no_history_is_insufficient(client, db_session) -> None:
    user = await _user(db_session)
    client.set_user(user)
    resp = await client.get("/api/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient_data"] is True
    assert body["score"] is None


# --------------------------------------------------------------------------- #
# HRV drives the score; components are reported
# --------------------------------------------------------------------------- #


async def test_low_recent_hrv_reads_lower_than_baseline(client, db_session) -> None:
    user = await _user(db_session)
    await _seed_baseline_hrv(db_session, user, recent=30.0)
    await db_session.flush()
    client.set_user(user)
    resp = await client.get("/api/readiness")
    body = resp.json()
    assert body["insufficient_data"] is False
    assert body["score"] is not None
    # A recent HRV well below the 55ms baseline → below the neutral midpoint.
    assert body["score"] < 50.0
    metrics = {c["metric"] for c in body["components"]}
    assert "hrv" in metrics


async def test_high_recent_hrv_reads_above_baseline(client, db_session) -> None:
    user = await _user(db_session)
    await _seed_baseline_hrv(db_session, user, recent=80.0)
    await db_session.flush()
    client.set_user(user)
    resp = await client.get("/api/readiness")
    body = resp.json()
    assert body["score"] > 50.0


async def test_full_signal_combines_hrv_rhr_sleep(client, db_session) -> None:
    user = await _user(db_session)
    # Depressed HRV, elevated RHR, short sleep — all worse than baseline.
    for d in range(2, 16):
        await _metric(db_session, user, "HeartRateVariabilitySDNN", days_ago=d, value=60.0)
        await _metric(db_session, user, "RestingHeartRate", days_ago=d, value=55.0)
        await _sleep_night(db_session, user, days_ago=d, hours=7.5)
    await _metric(db_session, user, "HeartRateVariabilitySDNN", days_ago=0.3, value=35.0)
    await _metric(db_session, user, "RestingHeartRate", days_ago=0.3, value=68.0)
    await _sleep_night(db_session, user, days_ago=0.3, hours=4.5)
    await db_session.flush()
    client.set_user(user)
    resp = await client.get("/api/readiness")
    body = resp.json()
    assert body["score"] < 35.0
    assert body["band"] == "low"
    metrics = {c["metric"] for c in body["components"]}
    assert metrics == {"hrv", "resting_hr", "sleep_hours"}


# --------------------------------------------------------------------------- #
# Per-user scoping
# --------------------------------------------------------------------------- #


async def test_readiness_is_per_user(client, db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    # Only Alice has data; Bob is empty.
    await _seed_baseline_hrv(db_session, alice, recent=40.0)
    await db_session.flush()

    client.set_user(bob)
    bob_resp = (await client.get("/api/readiness")).json()
    assert bob_resp["insufficient_data"] is True

    client.set_user(alice)
    alice_resp = (await client.get("/api/readiness")).json()
    assert alice_resp["insufficient_data"] is False
