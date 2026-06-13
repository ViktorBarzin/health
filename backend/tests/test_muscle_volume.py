"""Per-muscle weekly volume aggregation — GROUP BY off ``exercise_muscles``.

The trailing-window, per-muscle-group rollup behind the volume heatmap and (later)
the engine's weekly-volume targets. Runs against real Postgres (the models use
Postgres enums / UUID), one clean schema per test via the ``db_session`` fixture.

Pinned behaviour:

* sets are grouped by the muscle their Exercise maps to (``exercise_muscles``),
  split by ``role`` (primary vs secondary), so "sets per muscle group" can count
  primary work the way the competitor heatmaps do;
* only ``normal`` Sets count — warmup/drop/failure are excluded (the same rule
  :func:`app.services.volume.counts_for_volume` owns), reused, not re-derived;
* only Sets inside the trailing window count;
* only the queried user's Sets count;
* volume-load is summed as ``weight × reps`` per (muscle, role).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.services.muscle_volume import weekly_muscle_volume

NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


async def _user(db, email: str = "alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _exercise(db, name: str, muscles: list[tuple[Muscle, MuscleRole]]) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db",
        instructions=[],
        images=[],
    )
    ex.muscles = [ExerciseMuscle(muscle=m, role=r) for m, r in muscles]
    db.add(ex)
    await db.flush()
    return ex


async def _session(db, user: User, *, started_at: datetime) -> TrainingSession:
    s = TrainingSession(user_id=user.id, started_at=started_at)
    db.add(s)
    await db.flush()
    return s


async def _set(
    db,
    session: TrainingSession,
    exercise: Exercise,
    *,
    order_index: int,
    weight: float,
    reps: int,
    set_type: SetType = SetType.normal,
) -> TrainingSet:
    ts = TrainingSet(
        session_id=session.id,
        exercise_id=exercise.id,
        order_index=order_index,
        weight_kg=weight,
        reps=reps,
        set_type=set_type,
    )
    db.add(ts)
    await db.flush()
    return ts


def _by_muscle(rows: list) -> dict[str, dict]:
    """Index the result rows by their muscle value for easy assertions."""
    return {r.muscle: r for r in rows}


async def test_empty_history_returns_nothing(db_session) -> None:
    alice = await _user(db_session)
    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    assert rows == []


async def test_groups_volume_and_sets_by_primary_muscle(db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(
        db_session,
        "Bench Press",
        [(Muscle.chest, MuscleRole.primary), (Muscle.triceps, MuscleRole.secondary)],
    )
    sess = await _session(db_session, alice, started_at=NOW - timedelta(days=2))
    # Two normal chest sets: 100×5 and 100×4 → primary chest volume 900.
    await _set(db_session, sess, bench, order_index=0, weight=100.0, reps=5)
    await _set(db_session, sess, bench, order_index=1, weight=100.0, reps=4)

    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    by = _by_muscle(rows)

    # Chest is the primary mover: 2 sets, volume 900.
    assert by["chest"].role == "primary"
    assert by["chest"].set_count == 2
    assert by["chest"].volume_load == pytest.approx(900.0)
    # Triceps is the secondary mover on the same 2 sets, same volume.
    assert by["triceps"].role == "secondary"
    assert by["triceps"].set_count == 2
    assert by["triceps"].volume_load == pytest.approx(900.0)


async def test_excludes_non_normal_sets(db_session) -> None:
    alice = await _user(db_session)
    squat = await _exercise(
        db_session, "Squat", [(Muscle.quadriceps, MuscleRole.primary)]
    )
    sess = await _session(db_session, alice, started_at=NOW - timedelta(days=1))
    await _set(db_session, sess, squat, order_index=0, weight=140.0, reps=5)  # 700
    await _set(
        db_session, sess, squat, order_index=1, weight=60.0, reps=10,
        set_type=SetType.warmup,
    )  # excluded
    await _set(
        db_session, sess, squat, order_index=2, weight=120.0, reps=3,
        set_type=SetType.drop,
    )  # excluded

    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    by = _by_muscle(rows)
    # Only the one normal set counts.
    assert by["quadriceps"].set_count == 1
    assert by["quadriceps"].volume_load == pytest.approx(700.0)


async def test_excludes_sets_outside_window(db_session) -> None:
    alice = await _user(db_session)
    curl = await _exercise(
        db_session, "Curl", [(Muscle.biceps, MuscleRole.primary)]
    )
    recent = await _session(db_session, alice, started_at=NOW - timedelta(days=3))
    old = await _session(db_session, alice, started_at=NOW - timedelta(days=40))
    await _set(db_session, recent, curl, order_index=0, weight=20.0, reps=10)  # 200
    await _set(db_session, old, curl, order_index=0, weight=99.0, reps=99)  # outside

    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    by = _by_muscle(rows)
    assert by["biceps"].set_count == 1
    assert by["biceps"].volume_load == pytest.approx(200.0)


async def test_window_is_inclusive_of_recent_and_respects_weeks_param(db_session) -> None:
    alice = await _user(db_session)
    curl = await _exercise(
        db_session, "Curl", [(Muscle.biceps, MuscleRole.primary)]
    )
    # A set 10 days ago: inside a 2-week window, outside a 1-week window.
    sess = await _session(db_session, alice, started_at=NOW - timedelta(days=10))
    await _set(db_session, sess, curl, order_index=0, weight=20.0, reps=10)

    two_wk = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=2)
    one_wk = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=1)
    assert _by_muscle(two_wk)["biceps"].set_count == 1
    assert one_wk == []


async def test_only_queried_user(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    press = await _exercise(
        db_session, "Press", [(Muscle.shoulders, MuscleRole.primary)]
    )
    a_sess = await _session(db_session, alice, started_at=NOW - timedelta(days=1))
    b_sess = await _session(db_session, bob, started_at=NOW - timedelta(days=1))
    await _set(db_session, a_sess, press, order_index=0, weight=50.0, reps=8)  # 400
    await _set(db_session, b_sess, press, order_index=0, weight=60.0, reps=8)  # bob's

    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    by = _by_muscle(rows)
    # Only Alice's 400, not Bob's set.
    assert by["shoulders"].set_count == 1
    assert by["shoulders"].volume_load == pytest.approx(400.0)


async def test_sums_across_sessions_and_exercises_for_one_muscle(db_session) -> None:
    alice = await _user(db_session)
    # Two different chest exercises, both primary chest.
    bench = await _exercise(
        db_session, "Bench", [(Muscle.chest, MuscleRole.primary)]
    )
    fly = await _exercise(
        db_session, "Fly", [(Muscle.chest, MuscleRole.primary)]
    )
    s1 = await _session(db_session, alice, started_at=NOW - timedelta(days=1))
    s2 = await _session(db_session, alice, started_at=NOW - timedelta(days=5))
    await _set(db_session, s1, bench, order_index=0, weight=100.0, reps=5)  # 500
    await _set(db_session, s2, fly, order_index=0, weight=20.0, reps=15)    # 300

    rows = await weekly_muscle_volume(db_session, alice.id, now=NOW, weeks=4)
    by = _by_muscle(rows)
    # Chest accumulates across both sessions/exercises: 3 sets? no — 2 sets, 800.
    assert by["chest"].set_count == 2
    assert by["chest"].volume_load == pytest.approx(800.0)
