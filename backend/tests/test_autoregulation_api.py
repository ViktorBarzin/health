"""Autoregulation wiring — today's Program day adjusts on Readiness + Recovery.

The pure autoregulator's numeric behaviour is pinned in
:mod:`tests.test_autoregulation`; here we assert the WIRING through the active-
Program recommendation path and the ``/api/recommendations/today`` endpoint:

* poor biometric **Readiness** (seeded via ``health_records``) trims the day's
  prescribed sets within the Program's Principle volume band, with the reason
  surfaced;
* strong Readiness keeps the planned volume (never above the ceiling);
* a user with no biometric history gets the planned day, unadjusted;
* the deload week's reduced volume is never *raised* by autoregulation;
* sustained low Readiness flags an early deload.
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
from app.models.health_record import HealthRecord
from app.models.program import Program, ProgramDay, ProgramMuscleVolume, ProgramStatus
from app.models.user import User
from app.services.program_recommendation import recommend_from_program

NOW = datetime(2026, 6, 13, 7, 0, 0, tzinfo=timezone.utc)


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


async def _ramping_program(db, user: User, *, created_at: datetime) -> Program:
    """A 1-day chest Program whose chest volume RAMPS 6→12 sets, deload 4.

    The ramp gives autoregulation a real band to move within (per-session floor <
    ceiling), unlike a flat profile.
    """
    mesocycle_weeks = 4
    total_weeks = mesocycle_weeks + 1
    prog = Program(
        user_id=user.id,
        name="Ramp Program",
        preset_key=None,
        goal="bulk",
        experience="intermediate",
        days_per_week=1,
        session_minutes=70,
        mesocycle_weeks=mesocycle_weeks,
        total_weeks=total_weeks,
        deload_week=total_weeks,
        rep_range_low=6,
        rep_range_high=12,
        effort_rir=3,
        status=ProgramStatus.active,
        provenance={},
        created_at=created_at,
    )
    prog.days = [ProgramDay(day_index=0, name="Chest", slots=[{"muscle": "chest"}])]
    ramp = [6, 8, 10, 12]
    vols = [
        ProgramMuscleVolume(muscle="chest", week=wk, target_sets=ramp[wk - 1], is_deload=False)
        for wk in range(1, mesocycle_weeks + 1)
    ]
    vols.append(
        ProgramMuscleVolume(muscle="chest", week=total_weeks, target_sets=4, is_deload=True)
    )
    prog.muscle_volumes = vols
    db.add(prog)
    await db.flush()
    return prog


async def _gym(db, user: User) -> None:
    db.add(
        GymProfile(
            user_id=user.id,
            bar_weights_kg=[20.0],
            plate_weights_kg=[1.25, 2.5, 5.0, 10.0, 20.0],
            equipment=["barbell"],
        )
    )
    await db.flush()


async def _hrv(db, user: User, *, days_ago: float, value: float) -> None:
    db.add(
        HealthRecord(
            time=NOW - timedelta(days=days_ago),
            user_id=user.id,
            metric_type="HeartRateVariabilitySDNN",
            value=value,
            unit="ms",
        )
    )


async def _seed_hrv_baseline(db, user: User, *, recent: float) -> None:
    for d in range(2, 16):
        await _hrv(db, user, days_ago=d, value=55.0)
    await _hrv(db, user, days_ago=0.3, value=recent)


def _chest_sets(rec) -> int:
    return next(
        e.target_sets
        for e in rec.recommendation.exercises
        if "chest" in e.primary_muscles
    )


# --------------------------------------------------------------------------- #
# Direct service: poor readiness trims; strong keeps; none = planned
# --------------------------------------------------------------------------- #


async def test_poor_readiness_trims_the_program_day(db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    # Mid-mesocycle (week ~3 → planned ~10 chest sets), evaluated at NOW.
    program = await _ramping_program(
        db_session, user, created_at=NOW - timedelta(weeks=2, days=3)
    )
    await db_session.flush()

    healthy = await recommend_from_program(
        db_session, user.id, program, now=NOW, readiness=85.0
    )
    poor = await recommend_from_program(
        db_session, user.id, program, now=NOW, readiness=35.0
    )
    assert _chest_sets(poor) < _chest_sets(healthy)
    assert poor.autoregulation is not None
    assert poor.autoregulation.adjusted is True
    assert "35" in poor.autoregulation.reason
    # Never below the per-session Principle floor (week-1 floor = 6 sets / 1 day).
    assert _chest_sets(poor) >= 6


async def test_no_readiness_leaves_the_planned_day(db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    program = await _ramping_program(
        db_session, user, created_at=NOW - timedelta(weeks=2, days=3)
    )
    await db_session.flush()

    none = await recommend_from_program(
        db_session, user.id, program, now=NOW, readiness=None
    )
    assert none.autoregulation is not None
    assert none.autoregulation.adjusted is False


async def test_strong_readiness_stays_within_ceiling(db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    # Last accumulation week → planned at the ramp top (12), the per-session ceiling.
    program = await _ramping_program(
        db_session, user, created_at=NOW - timedelta(weeks=3, days=1)
    )
    await db_session.flush()

    strong = await recommend_from_program(
        db_session, user.id, program, now=NOW, readiness=95.0
    )
    # Already at the ceiling → a strong-readiness bump can't exceed it.
    assert _chest_sets(strong) <= 12


async def test_strong_readiness_does_not_raise_the_deload_week(db_session) -> None:
    # CRUX (review Finding A): land a STRONG, fresh day ON the scheduled deload
    # week (created 4 weeks ago → week 5 = deload, chest cut to 4 sets). A great
    # subjective day must NOT bump a planned deload back up.
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    program = await _ramping_program(
        db_session, user, created_at=NOW - timedelta(weeks=4, days=1)
    )
    await db_session.flush()

    strong = await recommend_from_program(
        db_session, user.id, program, now=NOW, readiness=95.0
    )
    assert strong.is_deload is True
    # The deload sits at 4 sets — strong readiness leaves it there, never raises it.
    assert _chest_sets(strong) == 4
    assert strong.autoregulation is not None
    assert strong.autoregulation.adjusted is False


# --------------------------------------------------------------------------- #
# Endpoint: the reason + readiness surface in /today
# --------------------------------------------------------------------------- #


async def test_today_endpoint_surfaces_autoregulation(client, db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    # Created recently so "today" lands mid-ramp; seed a depressed recent HRV.
    await _ramping_program(
        db_session, user, created_at=datetime.now(timezone.utc) - timedelta(weeks=2)
    )
    # Baseline HRV with a low recent reading → poor readiness today.
    now = datetime.now(timezone.utc)
    for d in range(2, 16):
        db_session.add(
            HealthRecord(
                time=now - timedelta(days=d),
                user_id=user.id,
                metric_type="HeartRateVariabilitySDNN",
                value=55.0,
                unit="ms",
            )
        )
    db_session.add(
        HealthRecord(
            time=now - timedelta(hours=6),
            user_id=user.id,
            metric_type="HeartRateVariabilitySDNN",
            value=28.0,
            unit="ms",
        )
    )
    await db_session.flush()

    client.set_user(user)
    resp = await client.get("/api/recommendations/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "program"
    auto = body["program"]["autoregulation"]
    assert auto is not None
    assert auto["adjusted"] is True
    assert auto["readiness"] is not None and auto["readiness"] < 50.0
    assert auto["reason"]


async def test_today_endpoint_no_biometrics_unadjusted(client, db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _ramping_program(
        db_session, user, created_at=datetime.now(timezone.utc) - timedelta(weeks=2)
    )
    await db_session.flush()

    client.set_user(user)
    body = (await client.get("/api/recommendations/today")).json()
    auto = body["program"]["autoregulation"]
    assert auto["adjusted"] is False
    assert auto["readiness"] is None
    assert auto["early_deload"] is False


# --------------------------------------------------------------------------- #
# Early deload on sustained low signals
# --------------------------------------------------------------------------- #


async def test_sustained_low_readiness_flags_early_deload(client, db_session) -> None:
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _ramping_program(
        db_session, user, created_at=datetime.now(timezone.utc) - timedelta(weeks=2)
    )
    now = datetime.now(timezone.utc)
    # A high baseline weeks back, then a run of depressed recent days → each of the
    # last several days reads low → early deload trips.
    for d in range(10, 30):
        db_session.add(
            HealthRecord(
                time=now - timedelta(days=d),
                user_id=user.id,
                metric_type="HeartRateVariabilitySDNN",
                value=60.0,
                unit="ms",
            )
        )
    for d in range(0, 6):
        db_session.add(
            HealthRecord(
                time=now - timedelta(days=d, hours=6),
                user_id=user.id,
                metric_type="HeartRateVariabilitySDNN",
                value=25.0,
                unit="ms",
            )
        )
    await db_session.flush()

    client.set_user(user)
    body = (await client.get("/api/recommendations/today")).json()
    assert body["program"]["autoregulation"]["early_deload"] is True


async def test_early_deload_actually_cuts_the_prescription(client, db_session) -> None:
    # CRUX (review Finding B): a sustained-low stretch doesn't just SET a flag —
    # today's prescription is cut to DELOAD magnitude (chest 4 sets, the program's
    # deload-week depth), deeper than the normal poor-readiness floor (6). Program
    # created 2 weeks ago → week 3 (planned chest 10).
    user = await _user(db_session)
    await _gym(db_session, user)
    await _exercise(db_session, "Bench Press", Muscle.chest)
    await _ramping_program(
        db_session, user, created_at=datetime.now(timezone.utc) - timedelta(weeks=2)
    )
    now = datetime.now(timezone.utc)
    for d in range(10, 30):
        db_session.add(
            HealthRecord(
                time=now - timedelta(days=d),
                user_id=user.id,
                metric_type="HeartRateVariabilitySDNN",
                value=60.0,
                unit="ms",
            )
        )
    for d in range(0, 6):
        db_session.add(
            HealthRecord(
                time=now - timedelta(days=d, hours=6),
                user_id=user.id,
                metric_type="HeartRateVariabilitySDNN",
                value=25.0,
                unit="ms",
            )
        )
    await db_session.flush()

    client.set_user(user)
    body = (await client.get("/api/recommendations/today")).json()
    auto = body["program"]["autoregulation"]
    assert auto["early_deload"] is True
    chest = next(e for e in body["exercises"] if "chest" in e["primary_muscles"])
    # Cut to the deload-week depth (4), below the normal per-readiness floor (6).
    assert chest["target_sets"] == 4
    assert "deload" in auto["reason"].lower()
