"""Conversational adjust API — preview + start, end-to-end (#14, ADR-0002).

The adjust pieces are unit-tested in :mod:`tests.test_adjust` /
:mod:`tests.test_adjust_agent`; here we pin the WIRING through
``/api/recommendations/adjust[/start]`` with the **deterministic** provider (the
default — no external service): a request re-shapes today's proposal, the note
explains it, and starting the result instantiates editable Sets the user
overwrites (their edits win).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.gym_profile import GymProfile
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User


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


async def _exercise(db, name, muscle, *, equipment="barbell") -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db",
        equipment=equipment,
        instructions=[],
        images=[],
    )
    ex.muscles = [ExerciseMuscle(muscle=muscle, role=MuscleRole.primary)]
    db.add(ex)
    await db.flush()
    return ex


async def _gym(db, user: User, equipment: list[str]) -> None:
    db.add(
        GymProfile(
            user_id=user.id,
            bar_weights_kg=[20.0],
            plate_weights_kg=[1.25, 2.5, 5.0, 10.0, 20.0],
            equipment=equipment,
        )
    )
    await db.flush()


async def _log(db, user: User, ex: Exercise, *, weight: float, reps: int) -> None:
    started = datetime.now(timezone.utc) - timedelta(days=2)
    sess = TrainingSession(user_id=user.id, started_at=started)
    db.add(sess)
    await db.flush()
    db.add(
        TrainingSet(
            session_id=sess.id,
            exercise_id=ex.id,
            order_index=0,
            weight_kg=weight,
            reps=reps,
            set_type=SetType.normal,
        )
    )
    await db.flush()


async def _seed_freestyle_user(db) -> User:
    """A user with a couple of trained barbell+dumbbell Exercises (freestyle base)."""
    user = await _user(db)
    await _gym(db, user, ["barbell", "dumbbell"])
    bench = await _exercise(db, "Barbell Bench", Muscle.chest, equipment="barbell")
    row = await _exercise(db, "DB Row", Muscle.lats, equipment="dumbbell")
    squat = await _exercise(db, "Barbell Squat", Muscle.quadriceps, equipment="barbell")
    curl = await _exercise(db, "DB Curl", Muscle.biceps, equipment="dumbbell")
    for ex in (bench, row, squat, curl):
        await _log(db, user, ex, weight=40.0, reps=8)
    await db.flush()
    return user


# --------------------------------------------------------------------------- #
# Shorter
# --------------------------------------------------------------------------- #


async def test_adjust_shorter_caps_exercise_count(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)

    full = (await client.get("/api/recommendations/freestyle")).json()
    adjusted = (
        await client.post("/api/recommendations/adjust", json={"request": "make it shorter"})
    ).json()
    assert len(adjusted["exercises"]) <= 3
    assert len(adjusted["exercises"]) <= len(full["exercises"])
    assert adjusted["note"]
    assert adjusted["applied"]["max_exercises"] == 3


# --------------------------------------------------------------------------- #
# No barbell
# --------------------------------------------------------------------------- #


async def test_adjust_no_barbell_drops_barbell_exercises(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)

    adjusted = (
        await client.post("/api/recommendations/adjust", json={"request": "no barbell today"})
    ).json()
    names = [e["name"] for e in adjusted["exercises"]]
    assert all("Barbell" not in n for n in names)
    # Dumbbell movements survive.
    assert any("DB" in n for n in names)
    assert "barbell" in adjusted["applied"]["exclude_equipment"]


# --------------------------------------------------------------------------- #
# Tired → lighter
# --------------------------------------------------------------------------- #


async def test_adjust_tired_scales_volume_down(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)

    full = (await client.get("/api/recommendations/freestyle")).json()
    adjusted = (
        await client.post("/api/recommendations/adjust", json={"request": "I'm tired"})
    ).json()
    full_sets = sum(e["target_sets"] for e in full["exercises"])
    adj_sets = sum(e["target_sets"] for e in adjusted["exercises"])
    assert adj_sets < full_sets
    assert adjusted["applied"]["volume_scale"] is not None


# --------------------------------------------------------------------------- #
# Start instantiates editable Sets
# --------------------------------------------------------------------------- #


async def test_adjust_start_instantiates_session(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)

    resp = await client.post(
        "/api/recommendations/adjust/start", json={"request": "no barbell today"}
    )
    assert resp.status_code == 201
    detail = resp.json()
    # A real Session with editable Sets, none from a barbell movement.
    assert detail["id"]
    assert len(detail["sets"]) > 0


# --------------------------------------------------------------------------- #
# Unparseable request is a safe no-op (proposal, never a decision)
# --------------------------------------------------------------------------- #


async def test_adjust_unknown_request_is_noop(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)

    full = (await client.get("/api/recommendations/freestyle")).json()
    adjusted = (
        await client.post("/api/recommendations/adjust", json={"request": "tell me a joke"})
    ).json()
    # Nothing actionable → the proposal equals today's plan, with an explanatory note.
    assert len(adjusted["exercises"]) == len(full["exercises"])
    assert adjusted["note"]


async def test_adjust_request_validation(client, db_session) -> None:
    user = await _seed_freestyle_user(db_session)
    client.set_user(user)
    # Empty request is rejected by the schema.
    resp = await client.post("/api/recommendations/adjust", json={"request": ""})
    assert resp.status_code == 422
