"""Per-user rest-timer preference API (#7).

- GET returns the global default until the user sets an override.
- PUT upserts the override; null clears it (global default re-applies).
- The override is per-user and per-Exercise (isolation): one user's bench rest
  default never leaks to another, and global Exercises are never mutated.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise
from app.models.exercise_pref import DEFAULT_REST_SECONDS
from app.models.user import User

pytestmark = pytest.mark.asyncio


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


async def test_rest_pref_defaults_to_global_until_set(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)

    resp = await client.get(f"/api/exercises/{ex.id}/rest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_rest_seconds"] is None
    assert body["effective_rest_seconds"] == DEFAULT_REST_SECONDS


async def test_set_and_get_rest_override(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)

    put = await client.put(
        f"/api/exercises/{ex.id}/rest", json={"default_rest_seconds": 180}
    )
    assert put.status_code == 200
    assert put.json()["default_rest_seconds"] == 180
    assert put.json()["effective_rest_seconds"] == 180

    got = await client.get(f"/api/exercises/{ex.id}/rest")
    assert got.json()["effective_rest_seconds"] == 180


async def test_clear_rest_override_falls_back_to_global(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Deadlift")
    client.set_user(alice)
    await client.put(f"/api/exercises/{ex.id}/rest", json={"default_rest_seconds": 240})

    cleared = await client.put(
        f"/api/exercises/{ex.id}/rest", json={"default_rest_seconds": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["default_rest_seconds"] is None
    assert cleared.json()["effective_rest_seconds"] == DEFAULT_REST_SECONDS


async def test_rest_override_is_per_user(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    ex = await _make_exercise(db_session, "Overhead Press")  # global exercise

    client.set_user(alice)
    await client.put(f"/api/exercises/{ex.id}/rest", json={"default_rest_seconds": 200})

    # Bob's view of the same global Exercise is untouched.
    client.set_user(bob)
    bob_view = (await client.get(f"/api/exercises/{ex.id}/rest")).json()
    assert bob_view["default_rest_seconds"] is None
    assert bob_view["effective_rest_seconds"] == DEFAULT_REST_SECONDS


async def test_rest_pref_rejects_out_of_range(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Row")
    client.set_user(alice)
    too_long = await client.put(
        f"/api/exercises/{ex.id}/rest", json={"default_rest_seconds": 99999}
    )
    assert too_long.status_code == 422


async def test_rest_pref_404_for_invisible_exercise(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bob_ex = await _make_exercise(db_session, "Bob's Curl", user_id=bob.id)

    client.set_user(alice)
    resp = await client.get(f"/api/exercises/{bob_ex.id}/rest")
    assert resp.status_code == 404
