"""Training-analytics API: Recovery, per-muscle weekly volume, e1RM trend.

End-to-end over real Postgres + the ASGI app: seed Sessions/Sets, hit the
endpoints, assert the shapes and the per-user scoping. The numeric behaviour of
the cores is pinned in :mod:`tests.test_recovery` / :mod:`tests.test_muscle_volume`
/ :mod:`tests.test_e1rm`; here we assert the wiring (the right rows, the right
exclusions, the right user, the documented response shape).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User

# The 17 catalog muscles, so the Recovery endpoint's "fill untrained at 100" is
# checkable against a known total.
_ALL_MUSCLES = {m.value for m in Muscle}


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


async def _exercise(db, name: str, muscles: list[tuple[Muscle, MuscleRole]]) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db",
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
    """Create a one-set Session for ``user`` started ``days_ago`` days back."""
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


# --------------------------------------------------------------------------- #
# Recovery
# --------------------------------------------------------------------------- #


async def test_recovery_returns_all_muscles_untrained_at_100(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)

    resp = await client.get("/api/analytics/recovery")
    assert resp.status_code == 200
    body = resp.json()
    assert "as_of" in body and body["half_life_hours"] > 0
    returned = {m["muscle"] for m in body["muscles"]}
    # Every catalog muscle is present; with no training all read 100.
    assert returned == _ALL_MUSCLES
    assert all(m["recovery"] == 100.0 for m in body["muscles"])


async def test_recovery_drops_for_recently_trained_muscle(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(
        db_session,
        "Bench Press",
        [(Muscle.chest, MuscleRole.primary), (Muscle.triceps, MuscleRole.secondary)],
    )
    # A hard chest session a few hours ago.
    await _log(db_session, alice, bench, days_ago=0.25, weight=100.0, reps=8)
    client.set_user(alice)

    body = (await client.get("/api/analytics/recovery")).json()
    by = {m["muscle"]: m["recovery"] for m in body["muscles"]}
    # Chest (primary) is the most fatigued; triceps (secondary) less so; both
    # below an untrained muscle.
    assert by["chest"] < by["triceps"] < 100.0
    assert by["hamstrings"] == 100.0


async def test_recovery_ignores_other_users(client, db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    squat = await _exercise(
        db_session, "Squat", [(Muscle.quadriceps, MuscleRole.primary)]
    )
    # Bob trains legs hard; Alice does nothing.
    await _log(db_session, bob, squat, days_ago=0.1, weight=150.0, reps=5)

    client.set_user(alice)
    body = (await client.get("/api/analytics/recovery")).json()
    by = {m["muscle"]: m["recovery"] for m in body["muscles"]}
    # Alice's quads are fresh — Bob's session must not bleed in.
    assert by["quadriceps"] == 100.0


# --------------------------------------------------------------------------- #
# Weekly volume
# --------------------------------------------------------------------------- #


async def test_volume_groups_by_muscle_and_excludes_non_normal(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(
        db_session,
        "Bench Press",
        [(Muscle.chest, MuscleRole.primary), (Muscle.triceps, MuscleRole.secondary)],
    )
    await _log(db_session, alice, bench, days_ago=2, weight=100.0, reps=5)  # 500
    await _log(db_session, alice, bench, days_ago=2, weight=100.0, reps=4)  # 400
    await _log(
        db_session, alice, bench, days_ago=2, weight=60.0, reps=10,
        set_type=SetType.warmup,
    )  # excluded
    client.set_user(alice)

    body = (await client.get("/api/analytics/volume?weeks=4")).json()
    assert body["weeks"] == 4
    by = {(m["muscle"], m["role"]): m for m in body["muscles"]}
    # Chest primary: 2 normal sets, 900 load. Triceps secondary: same 2 sets.
    assert by[("chest", "primary")]["set_count"] == 2
    assert by[("chest", "primary")]["volume_load"] == pytest.approx(900.0)
    assert by[("triceps", "secondary")]["set_count"] == 2
    # The warmup never appears.
    assert all(m["set_count"] == 2 for m in body["muscles"])


async def test_volume_respects_weeks_window(client, db_session) -> None:
    alice = await _user(db_session)
    curl = await _exercise(
        db_session, "Curl", [(Muscle.biceps, MuscleRole.primary)]
    )
    await _log(db_session, alice, curl, days_ago=10, weight=20.0, reps=10)
    client.set_user(alice)

    two_wk = (await client.get("/api/analytics/volume?weeks=2")).json()
    one_wk = (await client.get("/api/analytics/volume?weeks=1")).json()
    assert any(m["muscle"] == "biceps" for m in two_wk["muscles"])
    assert one_wk["muscles"] == []


# --------------------------------------------------------------------------- #
# e1RM trend
# --------------------------------------------------------------------------- #


async def test_e1rm_trend_returns_chronological_points(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(
        db_session, "Bench Press", [(Muscle.chest, MuscleRole.primary)]
    )
    # Three normal sets on different days; e1RM rises with the heavier later set.
    await _log(db_session, alice, bench, days_ago=14, weight=80.0, reps=5)
    await _log(db_session, alice, bench, days_ago=7, weight=85.0, reps=5)
    await _log(db_session, alice, bench, days_ago=1, weight=90.0, reps=5)
    client.set_user(alice)

    body = (await client.get(f"/api/analytics/e1rm-trend?exercise_id={bench.id}")).json()
    assert body["exercise_id"] == str(bench.id)
    times = [p["time"] for p in body["points"]]
    # Chronological order (oldest first).
    assert times == sorted(times)
    assert len(body["points"]) == 3
    # The best equals the peak point (the last, heaviest set here).
    assert body["best_e1rm"] == pytest.approx(max(p["e1rm"] for p in body["points"]))


async def test_e1rm_trend_excludes_non_normal_and_zero(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(
        db_session, "Bench Press", [(Muscle.chest, MuscleRole.primary)]
    )
    await _log(db_session, alice, bench, days_ago=3, weight=100.0, reps=5)  # counts
    await _log(
        db_session, alice, bench, days_ago=3, weight=120.0, reps=2,
        set_type=SetType.warmup,
    )  # excluded
    await _log(db_session, alice, bench, days_ago=3, weight=0.0, reps=10)  # zero load
    client.set_user(alice)

    body = (await client.get(f"/api/analytics/e1rm-trend?exercise_id={bench.id}")).json()
    # Only the single normal, non-zero set.
    assert len(body["points"]) == 1


async def test_e1rm_trend_is_per_user(client, db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    bench = await _exercise(
        db_session, "Bench Press", [(Muscle.chest, MuscleRole.primary)]
    )
    await _log(db_session, bob, bench, days_ago=1, weight=140.0, reps=5)

    client.set_user(alice)
    body = (await client.get(f"/api/analytics/e1rm-trend?exercise_id={bench.id}")).json()
    # Alice never logged this Exercise — Bob's sets must not appear.
    assert body["points"] == []
    assert body["best_e1rm"] is None


async def test_e1rm_trend_unknown_exercise_is_404(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get(f"/api/analytics/e1rm-trend?exercise_id={uuid.uuid4()}")
    assert resp.status_code == 404
