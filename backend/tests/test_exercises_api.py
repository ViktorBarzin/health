"""Exercise library API + visibility contract.

- A user browses global ∪ their own custom Exercises, never another user's.
- Search-by-name and filter-by-muscle/equipment narrow that visible set.
- Creating a custom Exercise yields a private row owned by the caller.
- Fetching another user's custom Exercise by id is a 404 (not visible).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.user import User


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


def _global(slug: str, name: str, *, equipment=None, primary=(), secondary=()) -> Exercise:
    ex = Exercise(slug=slug, name=name, user_id=None, equipment=equipment, source="free-exercise-db")
    for m in primary:
        ex.muscles.append(ExerciseMuscle(muscle=m, role=MuscleRole.primary))
    for m in secondary:
        ex.muscles.append(ExerciseMuscle(muscle=m, role=MuscleRole.secondary))
    return ex


@pytest.fixture
async def client(db_session):
    """An AsyncClient whose backend uses the test session and a fixed identity.

    The current user is whoever ``client.user`` points at; tests flip it to
    exercise cross-user visibility. ``get_db`` is overridden to hand back the
    test session without closing/committing it out from under the fixture.
    """
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


async def test_browse_returns_global_plus_own_not_other_users(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    db_session.add_all(
        [
            _global("bench", "Bench Press", primary=[Muscle.chest]),
            Exercise(slug="alice-move", name="Alice Move", user_id=alice.id),
            Exercise(slug="bob-move", name="Bob Move", user_id=bob.id),
        ]
    )
    await db_session.flush()

    client.set_user(alice)
    resp = await client.get("/api/exercises/")
    assert resp.status_code == 200
    names = {e["name"] for e in resp.json()}
    # Alice sees the global Exercise + her own, but NOT Bob's custom one.
    assert names == {"Bench Press", "Alice Move"}


async def test_search_by_name(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add_all(
        [
            _global("bench", "Barbell Bench Press"),
            _global("squat", "Back Squat"),
            _global("curl", "Bicep Curl"),
        ]
    )
    await db_session.flush()
    client.set_user(alice)

    resp = await client.get("/api/exercises/", params={"search": "bench"})
    assert [e["name"] for e in resp.json()] == ["Barbell Bench Press"]


async def test_filter_by_muscle_matches_primary_or_secondary(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add_all(
        [
            _global("bench", "Bench Press", primary=[Muscle.chest], secondary=[Muscle.triceps]),
            _global("pushdown", "Triceps Pushdown", primary=[Muscle.triceps]),
            _global("squat", "Back Squat", primary=[Muscle.quadriceps]),
        ]
    )
    await db_session.flush()
    client.set_user(alice)

    resp = await client.get("/api/exercises/", params={"muscle": "triceps"})
    names = {e["name"] for e in resp.json()}
    # Bench (triceps secondary) and Pushdown (triceps primary); not the squat.
    assert names == {"Bench Press", "Triceps Pushdown"}


async def test_filter_by_equipment(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add_all(
        [
            _global("bench", "Bench Press", equipment="barbell"),
            _global("curl", "Dumbbell Curl", equipment="dumbbell"),
        ]
    )
    await db_session.flush()
    client.set_user(alice)

    resp = await client.get("/api/exercises/", params={"equipment": "dumbbell"})
    assert [e["name"] for e in resp.json()] == ["Dumbbell Curl"]


async def test_create_custom_exercise_is_private_to_creator(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)

    resp = await client.post(
        "/api/exercises/",
        json={
            "name": "My Cable Fly",
            "equipment": "cable",
            "primary_muscles": ["chest"],
            "secondary_muscles": ["shoulders"],
            "instructions": ["Squeeze."],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_custom"] is True
    assert body["primary_muscles"] == ["chest"]
    assert body["secondary_muscles"] == ["shoulders"]
    assert body["instructions"] == ["Squeeze."]
    assert "youtube.com/results" in body["demo_video_url"]
    new_id = body["id"]

    # Alice sees it; Bob does not (browse) and gets 404 on direct fetch.
    client.set_user(alice)
    assert any(e["id"] == new_id for e in (await client.get("/api/exercises/")).json())

    client.set_user(bob)
    assert all(e["id"] != new_id for e in (await client.get("/api/exercises/")).json())
    assert (await client.get(f"/api/exercises/{new_id}")).status_code == 404


async def test_create_rejects_unknown_muscle(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.post(
        "/api/exercises/",
        json={"name": "Bad Move", "primary_muscles": ["spleen"]},
    )
    assert resp.status_code == 422  # not a member of the Muscle enum


async def test_get_global_exercise_detail(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = _global("bench", "Bench Press", primary=[Muscle.chest])
    ex.instructions = ["Lie down.", "Press up."]
    db_session.add(ex)
    await db_session.flush()
    client.set_user(alice)

    resp = await client.get(f"/api/exercises/{ex.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Bench Press"
    assert body["instructions"] == ["Lie down.", "Press up."]
    assert body["is_custom"] is False


async def test_get_missing_exercise_is_404(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.get(f"/api/exercises/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_muscles_endpoint_lists_the_typed_dimension(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.get("/api/exercises/muscles")
    assert resp.status_code == 200
    values = {m["value"] for m in resp.json()}
    assert "chest" in values and "lower back" in values
    assert len(values) == 17


async def test_equipment_endpoint_lists_visible_distinct_values(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    db_session.add_all(
        [
            _global("bench", "Bench Press", equipment="barbell"),
            _global("curl", "Dumbbell Curl", equipment="dumbbell"),
            _global("pushup", "Push Up", equipment=None),
        ]
    )
    await db_session.flush()
    client.set_user(alice)
    resp = await client.get("/api/exercises/equipment")
    assert resp.status_code == 200
    assert resp.json() == ["barbell", "dumbbell"]  # sorted, nulls excluded
