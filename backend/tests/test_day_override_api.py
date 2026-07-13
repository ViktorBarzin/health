"""Day-type override (plan ④): "give me push day today".

`GET /api/recommendations/today` gains two optional overrides:

- `day_index=` (Program path): preview a CHOSEN Program day instead of the
  next-due one — same slot filling, same autoregulation pipeline; the Program
  pointer self-heals afterwards via the existing session-count modulo + reflow,
  so an override never corrupts the schedule. Out-of-range → 422.
- `muscles=` (freestyle path): focus the freestyle generator on the given
  muscle group(s) — only Exercises with a matching PRIMARY mover are proposed.
  Unknown muscle names → 422.

Starting an overridden preview goes through the explicit WYSIWYG /start path
the client already uses for Swaps, so no start-side override exists.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Muscle
from app.models.gym_profile import GymProfile
from app.models.user import User

from tests.test_program_recommendation_api import _program
from tests.test_swap_exclusions_api import _exercise, _log_history


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


async def test_program_day_override_previews_the_chosen_day(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", [Muscle.chest])
    await _exercise(db_session, "Back Squat", [Muscle.quadriceps])
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    await _program(
        db_session,
        alice,
        days=[("Push Day", [Muscle.chest]), ("Leg Day", [Muscle.quadriceps])],
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    client.set_user(alice)

    # Next due is day 0 (no Sessions since the Program started).
    today = (await client.get("/api/recommendations/today")).json()
    assert today["program"]["day_name"] == "Push Day"

    # Override to day 1: leg day, same program context pipeline.
    overridden = (
        await client.get("/api/recommendations/today", params={"day_index": 1})
    ).json()
    assert overridden["source"] == "program"
    assert overridden["program"]["day_name"] == "Leg Day"
    assert overridden["program"]["day_index"] == 1
    assert [e["name"] for e in overridden["exercises"]] == ["Back Squat"]


async def test_program_day_override_out_of_range_is_422(client, db_session) -> None:
    alice = await _user(db_session)
    await _exercise(db_session, "Bench Press", [Muscle.chest])
    await _program(
        db_session,
        alice,
        days=[("Push Day", [Muscle.chest])],
        created_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    client.set_user(alice)

    resp = await client.get("/api/recommendations/today", params={"day_index": 5})
    assert resp.status_code == 422


async def test_freestyle_muscle_focus_filters_candidates(client, db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    squat = await _exercise(db_session, "Back Squat", [Muscle.quadriceps])
    await _log_history(db_session, alice, bench)
    await _log_history(db_session, alice, squat)
    client.set_user(alice)

    # No Program active — freestyle. Unfocused proposes both.
    plain = (await client.get("/api/recommendations/today")).json()
    assert plain["source"] == "freestyle"
    assert {e["name"] for e in plain["exercises"]} == {"Bench Press", "Back Squat"}

    focused = (
        await client.get(
            "/api/recommendations/today", params={"muscles": "quadriceps"}
        )
    ).json()
    assert [e["name"] for e in focused["exercises"]] == ["Back Squat"]

    multi = (
        await client.get(
            "/api/recommendations/today", params={"muscles": "chest,quadriceps"}
        )
    ).json()
    assert {e["name"] for e in multi["exercises"]} == {"Bench Press", "Back Squat"}


async def test_freestyle_unknown_muscle_is_422(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get(
        "/api/recommendations/today", params={"muscles": "forearm-of-doom"}
    )
    assert resp.status_code == 422


async def test_day_index_on_freestyle_user_is_422(client, db_session) -> None:
    # No active Program → a day override is meaningless; say so, don't guess.
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get("/api/recommendations/today", params={"day_index": 0})
    assert resp.status_code == 422
