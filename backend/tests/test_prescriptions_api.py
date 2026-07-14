"""Prescription persistence (CONTEXT.md "Prescription"; ADR-0011; plan M4).

Every start path snapshots what it prescribed; the snapshot is immutable and
survives the user's edits (which overwrite the pre-filled Sets, not the
Prescription). Manual/empty Sessions have no Prescription — unmeasured, never
faked.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Muscle
from app.models.gym_profile import GymProfile
from app.models.prescription import Prescription, PrescriptionSource
from app.models.user import User

from tests.test_program_recommendation_api import _program
from tests.test_swap_exclusions_api import _exercise, _log_history


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


async def _prescriptions(db):
    return (await db.execute(select(Prescription))).scalars().all()


async def test_program_start_writes_labelled_prescription(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    await _log_history(db_session, alice, bench, weight=60.0, reps=8)
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    program = await _program(
        db_session,
        alice,
        days=[("Push Day", [Muscle.chest])],
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    client.set_user(alice)

    resp = await client.post("/api/recommendations/today/start")
    assert resp.status_code == 201

    rows = await _prescriptions(db_session)
    # One prescription for the started Session (the history Session has none).
    assert len(rows) == 1
    p = rows[0]
    assert p.source == PrescriptionSource.program
    assert p.program_id == program.id
    assert p.program_version == 1
    assert p.day_index == 0
    assert p.user_id == alice.id
    assert str(p.session_id) == resp.json()["id"]
    assert len(p.slots) == 1
    slot = p.slots[0]
    assert slot["exercise_id"] == str(bench.id)
    assert slot["muscle"] == "chest"
    assert slot["target_sets"] >= 1
    assert slot["target_reps"] >= 1


async def test_freestyle_start_writes_prescription(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    await _log_history(db_session, alice, bench)
    client.set_user(alice)

    resp = await client.post("/api/recommendations/freestyle/start", json={})
    assert resp.status_code == 201
    rows = await _prescriptions(db_session)
    assert len(rows) == 1
    assert rows[0].source == PrescriptionSource.freestyle
    assert rows[0].program_id is None
    assert rows[0].slots[0]["exercise_id"] == str(bench.id)
    assert rows[0].slots[0]["muscle"] is None  # freestyle slots are unlabelled


async def test_explicit_start_snapshots_what_was_sent(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    client.set_user(alice)

    resp = await client.post(
        "/api/recommendations/start",
        json={
            "exercises": [
                {
                    "exercise_id": str(bench.id),
                    "target_sets": 3,
                    "target_reps": 8,
                    "target_weight_kg": 62.5,
                }
            ]
        },
    )
    assert resp.status_code == 201
    rows = await _prescriptions(db_session)
    assert len(rows) == 1
    assert rows[0].source == PrescriptionSource.explicit
    assert rows[0].slots == [
        {
            "exercise_id": str(bench.id),
            "muscle": None,
            "target_sets": 3,
            "target_reps": 8,
            "target_weight_kg": 62.5,
        }
    ]


async def test_manual_session_has_no_prescription(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.post("/api/sessions/", json={})
    assert resp.status_code in (200, 201)
    assert await _prescriptions(db_session) == []
