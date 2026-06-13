"""Fitbod import API: preview (dry-run) + commit (idempotent write), per user.

- Preview parses + auto-matches and reports unmatched names; writes nothing.
- Commit writes Sessions/Sets idempotently using the user's resolutions.
- A bad (non-Fitbod) CSV is a clean 400, not a 500.
- Imports are scoped to the calling user.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise
from app.models.training_session import TrainingSession, TrainingSet
from app.models.user import User

HEADER = (
    "Date,Exercise,Reps,Weight(kg),Duration(s),Distance(m),"
    "Incline,Resistance,isWarmup,Note,multiplier"
)


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_exercise(db, name: str, *, user_id=None) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        source="free-exercise-db" if user_id is None else "custom",
    )
    db.add(ex)
    await db.flush()
    return ex


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


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #


async def test_preview_reports_matched_and_unresolved(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    client.set_user(user)

    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,55.0,0,0,0,0,false,,1.0",
    )
    resp = await client.post("/api/import/fitbod/preview", json={"csv_text": text})
    assert resp.status_code == 200
    body = resp.json()

    assert body["session_count"] == 1
    assert body["set_count"] == 3
    assert len(body["matched"]) == 1
    assert body["matched"][0]["fitbod_name"] == "Back Squat"
    assert body["matched"][0]["exercise_name"] == "Barbell Squat"
    assert len(body["unresolved"]) == 1
    assert body["unresolved"][0]["fitbod_name"] == "Mystery Machine"
    assert body["unresolved"][0]["set_count"] == 2


async def test_preview_writes_nothing(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    client.set_user(user)
    text = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")

    await client.post("/api/import/fitbod/preview", json={"csv_text": text})

    count = (
        await db_session.execute(select(func.count(TrainingSession.id)))
    ).scalar()
    assert count == 0


async def test_preview_bad_csv_is_400(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    client.set_user(user)
    resp = await client.post(
        "/api/import/fitbod/preview",
        json={"csv_text": "not,a,fitbod,file\n1,2,3,4\n"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #


async def test_commit_creates_sessions_and_sets(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    client.set_user(user)

    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,true,,1.0",
        "2021-12-27 10:00:00 +0000,Back Squat,5,102.5,0,0,0,0,false,,1.0",
    )
    resp = await client.post(
        "/api/import/fitbod/commit", json={"csv_text": text}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sessions_created"] == 1
    assert body["sets_created"] == 2
    assert body["batch_id"]

    count = (
        await db_session.execute(select(func.count(TrainingSet.id)))
    ).scalar()
    assert count == 2


async def test_commit_with_manual_resolution(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    custom = await _make_exercise(db_session, "My Machine", user_id=user.id)
    client.set_user(user)
    text = _csv(
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0"
    )
    resp = await client.post(
        "/api/import/fitbod/commit",
        json={
            "csv_text": text,
            "resolutions": {"Mystery Machine": str(custom.id)},
        },
    )
    assert resp.status_code == 201
    assert resp.json()["sets_created"] == 1

    s = (await db_session.execute(select(TrainingSet))).scalars().one()
    assert s.exercise_id == custom.id


async def test_commit_is_idempotent(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    client.set_user(user)
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Back Squat,5,102.5,0,0,0,0,false,,1.0",
    )

    first = (
        await client.post("/api/import/fitbod/commit", json={"csv_text": text})
    ).json()
    second = (
        await client.post("/api/import/fitbod/commit", json={"csv_text": text})
    ).json()

    assert first["sets_created"] == 2
    assert second["sets_created"] == 0
    count = (
        await db_session.execute(select(func.count(TrainingSet.id)))
    ).scalar()
    assert count == 2


async def test_imported_session_is_listed_for_user(client, db_session) -> None:
    """An imported Session shows up in the user's normal Sessions list."""
    user = await _make_user(db_session, "lifter@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    client.set_user(user)
    text = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")

    await client.post("/api/import/fitbod/commit", json={"csv_text": text})

    listed = (await client.get("/api/sessions/")).json()
    assert len(listed) == 1
    assert listed[0]["set_count"] == 1
    # Historical import → not active (ended_at set).
    assert listed[0]["is_active"] is False


async def test_commit_bad_csv_is_400(client, db_session) -> None:
    user = await _make_user(db_session, "lifter@example.com")
    client.set_user(user)
    resp = await client.post(
        "/api/import/fitbod/commit",
        json={"csv_text": "garbage\nrows\n"},
    )
    assert resp.status_code == 400
