"""Block Review apply layer (ADR-0011; plan M4) — DB-integration contract.

- Two weak weeks of prescribed-but-underperformed Sessions → future
  accumulation volume drops, a versioned receipt exists, the gate stops an
  immediate re-run.
- Chronic slot failure → the slot is pinned to a Swap-ranked replacement and
  the daily Recommendation honours the pin.
- Block over → a successor Program is generated (parent-linked, achieved
  volume as the new week-1 start, days/week stepped down when the block's
  day-completion was poor).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.exercise import Muscle
from app.models.gym_profile import GymProfile
from app.models.prescription import Prescription, PrescriptionSource
from app.models.program import ProgramRevision, ProgramStatus, RevisionTrigger
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.services.program_query import active_program
from app.services.seed_principles import seed_principles
from app.services.review_query import evaluate_active_program

from tests.test_program_recommendation_api import _program
from tests.test_swap_exclusions_api import _exercise

NOW = datetime.now(timezone.utc)


async def _user(db, email="alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _prescribed_session(
    db,
    user,
    program,
    *,
    started_at,
    exercise,
    muscle: str,
    prescribed_sets: int,
    performed_sets: int,
    reps_target: int = 8,
    performed_reps: int = 8,
    rpe: float | None = None,
    day_index: int = 0,
):
    """A finished Session with its Prescription and performed Sets."""
    session = TrainingSession(
        user_id=user.id,
        started_at=started_at,
        ended_at=started_at + timedelta(hours=1),
    )
    db.add(session)
    await db.flush()
    db.add(
        Prescription(
            session_id=session.id,
            user_id=user.id,
            program_id=program.id,
            program_version=program.version,
            day_index=day_index,
            source=PrescriptionSource.program,
            slots=[
                {
                    "exercise_id": str(exercise.id),
                    "muscle": muscle,
                    "target_sets": prescribed_sets,
                    "target_reps": reps_target,
                    "target_weight_kg": 60.0,
                }
            ],
        )
    )
    for i in range(performed_sets):
        db.add(
            TrainingSet(
                session_id=session.id,
                exercise_id=exercise.id,
                order_index=i,
                weight_kg=60.0,
                reps=performed_reps,
                rpe=rpe,
                set_type=SetType.normal,
            )
        )
    await db.flush()
    return session


async def test_two_weak_weeks_cut_future_volume_with_receipt(db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    program = await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=2, days=1),  # week 3 now; weeks 1-2 complete
        volume_top=12,
    )

    # Weeks 1 and 2: prescribed 12, performed 8 (67% — weak, not severe).
    for week_start in (program.created_at, program.created_at + timedelta(weeks=1)):
        await _prescribed_session(
            db_session,
            alice,
            program,
            started_at=week_start + timedelta(days=1),
            exercise=bench,
            muscle="chest",
            prescribed_sets=12,
            performed_sets=8,
        )

    receipts = await evaluate_active_program(db_session, alice.id, now=NOW)
    assert len(receipts) == 1
    assert receipts[0]["lever"] == "volume"
    assert receipts[0]["muscle"] == "chest"
    assert receipts[0]["to"] == receipts[0]["from"] - 1
    assert "two weeks" in receipts[0]["reason"]

    # Future accumulation weeks dropped by 1; version bumped; revision stored.
    current_week = 3
    for row in program.muscle_volumes:
        if row.is_deload:
            continue
        expected = 11 if row.week > current_week else 12
        assert row.target_sets == expected, f"week {row.week}"
    assert program.version == 2
    revs = (await db_session.execute(select(ProgramRevision))).scalars().all()
    assert len(revs) == 1
    assert revs[0].trigger == RevisionTrigger.continuous_review

    # The gate: an immediate second evaluation changes nothing.
    assert await evaluate_active_program(db_session, alice.id, now=NOW) == []
    assert program.version == 2


async def test_chronic_slot_failure_rotates_to_swap_ranked_replacement(
    db_session,
) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    fly = await _exercise(
        db_session, "Dumbbell Fly", [Muscle.chest], equipment="dumbbell"
    )
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell", "dumbbell"]))
    program = await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=2, days=1),
        volume_top=12,
    )

    # Three consecutive Sessions failing hard (RIR 0, reps short) on the SAME
    # movement, spread over the two complete weeks; volume completion stays
    # high (12/12) so ONLY the rotation should fire.
    starts = [
        program.created_at + timedelta(days=1),
        program.created_at + timedelta(days=4),
        program.created_at + timedelta(weeks=1, days=1),
    ]
    for started in starts:
        await _prescribed_session(
            db_session,
            alice,
            program,
            started_at=started,
            exercise=bench,
            muscle="chest",
            prescribed_sets=12,
            performed_sets=12,
            reps_target=8,
            performed_reps=5,  # short of target...
            rpe=10.0,  # ...at RIR 0 — hard failure
        )

    receipts = await evaluate_active_program(db_session, alice.id, now=NOW)
    rotations = [r for r in receipts if r["lever"] == "rotation"]
    assert len(rotations) == 1
    assert rotations[0]["from"] == str(bench.id)
    assert rotations[0]["to"] == str(fly.id)  # the only shared-muscle equivalent

    day = program.days[0]
    assert day.slots[0]["exercise_id"] == str(fly.id)

    # The daily Recommendation honours the pin.
    from app.services.recommendation_query import recommend_today

    recommendation, program_rec = await recommend_today(
        db_session, alice.id, now=NOW
    )
    assert [e.name for e in recommendation.exercises] == ["Dumbbell Fly"]


async def test_block_end_generates_successor_from_achieved_volume(db_session) -> None:
    await seed_principles(db_session)  # the successor generator composes from the KB
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    # 4+1 weeks, created 6 weeks ago → the block is over.
    program = await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=6),
        mesocycle_weeks=4,
        volume_top=12,
    )
    # Good attendance: 2 finished Sessions/week for 4 weeks (expected 1/wk).
    # Last accumulation week (week 4): performed 11 sets — the achieved start.
    for wk in range(4):
        week_start = program.created_at + timedelta(weeks=wk)
        await _prescribed_session(
            db_session,
            alice,
            program,
            started_at=week_start + timedelta(days=1),
            exercise=bench,
            muscle="chest",
            prescribed_sets=12,
            performed_sets=11,
        )

    receipts = await evaluate_active_program(db_session, alice.id, now=NOW)
    levers = {r["lever"] for r in receipts}
    assert "block_succession" in levers
    assert "days_per_week" not in levers  # attendance was fine

    successor = await active_program(db_session, alice.id)
    assert successor is not None and successor.id != program.id
    assert successor.parent_program_id == program.id
    assert program.status == ProgramStatus.archived

    week1 = {
        v.muscle: v.target_sets
        for v in successor.muscle_volumes
        if v.week == 1 and not v.is_deload
    }
    assert week1.get("chest") == 11  # starts where the user actually is

    revs = (
        (
            await db_session.execute(
                select(ProgramRevision).where(
                    ProgramRevision.program_id == successor.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(revs) == 1 and revs[0].trigger == RevisionTrigger.block_review


async def test_revisions_and_adherence_endpoints(db_session) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.dependencies import get_current_user
    from app.database import get_db
    from app.main import app

    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    program = await _program(
        db_session,
        alice,
        days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=2, days=1),
        volume_top=12,
    )
    for week_start in (program.created_at, program.created_at + timedelta(weeks=1)):
        await _prescribed_session(
            db_session,
            alice,
            program,
            started_at=week_start + timedelta(days=1),
            exercise=bench,
            muscle="chest",
            prescribed_sets=12,
            performed_sets=8,
        )
    await evaluate_active_program(db_session, alice.id, now=NOW)

    async def _override_db():
        yield db_session

    async def _override_user():
        return alice

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            revs = (await ac.get("/api/programs/active/revisions")).json()
            assert len(revs) == 1
            assert revs[0]["version"] == 2
            assert revs[0]["trigger"] == "continuous_review"
            assert revs[0]["changes"][0]["lever"] == "volume"

            weeks = (await ac.get("/api/programs/active/adherence")).json()
            assert weeks[0]["current"] is True  # newest first, current flagged
            complete = [w for w in weeks if not w["current"] and w["sessions"] > 0]
            assert complete
            chest = complete[0]["muscles"][0]
            assert chest["muscle"] == "chest"
            assert chest["prescribed_sets"] == 12
            assert chest["performed_sets"] == 8
            assert abs(chest["completion"] - 0.667) < 0.01
    finally:
        app.dependency_overrides.clear()
