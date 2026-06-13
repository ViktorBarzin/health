"""Freestyle Recommendation API — preview + start, end-to-end over real Postgres.

The pure cores' numeric behaviour is pinned in :mod:`tests.test_progression` and
:mod:`tests.test_recommendation`; here we assert the WIRING (the right candidate
population, equipment filter from the Gym Profile, Recovery bias, per-user
scoping, and that *starting* a Recommendation instantiates a Session pre-filled
with the target Sets the existing logging UI then drives).
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


async def _exercise(
    db,
    name: str,
    muscles: list[tuple[Muscle, MuscleRole]],
    *,
    equipment: str | None = "dumbbell",
) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db",
        equipment=equipment,
        instructions=[],
        images=[],
    )
    ex.muscles = [ExerciseMuscle(muscle=m, role=r) for m, r in muscles]
    db.add(ex)
    await db.flush()
    return ex


async def _log(
    db,
    user: User,
    exercise: Exercise,
    *,
    days_ago: float,
    weight: float,
    reps: int,
    set_type: SetType = SetType.normal,
    rpe: float | None = None,
) -> TrainingSet:
    started = datetime.now(timezone.utc) - timedelta(days=days_ago)
    sess = TrainingSession(user_id=user.id, started_at=started)
    db.add(sess)
    await db.flush()
    ts = TrainingSet(
        session_id=sess.id,
        exercise_id=exercise.id,
        order_index=0,
        weight_kg=weight,
        reps=reps,
        set_type=set_type,
        rpe=rpe,
    )
    db.add(ts)
    await db.flush()
    return ts


async def _set_gym_profile(db, user: User, equipment: list[str]) -> None:
    db.add(
        GymProfile(
            user_id=user.id,
            bar_weights_kg=[20.0],
            plate_weights_kg=[1.25, 2.5, 5.0, 10.0, 20.0],
            equipment=equipment,
        )
    )
    await db.flush()


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #


async def test_preview_empty_with_no_history(client, db_session) -> None:
    # A user who has logged nothing gets an empty proposal (freestyle is
    # training-history-only; the UI guides them to log first).
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get("/api/recommendations/freestyle")
    assert resp.status_code == 200
    assert resp.json() == {"exercises": []}


async def test_preview_prescribes_progression_target(client, db_session) -> None:
    # Last time bench 60×12 @ RIR2 (RPE 8): top of 8–12 with reserve → next
    # target +2.5 kg, reset to 8 reps, default 3 sets.
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    await _log(db_session, alice, bench, days_ago=3, weight=60.0, reps=12, rpe=8.0)
    client.set_user(alice)

    resp = await client.get("/api/recommendations/freestyle")
    assert resp.status_code == 200
    items = resp.json()["exercises"]
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "Bench"
    assert item["target_weight_kg"] == 62.5
    assert item["target_reps"] == 8
    assert item["target_sets"] == 3
    assert item["is_starting_point"] is False
    assert item["primary_muscles"] == ["chest"]


async def test_preview_excludes_unavailable_equipment(client, db_session) -> None:
    # The user owns only dumbbells; a trained barbell Exercise must not appear.
    alice = await _user(db_session)
    await _set_gym_profile(db_session, alice, ["dumbbell"])
    db_ex = await _exercise(
        db_session, "DB Press", [(Muscle.chest, MuscleRole.primary)], equipment="dumbbell"
    )
    bb_ex = await _exercise(
        db_session, "BB Bench", [(Muscle.chest, MuscleRole.primary)], equipment="barbell"
    )
    await _log(db_session, alice, db_ex, days_ago=2, weight=30.0, reps=10, rpe=8.0)
    await _log(db_session, alice, bb_ex, days_ago=2, weight=80.0, reps=10, rpe=8.0)
    client.set_user(alice)

    resp = await client.get("/api/recommendations/freestyle")
    names = {i["name"] for i in resp.json()["exercises"]}
    assert "DB Press" in names
    assert "BB Bench" not in names


async def test_preview_biases_toward_fresh_muscles(client, db_session) -> None:
    # Chest was hammered today (low Recovery); back trained long ago (fresh).
    # With room for one Exercise, the fresh-muscle one leads.
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    row = await _exercise(db_session, "Row", [(Muscle.lats, MuscleRole.primary)])
    # Heavy, very recent chest load → low chest Recovery.
    await _log(db_session, alice, bench, days_ago=0.05, weight=80.0, reps=10, rpe=8.0)
    # Light, old back load → lats nearly fully recovered.
    await _log(db_session, alice, row, days_ago=20, weight=40.0, reps=10, rpe=8.0)
    client.set_user(alice)

    resp = await client.get("/api/recommendations/freestyle?exercise_count=1")
    items = resp.json()["exercises"]
    assert len(items) == 1
    assert items[0]["name"] == "Row"


async def test_preview_is_scoped_to_the_user(client, db_session) -> None:
    # Bob's history never leaks into Alice's proposal.
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    bob_ex = await _exercise(db_session, "Bob Curl", [(Muscle.biceps, MuscleRole.primary)])
    await _log(db_session, bob, bob_ex, days_ago=2, weight=20.0, reps=10, rpe=8.0)

    client.set_user(alice)
    resp = await client.get("/api/recommendations/freestyle")
    assert resp.json() == {"exercises": []}


async def test_preview_is_deterministic(client, db_session) -> None:
    # Same data → identical proposal on repeated calls (deterministic core).
    alice = await _user(db_session)
    for i, m in enumerate([Muscle.chest, Muscle.lats, Muscle.quadriceps]):
        ex = await _exercise(db_session, f"Ex{i}", [(m, MuscleRole.primary)])
        await _log(db_session, alice, ex, days_ago=5, weight=50.0 + i, reps=10, rpe=8.0)
    client.set_user(alice)

    a = (await client.get("/api/recommendations/freestyle")).json()
    b = (await client.get("/api/recommendations/freestyle")).json()
    assert a == b


# --------------------------------------------------------------------------- #
# Start → instantiate a Session pre-filled with target Sets
# --------------------------------------------------------------------------- #


async def test_start_instantiates_session_with_target_sets(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    await _log(db_session, alice, bench, days_ago=3, weight=60.0, reps=12, rpe=8.0)
    client.set_user(alice)

    resp = await client.post("/api/recommendations/freestyle/start", json={})
    assert resp.status_code == 201
    body = resp.json()
    # A real Session was created, active (not finished), with 3 pre-filled Sets.
    assert body["is_active"] is True
    assert body["set_count"] == 3
    assert len(body["sets"]) == 3
    for s in body["sets"]:
        assert s["exercise_id"] == str(bench.id)
        assert s["weight_kg"] == 62.5
        assert s["reps"] == 8
        assert s["set_type"] == "normal"
        assert s["effort_rir"] is None
        # The Exercise relationship is loaded for the response (no MissingGreenlet).
        assert s["exercise_name"] == "Bench"
    # order_index is gap-free 0..n-1.
    assert sorted(s["order_index"] for s in body["sets"]) == [0, 1, 2]


async def test_start_then_get_session_round_trips(client, db_session) -> None:
    # The instantiated Session is a normal Session: fetchable via the sessions API.
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    await _log(db_session, alice, bench, days_ago=3, weight=60.0, reps=12, rpe=8.0)
    client.set_user(alice)

    start = await client.post("/api/recommendations/freestyle/start", json={})
    session_id = start.json()["id"]
    got = await client.get(f"/api/sessions/{session_id}")
    assert got.status_code == 200
    assert got.json()["set_count"] == 3


async def test_user_edit_persists_over_target(client, db_session) -> None:
    # User edits always win: PATCHing a prescribed Set's weight overwrites the
    # generated target and persists (there is no separate prescribed state).
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    await _log(db_session, alice, bench, days_ago=3, weight=60.0, reps=12, rpe=8.0)
    client.set_user(alice)

    start = await client.post("/api/recommendations/freestyle/start", json={})
    session_id = start.json()["id"]
    first_set = start.json()["sets"][0]
    assert first_set["weight_kg"] == 62.5

    patch = await client.patch(
        f"/api/sessions/{session_id}/sets/{first_set['id']}",
        json={"weight_kg": 70.0, "reps": 6, "effort_rir": 1},
    )
    assert patch.status_code == 200

    got = await client.get(f"/api/sessions/{session_id}")
    edited = next(s for s in got.json()["sets"] if s["id"] == first_set["id"])
    assert edited["weight_kg"] == 70.0
    assert edited["reps"] == 6
    assert edited["effort_rir"] == 1


async def test_start_with_no_history_creates_empty_session(client, db_session) -> None:
    # Nothing to propose → still a valid (empty) Session the user can add to.
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.post("/api/recommendations/freestyle/start", json={})
    assert resp.status_code == 201
    assert resp.json()["set_count"] == 0


async def test_start_honours_count_and_sets_params(client, db_session) -> None:
    # exercise_count + sets_per_exercise size the instantiated Session.
    alice = await _user(db_session)
    for i, m in enumerate([Muscle.chest, Muscle.lats, Muscle.quadriceps]):
        ex = await _exercise(db_session, f"Ex{i}", [(m, MuscleRole.primary)])
        await _log(db_session, alice, ex, days_ago=5, weight=50.0, reps=10, rpe=8.0)
    client.set_user(alice)

    resp = await client.post(
        "/api/recommendations/freestyle/start",
        json={"exercise_count": 2, "sets_per_exercise": 4},
    )
    assert resp.status_code == 201
    # 2 Exercises × 4 sets = 8 Sets.
    assert resp.json()["set_count"] == 8


async def test_warmup_sets_do_not_seed_progression(client, db_session) -> None:
    # Only normal Sets feed Progression (the volume.counts_for_volume exclusion):
    # a user whose only history is a warmup has nothing to progress → empty.
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench", [(Muscle.chest, MuscleRole.primary)])
    await _log(
        db_session, alice, bench, days_ago=2, weight=60.0, reps=12,
        set_type=SetType.warmup, rpe=8.0,
    )
    client.set_user(alice)
    resp = await client.get("/api/recommendations/freestyle")
    assert resp.json() == {"exercises": []}
