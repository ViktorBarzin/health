"""Superset grouping on Sets (#7).

- A Set can be created/edited with a superset_group; it round-trips on read.
- POST /supersets tags the named Sets with a fresh group id (>=2 distinct
  Exercises required); DELETE /supersets/{group} clears the tag.
- Validation: unknown set ids and single-exercise groups are rejected.
- All scoped per-user (the Session ownership guards the Sets).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_exercise(db, name: str) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=None,
        source="free-exercise-db",
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


async def _start_session(client) -> str:
    return (await client.post("/api/sessions/", json={})).json()["id"]


async def _add_set(client, sid, ex, **kw) -> dict:
    payload = {"exercise_id": str(ex.id), "weight_kg": 50, "reps": 8, **kw}
    return (await client.post(f"/api/sessions/{sid}/sets", json=payload)).json()


async def test_set_superset_group_round_trips_on_create(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = await _start_session(client)

    created = await _add_set(client, sid, bench, superset_group=3)
    assert created["superset_group"] == 3

    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["sets"][0]["superset_group"] == 3


async def test_patch_can_clear_superset_group(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = await _start_session(client)
    s = await _add_set(client, sid, bench, superset_group=1)

    patched = await client.patch(
        f"/api/sessions/{sid}/sets/{s['id']}", json={"superset_group": None}
    )
    assert patched.status_code == 200
    assert patched.json()["superset_group"] is None


async def test_group_superset_assigns_fresh_group_id(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    row = await _make_exercise(db_session, "Barbell Row")
    client.set_user(alice)
    sid = await _start_session(client)
    s1 = await _add_set(client, sid, bench)
    s2 = await _add_set(client, sid, row)

    resp = await client.post(
        f"/api/sessions/{sid}/supersets",
        json={"set_ids": [s1["id"], s2["id"]]},
    )
    assert resp.status_code == 200
    groups = {st["id"]: st["superset_group"] for st in resp.json()["sets"]}
    # Both got the same fresh group id (0, the first group in this Session).
    assert groups[s1["id"]] == 0
    assert groups[s2["id"]] == 0


async def test_group_superset_increments_group_id(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    a = await _make_exercise(db_session, "A")
    b = await _make_exercise(db_session, "B")
    c = await _make_exercise(db_session, "C")
    d = await _make_exercise(db_session, "D")
    client.set_user(alice)
    sid = await _start_session(client)
    sa = await _add_set(client, sid, a)
    sb = await _add_set(client, sid, b)
    sc = await _add_set(client, sid, c)
    sd = await _add_set(client, sid, d)

    await client.post(
        f"/api/sessions/{sid}/supersets", json={"set_ids": [sa["id"], sb["id"]]}
    )
    resp = await client.post(
        f"/api/sessions/{sid}/supersets", json={"set_ids": [sc["id"], sd["id"]]}
    )
    groups = {st["id"]: st["superset_group"] for st in resp.json()["sets"]}
    assert groups[sa["id"]] == 0
    assert groups[sc["id"]] == 1  # next fresh id


async def test_group_superset_requires_two_distinct_exercises(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = await _start_session(client)
    s1 = await _add_set(client, sid, bench)
    s2 = await _add_set(client, sid, bench)  # same exercise

    resp = await client.post(
        f"/api/sessions/{sid}/supersets", json={"set_ids": [s1["id"], s2["id"]]}
    )
    assert resp.status_code == 400


async def test_group_superset_rejects_foreign_set_id(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = await _start_session(client)
    s1 = await _add_set(client, sid, bench)

    resp = await client.post(
        f"/api/sessions/{sid}/supersets",
        json={"set_ids": [s1["id"], str(uuid.uuid4())]},
    )
    assert resp.status_code == 400


async def test_ungroup_superset_clears_the_tag(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    row = await _make_exercise(db_session, "Barbell Row")
    client.set_user(alice)
    sid = await _start_session(client)
    s1 = await _add_set(client, sid, bench)
    s2 = await _add_set(client, sid, row)
    await client.post(
        f"/api/sessions/{sid}/supersets", json={"set_ids": [s1["id"], s2["id"]]}
    )

    resp = await client.delete(f"/api/sessions/{sid}/supersets/0")
    assert resp.status_code == 200
    assert all(st["superset_group"] is None for st in resp.json()["sets"])


async def test_superset_endpoints_are_per_user(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bench = await _make_exercise(db_session, "Bench Press")
    row = await _make_exercise(db_session, "Barbell Row")

    client.set_user(alice)
    sid = await _start_session(client)
    s1 = await _add_set(client, sid, bench)
    s2 = await _add_set(client, sid, row)

    # Bob cannot group Alice's session's sets — her Session 404s for him.
    client.set_user(bob)
    resp = await client.post(
        f"/api/sessions/{sid}/supersets", json={"set_ids": [s1["id"], s2["id"]]}
    )
    assert resp.status_code == 404
