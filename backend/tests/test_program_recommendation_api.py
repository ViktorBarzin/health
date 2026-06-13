"""The active-Program path of the daily Recommendation (#13, ADR-0004).

Pins the integration the spec calls "CRUCIAL": when a Program is active, today's
Recommendation is drawn from the Program (its next due day, slots filled via the
Progression core, constrained by the Gym Profile) — overriding the freestyle
generator; with no active Program it still freestyles. Also: starting today's
Program workout instantiates a Session (the #11 path), and the deload week reduces
volume.
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
from app.models.program import Program, ProgramDay, ProgramMuscleVolume, ProgramStatus
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


async def _program(
    db,
    user: User,
    *,
    days: list[tuple[str, list[Muscle]]],
    created_at: datetime,
    mesocycle_weeks: int = 4,
    rep_low: int = 6,
    rep_high: int = 12,
    volume_top: int = 12,
    deload_sets: int = 6,
) -> Program:
    """Persist a minimal active Program directly (bypassing the generator)."""
    total_weeks = mesocycle_weeks + 1
    prog = Program(
        user_id=user.id,
        name="Test Program",
        preset_key=None,
        goal="bulk",
        experience="intermediate",
        days_per_week=len(days),
        session_minutes=70,
        mesocycle_weeks=mesocycle_weeks,
        total_weeks=total_weeks,
        deload_week=total_weeks,
        rep_range_low=rep_low,
        rep_range_high=rep_high,
        effort_rir=3,
        status=ProgramStatus.active,
        provenance={},
        created_at=created_at,
    )
    prog.days = [
        ProgramDay(
            day_index=i,
            name=name,
            slots=[{"muscle": m.value} for m in muscles],
        )
        for i, (name, muscles) in enumerate(days)
    ]
    # Build the per-(muscle, week) volume: flat top across the meso, drop on deload.
    muscles = {m for _, ms in days for m in ms}
    vols = []
    for m in muscles:
        for wk in range(1, mesocycle_weeks + 1):
            vols.append(
                ProgramMuscleVolume(
                    muscle=m.value, week=wk, target_sets=volume_top, is_deload=False
                )
            )
        vols.append(
            ProgramMuscleVolume(
                muscle=m.value, week=total_weeks, target_sets=deload_sets,
                is_deload=True,
            )
        )
    prog.muscle_volumes = vols
    db.add(prog)
    await db.flush()
    return prog


# --------------------------------------------------------------------------- #
# Active Program OVERRIDES freestyle
# --------------------------------------------------------------------------- #


async def test_today_uses_program_when_active(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc),
    )
    client.set_user(alice)

    resp = await client.get("/api/recommendations/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "program"
    assert body["program"]["day_name"] == "Push"
    assert body["program"]["week"] == 1
    # The Program's chest slot was filled with the chest Exercise.
    assert any("chest" in e["primary_muscles"] for e in body["exercises"])


async def test_today_freestyles_when_no_active_program(client, db_session) -> None:
    # No Program → the freestyle path (source freestyle), even with history.
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", Muscle.chest)
    sess = TrainingSession(
        user_id=alice.id,
        started_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db_session.add(sess)
    await db_session.flush()
    db_session.add(
        TrainingSet(
            session_id=sess.id, exercise_id=bench.id, order_index=0,
            weight_kg=60.0, reps=10, rpe=8.0, set_type=SetType.normal,
        )
    )
    await db_session.flush()
    client.set_user(alice)

    resp = await client.get("/api/recommendations/today")
    assert resp.status_code == 200
    assert resp.json()["source"] == "freestyle"
    assert resp.json()["program"] is None


async def test_program_recommendation_respects_gym_profile(client, db_session) -> None:
    # The chest slot must be filled by a dumbbell movement when the user has no
    # barbell, even though a barbell chest Exercise exists.
    alice = await _user(db_session)
    await _exercise(db_session, "Barbell Bench", Muscle.chest, equipment="barbell")
    await _exercise(db_session, "DB Press", Muscle.chest, equipment="dumbbell")
    db_session.add(GymProfile(user_id=alice.id, equipment=["dumbbell"]))
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc),
    )
    await db_session.flush()
    client.set_user(alice)

    body = (await client.get("/api/recommendations/today")).json()
    names = {e["name"] for e in body["exercises"]}
    assert "DB Press" in names
    assert "Barbell Bench" not in names


async def test_program_recommendation_progresses_off_history(client, db_session) -> None:
    # A trained chest movement is progressed off its last working set (top of the
    # rep range with reserve → +load, reset reps to the bottom).
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", Muscle.chest)
    sess = TrainingSession(
        user_id=alice.id, started_at=datetime.now(timezone.utc) - timedelta(days=3)
    )
    db_session.add(sess)
    await db_session.flush()
    db_session.add(
        TrainingSet(
            session_id=sess.id, exercise_id=bench.id, order_index=0,
            weight_kg=60.0, reps=12, rpe=8.0, set_type=SetType.normal,
        )
    )
    await db_session.flush()
    # Program created AFTER the logged session so it isn't counted as a Program day.
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc),
        rep_low=8,
        rep_high=12,
    )
    client.set_user(alice)

    body = (await client.get("/api/recommendations/today")).json()
    bench_item = next(e for e in body["exercises"] if e["name"] == "Bench Press")
    # 60×12 @ RIR2, range 8-12 → +2.5kg, reset to 8 reps.
    assert bench_item["target_weight_kg"] == 62.5
    assert bench_item["target_reps"] == 8


# --------------------------------------------------------------------------- #
# Deload week reduces volume
# --------------------------------------------------------------------------- #


async def test_deload_week_reduces_prescribed_sets(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    # Created 5 weeks ago → week 5 = the deload (mesocycle 4 + 1).
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc) - timedelta(weeks=5),
        mesocycle_weeks=4,
        volume_top=12,
        deload_sets=6,
    )
    client.set_user(alice)

    body = (await client.get("/api/recommendations/today")).json()
    assert body["program"]["is_deload"] is True
    assert body["program"]["week"] == 5
    # The chest slot is trained once/week here, so per-session sets == the week's
    # target: 6 on deload (vs 12 on a normal week).
    chest_item = next(e for e in body["exercises"] if "chest" in e["primary_muscles"])
    assert chest_item["target_sets"] == 6


async def test_non_deload_week_uses_full_volume(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc),  # week 1, accumulation
        volume_top=12,
        deload_sets=6,
    )
    client.set_user(alice)

    body = (await client.get("/api/recommendations/today")).json()
    assert body["program"]["is_deload"] is False
    chest_item = next(e for e in body["exercises"] if "chest" in e["primary_muscles"])
    assert chest_item["target_sets"] == 12


# --------------------------------------------------------------------------- #
# Next due day rotates with logged Sessions
# --------------------------------------------------------------------------- #


async def test_next_due_day_advances_with_sessions(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _exercise(db_session, "Squat", Muscle.quadriceps)
    created = datetime.now(timezone.utc) - timedelta(hours=1)
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest]), ("Legs", [Muscle.quadriceps])],
        created_at=created,
    )
    client.set_user(alice)

    # No Sessions yet → day 0 (Push).
    first = (await client.get("/api/recommendations/today")).json()
    assert first["program"]["day_index"] == 0
    assert first["program"]["day_name"] == "Push"

    # Log one Session after the Program started → next due advances to day 1 (Legs).
    sess = TrainingSession(user_id=alice.id, started_at=datetime.now(timezone.utc))
    db_session.add(sess)
    await db_session.flush()

    second = (await client.get("/api/recommendations/today")).json()
    assert second["program"]["day_index"] == 1
    assert second["program"]["day_name"] == "Legs"


# --------------------------------------------------------------------------- #
# Starting today's Program workout instantiates a Session (#11 path)
# --------------------------------------------------------------------------- #


async def test_start_today_instantiates_session_from_program(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=datetime.now(timezone.utc),
        volume_top=4,  # 4 sets this week, chest trained once → 4 pre-filled sets
        deload_sets=2,
    )
    client.set_user(alice)

    resp = await client.post("/api/recommendations/today/start", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_active"] is True
    assert body["set_count"] == 4
    for s in body["sets"]:
        assert s["set_type"] == "normal"
        assert s["exercise_name"] == "Bench Press"

    # It's a normal Session, fetchable via the sessions API.
    got = await client.get(f"/api/sessions/{body['id']}")
    assert got.status_code == 200
    assert got.json()["set_count"] == 4


# --------------------------------------------------------------------------- #
# GENERATOR-LEVEL deload e2e: a Program generated from the REAL KB prescribes
# fewer sets on the deload week than on week 1 (catches the "invisible deload"
# bug that hand-built-row tests missed).
# --------------------------------------------------------------------------- #


async def test_generated_program_deload_prescribes_fewer_sets_than_week_one(
    db_session,
) -> None:
    from datetime import datetime, timedelta, timezone

    from app.models.principle import ExperienceLevel, TrainingGoal
    from app.services.program_generation import QuizInput
    from app.services.program_query import create_program_from_quiz
    from app.services.program_recommendation import recommend_from_program
    from app.services.seed_principles import seed_principles

    # Seed the REAL KB and generate a real Program (no hand-built volume rows).
    await seed_principles(db_session)
    alice = await _user(db_session)
    # A chest movement so the Push day's chest slot fills.
    await _exercise(db_session, "Bench Press", Muscle.chest)

    created = datetime.now(timezone.utc)
    program = await create_program_from_quiz(
        db_session,
        alice.id,
        QuizInput(
            goal=TrainingGoal.bulk,
            experience=ExperienceLevel.intermediate,
            days_per_week=4,
            session_minutes=70,
        ),
    )
    # Sanity: the generator produced a real ramp with a deload below week 1.
    chest_week1 = next(
        v.target_sets
        for v in program.muscle_volumes
        if v.muscle == Muscle.chest.value and v.week == 1
    )
    chest_deload = next(
        v.target_sets
        for v in program.muscle_volumes
        if v.muscle == Muscle.chest.value and v.is_deload
    )
    assert chest_deload < chest_week1, (chest_deload, chest_week1)

    # Drive the Recommendation at week 1 (the day the Program started) and at the
    # deload week (created_at + (total_weeks-1) full weeks), injecting `now`. The
    # day_index is 0 both times (no Sessions logged), so it's the SAME Push day —
    # only the week differs — making the set counts directly comparable.
    week1 = await recommend_from_program(db_session, alice.id, program, now=created)
    deload_now = created + timedelta(weeks=program.total_weeks - 1)
    deload = await recommend_from_program(
        db_session, alice.id, program, now=deload_now
    )

    assert week1.is_deload is False
    assert deload.is_deload is True
    assert deload.day_name == week1.day_name  # same due day, different week

    def chest_sets(rec) -> int:
        return next(
            e.target_sets
            for e in rec.recommendation.exercises
            if "chest" in e.primary_muscles
        )

    # The CRUX: the driven Recommendation prescribes fewer chest sets on the deload
    # week than on week 1 — the deload is visible end-to-end through the generator.
    assert chest_sets(deload) < chest_sets(week1), (
        chest_sets(deload),
        chest_sets(week1),
    )
