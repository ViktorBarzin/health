"""Gym Profile API + per-user scoping contract.

- GET get-or-creates the singleton profile with the standard defaults.
- PUT replaces the equipment and normalizes the weight/equipment lists.
- A user only ever reads/writes their own profile (isolation).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.gym_profile import (
    DEFAULT_BAR_WEIGHTS_KG,
    DEFAULT_PLATE_WEIGHTS_KG,
)
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


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


async def test_get_creates_profile_with_defaults(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.get("/api/gym-profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bar_weights_kg"] == DEFAULT_BAR_WEIGHTS_KG
    assert body["plate_weights_kg"] == DEFAULT_PLATE_WEIGHTS_KG
    assert "barbell" in body["equipment"]


async def test_get_is_idempotent_does_not_duplicate(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.get("/api/gym-profile")
    again = await client.get("/api/gym-profile")
    assert again.status_code == 200
    # Same defaults still — a second get didn't create a second profile or reset.
    assert again.json()["bar_weights_kg"] == DEFAULT_BAR_WEIGHTS_KG


async def test_put_replaces_and_normalizes(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.put(
        "/api/gym-profile",
        json={
            # unsorted, dup, and a junk non-positive value
            "bar_weights_kg": [20, 15, 20, 0, -5],
            "plate_weights_kg": [25, 1.25, 5, 5, 10],
            "equipment": [" barbell ", "Barbell", "dumbbell", ""],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # weights de-duplicated, positives only, ascending
    assert body["bar_weights_kg"] == [15, 20]
    assert body["plate_weights_kg"] == [1.25, 5, 10, 25]
    # equipment trimmed + case-insensitively de-duplicated, first-seen kept
    assert body["equipment"] == ["barbell", "dumbbell"]

    # Persisted: a fresh GET returns the saved values, not the defaults.
    got = await client.get("/api/gym-profile")
    assert got.json()["plate_weights_kg"] == [1.25, 5, 10, 25]


async def test_put_rejects_unknown_fields(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.put("/api/gym-profile", json={"bogus": 1})
    assert resp.status_code == 422


async def test_profile_is_per_user(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    client.set_user(alice)
    await client.put(
        "/api/gym-profile",
        json={"bar_weights_kg": [25], "plate_weights_kg": [20], "equipment": []},
    )

    # Bob sees the defaults, not Alice's edits.
    client.set_user(bob)
    bob_body = (await client.get("/api/gym-profile")).json()
    assert bob_body["bar_weights_kg"] == DEFAULT_BAR_WEIGHTS_KG

    # Alice still sees her own edits.
    client.set_user(alice)
    alice_body = (await client.get("/api/gym-profile")).json()
    assert alice_body["bar_weights_kg"] == [25]
