"""Apple Health push Connector (M7, ADR-0012) — bearer ingest + tokens.

The fully-automatic path: an iOS Shortcut (workout-end + morning automations)
POSTs the engine-critical samples to ``/api/ingest/apple`` with a per-user
bearer token. Contract pinned here:

- token lifecycle: created via the forward-auth settings API (plaintext shown
  ONCE, only a hash stored), listed with prefix + last-used, revocable —
  a revoked/garbage/missing token ⇒ 401, never a silent accept;
- the endpoint accepts BOTH the Shortcut-friendly CSV lines and JSON, maps
  Shortcut/HK type spellings onto the app's canonical metric types, converts
  units (lb→kg), maps sleep stages onto the HK ``Asleep*`` labels Readiness
  matches, lands workouts on the natural-key dedup, kcal→kJ;
- everything is idempotent (re-POST changes nothing) and rolled up
  (metric_daily updated for touched days) with DataSource + ImportBatch audit;
- junk lines are skipped and counted, never guessed at.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.category_record import CategoryRecord
from app.models.health_record import HealthRecord
from app.models.import_batch import ImportBatch
from app.models.ingest_token import IngestToken
from app.models.metric_daily import MetricDaily
from app.models.user import User
from app.models.workout import Workout


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


async def _user(db, email="alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _token_for(client, db, user) -> str:
    client.set_user(user)
    resp = await client.post("/api/ingest/tokens", json={"label": "iPhone"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["token"].startswith("hlth_")
    return body["token"]


CSV = """\
metric,HeartRateVariabilitySDNN,2026-07-14T07:00:00Z,42.5,ms
metric,Resting Heart Rate,2026-07-14T07:00:00Z,52,count/min
metric,Body Mass,2026-07-14T06:45:00Z,180,lb
sleep,2026-07-13T23:00:00Z,2026-07-14T06:30:00Z,Core
workout,Functional Strength Training,2026-07-14T18:00:00Z,2026-07-14T19:00:00Z,320,0
"""


# --------------------------------------------------------------------------- #
# Token lifecycle
# --------------------------------------------------------------------------- #


async def test_token_create_list_revoke(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)

    listed = (await client.get("/api/ingest/tokens")).json()
    assert len(listed) == 1
    assert listed[0]["label"] == "iPhone"
    assert listed[0]["prefix"] == token[:10]
    assert "token" not in listed[0]  # plaintext shown once, never again
    row = (await db_session.execute(select(IngestToken))).scalars().one()
    assert token not in (row.token_hash or "")  # only a hash is stored

    resp = await client.delete(f"/api/ingest/tokens/{listed[0]['id']}")
    assert resp.status_code == 204
    assert (await client.get("/api/ingest/tokens")).json() == []


async def test_ingest_rejects_missing_bad_or_revoked_token(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)

    assert (
        await client.post("/api/ingest/apple", content=CSV)
    ).status_code == 401
    assert (
        await client.post(
            "/api/ingest/apple",
            content=CSV,
            headers={"Authorization": "Bearer hlth_wrong"},
        )
    ).status_code == 401

    listed = (await client.get("/api/ingest/tokens")).json()
    await client.delete(f"/api/ingest/tokens/{listed[0]['id']}")
    assert (
        await client.post(
            "/api/ingest/apple",
            content=CSV,
            headers={"Authorization": f"Bearer {token}"},
        )
    ).status_code == 401


# --------------------------------------------------------------------------- #
# CSV ingest
# --------------------------------------------------------------------------- #


async def test_csv_ingest_lands_normalizes_and_rolls_up(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)

    resp = await client.post(
        "/api/ingest/apple",
        content=CSV,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/plain",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"metrics": 3, "sleep": 1, "workouts": 1, "skipped": 0}

    metrics = (await db_session.execute(select(HealthRecord))).scalars().all()
    by_type = {m.metric_type: m for m in metrics}
    # Shortcut spellings normalised onto the canonical types.
    assert set(by_type) == {
        "HeartRateVariabilitySDNN",
        "RestingHeartRate",
        "BodyMass",
    }
    assert by_type["HeartRateVariabilitySDNN"].value == 42.5
    # lb → kg conversion.
    assert abs(by_type["BodyMass"].value - 81.646) < 0.01
    assert by_type["BodyMass"].unit == "kg"

    sleep = (await db_session.execute(select(CategoryRecord))).scalars().one()
    assert sleep.category_type == "SleepAnalysis"
    assert "Asleep" in sleep.value  # the Readiness %Asleep% filter matches
    assert sleep.value_label == "Core"
    assert sleep.end_time is not None

    workout = (await db_session.execute(select(Workout))).scalars().one()
    assert workout.activity_type == "Functional Strength Training"
    assert workout.duration_sec == 3600.0
    assert abs(workout.total_energy_kj - 320 * 4.184) < 0.01

    # Rollups recomputed for the touched (user, metric, day) buckets.
    daily = (await db_session.execute(select(MetricDaily))).scalars().all()
    assert {d.metric_type for d in daily} == set(by_type)

    # Audit trail + token bookkeeping.
    batch = (await db_session.execute(select(ImportBatch))).scalars().one()
    assert batch.user_id == alice.id
    tok = (await db_session.execute(select(IngestToken))).scalars().one()
    assert tok.last_used_at is not None


async def test_ingest_is_idempotent(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "text/plain"}

    assert (await client.post("/api/ingest/apple", content=CSV, headers=headers)).status_code == 200
    assert (await client.post("/api/ingest/apple", content=CSV, headers=headers)).status_code == 200

    assert len((await db_session.execute(select(HealthRecord))).scalars().all()) == 3
    assert len((await db_session.execute(select(CategoryRecord))).scalars().all()) == 1
    assert len((await db_session.execute(select(Workout))).scalars().all()) == 1


async def test_junk_lines_are_skipped_and_counted(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)
    body = (
        "metric,SomeUnknownType,2026-07-14T07:00:00Z,1,ms\n"
        "not,even,close\n"
        "metric,BodyMass,not-a-date,80,kg\n"
        "\n"
        "metric,LeanBodyMass,2026-07-14T06:45:00Z,65.2,kg\n"
    )
    resp = await client.post(
        "/api/ingest/apple",
        content=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"metrics": 1, "sleep": 0, "workouts": 0, "skipped": 3}
    kept = (await db_session.execute(select(HealthRecord))).scalars().one()
    assert kept.metric_type == "LeanBodyMass"


# --------------------------------------------------------------------------- #
# JSON ingest
# --------------------------------------------------------------------------- #


async def test_json_body_is_equivalent(client, db_session) -> None:
    alice = await _user(db_session)
    token = await _token_for(client, db_session, alice)
    resp = await client.post(
        "/api/ingest/apple",
        json={
            "metrics": [
                {
                    "type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                    "time": "2026-07-14T07:00:00Z",
                    "value": 44.0,
                    "unit": "ms",
                }
            ],
            "sleep": [
                {
                    "start": "2026-07-13T23:10:00Z",
                    "end": "2026-07-14T06:20:00Z",
                    "stage": "Asleep",
                }
            ],
            "workouts": [
                {
                    "type": "Traditional Strength Training",
                    "start": "2026-07-14T18:00:00Z",
                    "end": "2026-07-14T18:45:00Z",
                    "energy_kcal": 250,
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"metrics": 1, "sleep": 1, "workouts": 1, "skipped": 0}
    hk = (await db_session.execute(select(HealthRecord))).scalars().one()
    assert hk.metric_type == "HeartRateVariabilitySDNN"  # HK identifier normalised
