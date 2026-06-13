"""Budget API + query layer: the Goal-driven, self-calibrating daily target (#23).

End-to-end over the real cores + DB:

- ``GET /api/nutrition/budget`` reconciles logged Diary intake against the
  de-noised BodyMass trend to *measure* TDEE (``method='adaptive'``), and sizes the
  target to the active Program's Goal (the single Goal, ADR-0004).
- BodyMass stored in pounds is normalised to kg before the trend.
- Protein comes from the seeded ``protein-intake`` Principle's g/kg range.
- No active Program ⇒ the Goal defaults to ``maintain``.
- No bodyweight at all ⇒ an honest ``insufficient_data`` result, no fabricated
  number; bodyweight but no intake/trend ⇒ a labelled ``estimated`` fallback.
- The Budget is per-user scoped (one user's weight/diary never leaks into another's).
"""

import datetime as dt
import uuid
from datetime import timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.diary_entry import DiaryEntry, Meal
from app.models.food import Food
from app.models.health_record import HealthRecord
from app.models.principle import (
    EvidenceGrade,
    Principle,
    PrincipleCategory,
)
from app.models.program import Program, ProgramStatus
from app.models.user import User

NOW = dt.datetime.now(timezone.utc)


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_food(db, name: str, *, calories, protein_g, carbs_g, fat_g) -> Food:
    food = Food(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=None,
        serving_size=1.0,
        serving_unit="serving",
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        source="generic",
    )
    db.add(food)
    await db.flush()
    return food


async def _log_daily_calories(
    db, user, food, *, kcal_per_day: float, days: int
) -> None:
    """Log one Diary Entry per day for ``days`` days ending today, at ``kcal_per_day``.

    ``food`` is 1 kcal/serving so quantity == calories; one entry/day is enough for
    the average.
    """
    for back in range(days):
        day = (NOW - dt.timedelta(days=back)).date()
        db.add(
            DiaryEntry(
                user_id=user.id,
                food_id=food.id,
                entry_date=day,
                meal=Meal.lunch,
                quantity=kcal_per_day,
            )
        )
    await db.flush()


async def _log_bodyweight(
    db, user, *, start_kg: float, daily_delta_kg: float, days: int, unit: str = "kg"
) -> None:
    """A daily BodyMass series: ``start_kg`` ``days`` ago, +``daily_delta_kg``/day.

    Stored in ``unit`` (kg or lb) — the value is converted to that unit so the
    query layer's normalisation is exercised.
    """
    factor = 1.0 if unit == "kg" else 1.0 / 0.45359237
    for i in range(days):
        at = NOW - dt.timedelta(days=days - 1 - i)
        kg = start_kg + daily_delta_kg * i
        db.add(
            HealthRecord(
                time=at,
                user_id=user.id,
                metric_type="BodyMass",
                value=kg * factor,
                unit=unit,
            )
        )
    await db.flush()


async def _seed_protein_principle(db) -> None:
    db.add(
        Principle(
            key="protein-intake",
            statement="Aim for 1.6-2.2 g/kg/day of protein.",
            category=PrincipleCategory.nutrition,
            params={"protein_g_per_kg_per_day": {"min": 1.6, "max": 2.2, "unit": "g/kg/day"}},
            goals=[],
            experience_levels=[],
            evidence_grade=EvidenceGrade.A,
        )
    )
    await db.flush()


async def _make_active_program(db, user, *, goal: str) -> Program:
    prog = Program(
        user_id=user.id,
        name=f"{goal} program",
        goal=goal,
        experience="intermediate",
        days_per_week=4,
        session_minutes=60,
        mesocycle_weeks=4,
        total_weeks=5,
        deload_week=5,
        rep_range_low=6,
        rep_range_high=12,
        effort_rir=2,
        status=ProgramStatus.active,
        provenance={},
    )
    db.add(prog)
    await db.flush()
    return prog


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


# --------------------------------------------------------------------------- #
# Adaptive: TDEE measured from intake + weight trend, target driven by the Goal
# --------------------------------------------------------------------------- #


async def test_adaptive_budget_from_intake_and_weight_trend(client, db_session) -> None:
    """Eating ~2500 while gaining ~0.7 kg/wk on a bulk ⇒ adaptive TDEE + a surplus."""
    user = await _make_user(db_session, "bulk@example.com")
    await _seed_protein_principle(db_session)
    await _make_active_program(db_session, user, goal="bulk")
    food = await _make_food(db_session, "kcal", calories=1.0, protein_g=0.0, carbs_g=0.25, fat_g=0.0)
    await _log_daily_calories(db_session, user, food, kcal_per_day=2500.0, days=28)
    # +0.1 kg/day ≈ +0.7 kg/week.
    await _log_bodyweight(db_session, user, start_kg=80.0, daily_delta_kg=0.1, days=28)
    client.set_user(user)

    resp = await client.get("/api/nutrition/budget")
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient_data"] is False
    assert body["method"] == "adaptive"
    assert body["goal"] == "bulk"
    # TDEE ≈ 2500 − 0.7*7700/7 ≈ 1730; target is a surplus *above* that TDEE.
    assert body["tdee_kcal"] == pytest.approx(2500.0 - 0.7 * 7700 / 7, abs=120.0)
    assert body["target_kcal"] > body["tdee_kcal"]
    # Protein from the Principle (1.6-2.2 g/kg) on the ~82 kg current weight.
    assert body["protein_g"] is not None and body["protein_g"] > 0
    # The trend is surfaced and reads a clear gain.
    assert body["trend"]["rate_kg_per_week"] == pytest.approx(0.7, abs=0.2)
    assert body["trend"]["true_weight_kg"] == pytest.approx(82.0, abs=1.5)
    assert body["target_rate_kg_per_week"] > 0  # a bulk aims to gain


async def test_bodyweight_in_pounds_is_normalised_to_kg(client, db_session) -> None:
    """BodyMass stored in lb is converted — the true weight reads in kg, not lb."""
    user = await _make_user(db_session, "imperial@example.com")
    await _seed_protein_principle(db_session)
    # 176 lb ≈ 79.8 kg, flat.
    await _log_bodyweight(db_session, user, start_kg=79.8, daily_delta_kg=0.0, days=20, unit="lb")
    food = await _make_food(db_session, "kcal", calories=1.0, protein_g=0.0, carbs_g=0.25, fat_g=0.0)
    await _log_daily_calories(db_session, user, food, kcal_per_day=2400.0, days=20)
    client.set_user(user)

    resp = await client.get("/api/nutrition/budget")
    body = resp.json()
    assert body["trend"]["true_weight_kg"] == pytest.approx(79.8, abs=1.0)
    # Flat weight ⇒ TDEE ≈ intake.
    assert body["tdee_kcal"] == pytest.approx(2400.0, abs=60.0)


# --------------------------------------------------------------------------- #
# Goal defaulting + estimated/insufficient fallbacks
# --------------------------------------------------------------------------- #


async def test_no_active_program_defaults_goal_to_maintain(client, db_session) -> None:
    """With no Program the Goal is maintain, so the target sits at maintenance."""
    user = await _make_user(db_session, "noprog@example.com")
    await _seed_protein_principle(db_session)
    await _log_bodyweight(db_session, user, start_kg=75.0, daily_delta_kg=0.0, days=20)
    food = await _make_food(db_session, "kcal", calories=1.0, protein_g=0.0, carbs_g=0.25, fat_g=0.0)
    await _log_daily_calories(db_session, user, food, kcal_per_day=2300.0, days=20)
    client.set_user(user)

    resp = await client.get("/api/nutrition/budget")
    body = resp.json()
    assert body["goal"] == "maintain"
    assert body["target_kcal"] == pytest.approx(body["tdee_kcal"], abs=1.0)


async def test_no_bodyweight_is_insufficient_data(client, db_session) -> None:
    """No BodyMass history at all ⇒ insufficient_data, null numbers (no fabrication)."""
    user = await _make_user(db_session, "nodata@example.com")
    await _seed_protein_principle(db_session)
    food = await _make_food(db_session, "kcal", calories=1.0, protein_g=0.0, carbs_g=0.25, fat_g=0.0)
    await _log_daily_calories(db_session, user, food, kcal_per_day=2200.0, days=10)
    client.set_user(user)

    resp = await client.get("/api/nutrition/budget")
    body = resp.json()
    assert body["insufficient_data"] is True
    assert body["target_kcal"] is None
    assert body["tdee_kcal"] is None


async def test_weight_but_no_intake_is_estimated(client, db_session) -> None:
    """Bodyweight but no logged intake ⇒ a labelled 'estimated' fallback budget."""
    user = await _make_user(db_session, "weightonly@example.com")
    await _seed_protein_principle(db_session)
    await _log_bodyweight(db_session, user, start_kg=80.0, daily_delta_kg=0.05, days=20)
    client.set_user(user)

    resp = await client.get("/api/nutrition/budget")
    body = resp.json()
    assert body["insufficient_data"] is False
    assert body["method"] == "estimated"
    assert body["tdee_kcal"] is not None
    assert body["target_kcal"] is not None


# --------------------------------------------------------------------------- #
# Per-user scoping
# --------------------------------------------------------------------------- #


async def test_budget_is_scoped_per_user(client, db_session) -> None:
    """Bob's weight/diary never feed Alice's Budget."""
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await _seed_protein_principle(db_session)
    # Only Bob has data.
    await _log_bodyweight(db_session, bob, start_kg=90.0, daily_delta_kg=0.0, days=20)
    food = await _make_food(db_session, "kcal", calories=1.0, protein_g=0.0, carbs_g=0.25, fat_g=0.0)
    await _log_daily_calories(db_session, bob, food, kcal_per_day=3000.0, days=20)

    client.set_user(alice)
    alice_budget = (await client.get("/api/nutrition/budget")).json()
    assert alice_budget["insufficient_data"] is True

    client.set_user(bob)
    bob_budget = (await client.get("/api/nutrition/budget")).json()
    assert bob_budget["insufficient_data"] is False
    assert bob_budget["tdee_kcal"] == pytest.approx(3000.0, abs=60.0)
