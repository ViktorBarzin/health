"""Swap alternatives + Exclusion API (CONTEXT.md "Swap" / "Exclusion").

- PUT/DELETE ``/api/exercises/{id}/exclusion`` toggles the per-user "never
  recommend this again" mark (idempotent, visibility-checked, coexists with the
  rest pref on the same row); ``GET /api/exercises/exclusions`` lists them.
- An Excluded Exercise disappears from BOTH generator paths (freestyle and
  Program-drawn) — the filter behaves exactly like Gym Profile equipment.
- ``GET /api/exercises/{id}/alternatives`` returns the ranked equivalents for a
  Swap: shared-primary-muscle pool, Gym-Profile-filtered, Exclusions and
  ``?exclude=`` (today's other Exercises) dropped, each prescribed off its OWN
  history.
- ``POST /api/recommendations/start`` instantiates exactly the (possibly
  swapped) proposal the client displays — the WYSIWYG start path.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.exercise_pref import ExercisePref
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
    primary: list[Muscle],
    *,
    equipment: str | None = "barbell",
    secondary: list[Muscle] | None = None,
    user_id: int | None = None,
) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db" if user_id is None else "custom",
        equipment=equipment,
        instructions=[],
        images=[],
        user_id=user_id,
    )
    ex.muscles = [ExerciseMuscle(muscle=m, role=MuscleRole.primary) for m in primary]
    for m in secondary or []:
        ex.muscles.append(ExerciseMuscle(muscle=m, role=MuscleRole.secondary))
    db.add(ex)
    await db.flush()
    return ex


async def _log_history(
    db, user: User, exercise: Exercise, *, weight: float = 60.0, reps: int = 8
) -> None:
    """One recent working Set so the Exercise is 'trained' (history for Progression)."""
    session = TrainingSession(
        user_id=user.id, started_at=datetime.now(timezone.utc) - timedelta(days=2)
    )
    db.add(session)
    await db.flush()
    db.add(
        TrainingSet(
            session_id=session.id,
            exercise_id=exercise.id,
            order_index=0,
            weight_kg=weight,
            reps=reps,
            set_type=SetType.normal,
        )
    )
    await db.flush()


# --------------------------------------------------------------------------- #
# Exclusion endpoints
# --------------------------------------------------------------------------- #


async def test_exclude_upsert_list_and_remove(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    client.set_user(alice)

    # Nothing excluded yet.
    resp = await client.get("/api/exercises/exclusions")
    assert resp.status_code == 200
    assert resp.json() == []

    # Exclude (idempotent: second PUT is fine and doesn't duplicate).
    assert (await client.put(f"/api/exercises/{bench.id}/exclusion")).status_code == 204
    assert (await client.put(f"/api/exercises/{bench.id}/exclusion")).status_code == 204
    listed = (await client.get("/api/exercises/exclusions")).json()
    assert [e["name"] for e in listed] == ["Bench Press"]
    assert listed[0]["exercise_id"] == str(bench.id)

    # Remove — list is empty again; removing again stays a 204 (idempotent).
    assert (
        await client.delete(f"/api/exercises/{bench.id}/exclusion")
    ).status_code == 204
    assert (await client.get("/api/exercises/exclusions")).json() == []
    assert (
        await client.delete(f"/api/exercises/{bench.id}/exclusion")
    ).status_code == 204


async def test_exclusion_coexists_with_rest_pref_on_the_same_row(
    client, db_session
) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    client.set_user(alice)

    # Set a rest pref first, then exclude, then un-exclude: the rest pref survives.
    await client.put(f"/api/exercises/{bench.id}/rest", json={"default_rest_seconds": 180})
    await client.put(f"/api/exercises/{bench.id}/exclusion")
    await client.delete(f"/api/exercises/{bench.id}/exclusion")
    pref = (await client.get(f"/api/exercises/{bench.id}/rest")).json()
    assert pref["default_rest_seconds"] == 180

    prefs = (
        await db_session.execute(
            __import__("sqlalchemy").select(ExercisePref).where(
                ExercisePref.user_id == alice.id
            )
        )
    ).scalars().all()
    assert len(prefs) == 1  # one row per (user, exercise) — no duplicates


async def test_exclude_invisible_exercise_is_404(client, db_session) -> None:
    alice = await _user(db_session)
    bob = await _user(db_session, "bob@example.com")
    bobs = await _exercise(db_session, "Bob Move", [Muscle.chest], user_id=bob.id)
    client.set_user(alice)

    assert (await client.put(f"/api/exercises/{bobs.id}/exclusion")).status_code == 404


# --------------------------------------------------------------------------- #
# Exclusions filter BOTH generator paths
# --------------------------------------------------------------------------- #


async def test_excluded_exercise_never_freestyle_recommended(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    squat = await _exercise(db_session, "Back Squat", [Muscle.quadriceps])
    await _log_history(db_session, alice, bench)
    await _log_history(db_session, alice, squat)
    client.set_user(alice)

    names = {
        e["name"]
        for e in (await client.get("/api/recommendations/freestyle")).json()["exercises"]
    }
    assert names == {"Bench Press", "Back Squat"}

    await client.put(f"/api/exercises/{bench.id}/exclusion")
    names = {
        e["name"]
        for e in (await client.get("/api/recommendations/freestyle")).json()["exercises"]
    }
    assert names == {"Back Squat"}


async def test_excluded_exercise_never_picked_for_a_program_slot(
    client, db_session
) -> None:
    from tests.test_program_recommendation_api import _program

    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    fly = await _exercise(db_session, "Dumbbell Fly", [Muscle.chest], equipment="dumbbell")
    await _log_history(db_session, alice, bench)  # trained → would win the slot
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell", "dumbbell"]))
    await _program(
        db_session,
        alice,
        days=[("Chest Day", [Muscle.chest])],
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    client.set_user(alice)

    today = (await client.get("/api/recommendations/today")).json()
    assert today["source"] == "program"
    assert [e["name"] for e in today["exercises"]] == ["Bench Press"]

    await client.put(f"/api/exercises/{bench.id}/exclusion")
    today = (await client.get("/api/recommendations/today")).json()
    assert [e["name"] for e in today["exercises"]] == ["Dumbbell Fly"]


# --------------------------------------------------------------------------- #
# Alternatives endpoint
# --------------------------------------------------------------------------- #


async def test_alternatives_ranked_filtered_and_prescribed(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    db_bench = await _exercise(
        db_session, "Dumbbell Bench Press", [Muscle.chest], equipment="dumbbell"
    )
    machine = await _exercise(
        db_session, "Machine Chest Press", [Muscle.chest], equipment="machine"
    )
    pushup = await _exercise(db_session, "Push-Up", [Muscle.chest], equipment=None)
    await _exercise(db_session, "Back Squat", [Muscle.quadriceps])
    excluded = await _exercise(
        db_session, "Smith Press", [Muscle.chest], equipment="dumbbell"
    )
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell", "dumbbell"]))
    await _log_history(db_session, alice, db_bench, weight=30.0, reps=10)
    client.set_user(alice)
    await client.put(f"/api/exercises/{excluded.id}/exclusion")

    resp = await client.get(f"/api/exercises/{bench.id}/alternatives")
    assert resp.status_code == 200
    alts = resp.json()
    # Trained equivalent first; bodyweight allowed; machine (no equipment), the
    # squat (no shared primary), the Excluded one, and bench itself are absent.
    assert [a["name"] for a in alts] == ["Dumbbell Bench Press", "Push-Up"]
    assert alts[0]["has_history"] is True
    assert alts[0]["target_weight_kg"] >= 30.0
    assert alts[0]["is_starting_point"] is False
    assert alts[1]["is_starting_point"] is True

    # ?exclude= drops Exercises already in today's plan.
    resp = await client.get(
        f"/api/exercises/{bench.id}/alternatives", params={"exclude": str(db_bench.id)}
    )
    assert [a["name"] for a in resp.json()] == ["Push-Up"]

    # Invisible target → 404 (same contract as the detail endpoint).
    bob = await _user(db_session, "bob@example.com")
    bobs = await _exercise(db_session, "Bob Move", [Muscle.chest], user_id=bob.id)
    assert (
        await client.get(f"/api/exercises/{bobs.id}/alternatives")
    ).status_code == 404


# --------------------------------------------------------------------------- #
# Explicit (WYSIWYG) start
# --------------------------------------------------------------------------- #


async def test_start_explicit_instantiates_exactly_what_was_sent(
    client, db_session
) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    squat = await _exercise(db_session, "Back Squat", [Muscle.quadriceps])
    client.set_user(alice)

    resp = await client.post(
        "/api/recommendations/start",
        json={
            "exercises": [
                {
                    "exercise_id": str(squat.id),
                    "target_sets": 2,
                    "target_reps": 5,
                    "target_weight_kg": 100.0,
                },
                {
                    "exercise_id": str(bench.id),
                    "target_sets": 3,
                    "target_reps": 8,
                    "target_weight_kg": 60.0,
                },
            ]
        },
    )
    assert resp.status_code == 201
    detail = resp.json()
    sets = detail["sets"]
    # Exactly 2 + 3 Sets, in the order sent, gap-free order_index, values echoed.
    assert len(sets) == 5
    assert [s["order_index"] for s in sets] == [0, 1, 2, 3, 4]
    assert [s["exercise_id"] for s in sets] == [str(squat.id)] * 2 + [str(bench.id)] * 3
    assert sets[0]["weight_kg"] == 100.0 and sets[0]["reps"] == 5
    assert sets[4]["weight_kg"] == 60.0 and sets[4]["reps"] == 8


async def test_start_explicit_rejects_invisible_exercise(client, db_session) -> None:
    alice = await _user(db_session)
    bob = await _user(db_session, "bob@example.com")
    bobs = await _exercise(db_session, "Bob Move", [Muscle.chest], user_id=bob.id)
    client.set_user(alice)

    resp = await client.post(
        "/api/recommendations/start",
        json={
            "exercises": [
                {
                    "exercise_id": str(bobs.id),
                    "target_sets": 3,
                    "target_reps": 8,
                    "target_weight_kg": 60.0,
                }
            ]
        },
    )
    assert resp.status_code == 404


async def test_start_explicit_enforces_bounds(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    client.set_user(alice)

    item = {
        "exercise_id": str(bench.id),
        "target_sets": 3,
        "target_reps": 8,
        "target_weight_kg": 60.0,
    }
    # Too many Exercises (>12) and too many sets (>10) are both rejected.
    resp = await client.post(
        "/api/recommendations/start", json={"exercises": [item] * 13}
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/api/recommendations/start",
        json={"exercises": [{**item, "target_sets": 11}]},
    )
    assert resp.status_code == 422
    resp = await client.post("/api/recommendations/start", json={"exercises": []})
    assert resp.status_code == 422
