"""Program API — generate / browse / manage, end-to-end over real Postgres (#13).

The generation maths is pinned in :mod:`tests.test_program_generation`; here we
assert the WIRING: quiz→generate persists a Program with its split, ramping volume
and provenance receipt; presets generate; one-active-per-user (generating archives
the prior active); browse/get/activate/delete are per-user scoped; and the
Principle-derivation is real (provenance keys resolve to seeded Principles).
"""


import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.user import User
from app.services.seed_principles import seed_principles


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


async def _seed_kb(db) -> None:
    """Seed the real Principles KB so the generator has rules to derive from."""
    await seed_principles(db)


# --------------------------------------------------------------------------- #
# Quiz → generate
# --------------------------------------------------------------------------- #


async def test_generate_from_quiz_persists_program(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)

    resp = await client.post(
        "/api/programs/generate",
        json={
            "goal": "bulk",
            "experience": "intermediate",
            "days_per_week": 4,
            "session_minutes": 70,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["goal"] == "bulk"
    assert body["days_per_week"] == 4
    assert body["status"] == "active"
    # Split: one day per training day.
    assert len(body["days"]) == 4
    # Ramping volume + a deload week present.
    assert body["total_weeks"] == body["mesocycle_weeks"] + 1
    assert any(v["is_deload"] for v in body["muscle_volumes"])
    # Provenance receipt present and every entry names a Principle.
    assert body["provenance"]
    for entry in body["provenance"].values():
        assert entry["principle_key"]


async def test_generated_volume_traces_to_seeded_volume_principle(
    client, db_session
) -> None:
    # The persisted provenance for the weekly volume top resolves to the real
    # seeded volume Principle (Principle-derivation is genuine, not invented).
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)

    gen = await client.post(
        "/api/programs/generate",
        json={
            "goal": "bulk",
            "experience": "intermediate",
            "days_per_week": 4,
            "session_minutes": 70,
        },
    )
    key = gen.json()["provenance"]["weekly_sets_per_muscle_top"]["principle_key"]
    assert key == "volume-dose-response"
    # And that key is a real Principle the API can resolve.
    principle = await client.get(f"/api/principles/{key}")
    assert principle.status_code == 200
    assert principle.json()["params"]["sets_per_muscle_per_week"]["min"] == 10


async def test_generated_volume_within_principle_range(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    gen = await client.post(
        "/api/programs/generate",
        json={
            "goal": "bulk",
            "experience": "intermediate",
            "days_per_week": 4,
            "session_minutes": 70,
        },
    )
    body = gen.json()
    top = max(v["target_sets"] for v in body["muscle_volumes"] if not v["is_deload"])
    assert 10 <= top <= 20


@pytest.mark.parametrize("goal", ["bulk", "cut", "maintain", "strength"])
@pytest.mark.parametrize("experience", ["beginner", "intermediate", "advanced"])
async def test_every_goal_and_experience_generates_against_real_kb(
    client, db_session, goal, experience
) -> None:
    # Every quiz combo must generate against the REAL seeded KB — in particular a
    # cut, whose volume/frequency must still derive from Principles (a cut retains
    # muscle, so the volume + frequency rules apply to it too). This guards the
    # applicability filter: a Principle the generator reads but the KB scopes away
    # from a goal would 500 here.
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    resp = await client.post(
        "/api/programs/generate",
        json={
            "goal": goal,
            "experience": experience,
            "days_per_week": 4,
            "session_minutes": 70,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["goal"] == goal
    # Volume still derived from the KB for every goal.
    top = max(v["target_sets"] for v in body["muscle_volumes"] if not v["is_deload"])
    assert 10 <= top <= 20
    assert body["provenance"]["weekly_sets_per_muscle_top"]["principle_key"] == "volume-dose-response"


# --------------------------------------------------------------------------- #
# One active per user — generating archives the prior
# --------------------------------------------------------------------------- #


async def test_second_generate_archives_the_first(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)

    first = await client.post(
        "/api/programs/generate",
        json={"goal": "bulk", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 70},
    )
    second = await client.post(
        "/api/programs/generate",
        json={"goal": "strength", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 75},
    )
    assert first.status_code == 201 and second.status_code == 201

    # The active Program is now the second; the first is archived but kept.
    active = await client.get("/api/programs/active")
    assert active.json()["id"] == second.json()["id"]
    listing = await client.get("/api/programs")
    statuses = {p["id"]: p["status"] for p in listing.json()}
    assert statuses[first.json()["id"]] == "archived"
    assert statuses[second.json()["id"]] == "active"
    assert len(listing.json()) == 2  # the old one is kept, not deleted


async def test_no_active_program_returns_404(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get("/api/programs/active")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #


async def test_preset_catalog_lists_named_programs(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get("/api/programs/presets")
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()}
    assert {"gzclp", "upper-lower-hypertrophy", "ppl-hypertrophy", "531-strength"} <= keys


async def test_generate_from_preset(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    resp = await client.post(
        "/api/programs/generate", json={"preset_key": "ppl-hypertrophy"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["preset_key"] == "ppl-hypertrophy"
    assert body["days_per_week"] == 6
    assert len(body["days"]) == 6


async def test_generate_unknown_preset_404(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    resp = await client.post(
        "/api/programs/generate", json={"preset_key": "does-not-exist"}
    )
    assert resp.status_code == 404


async def test_quiz_options_lists_goals_and_days(client, db_session) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    resp = await client.get("/api/programs/quiz-options")
    assert resp.status_code == 200
    body = resp.json()
    assert {g["value"] for g in body["goals"]} == {"bulk", "cut", "maintain", "strength"}
    assert 4 in body["days_per_week"]


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


async def test_generate_requires_quiz_or_preset(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    # Missing experience/days/length and no preset → 422.
    resp = await client.post("/api/programs/generate", json={"goal": "bulk"})
    assert resp.status_code == 422


async def test_generate_rejects_unsupported_day_count(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    resp = await client.post(
        "/api/programs/generate",
        json={"goal": "bulk", "experience": "intermediate",
              "days_per_week": 7, "session_minutes": 70},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Per-user scoping + manage
# --------------------------------------------------------------------------- #


async def test_programs_are_scoped_to_user(client, db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    await _seed_kb(db_session)

    client.set_user(bob)
    bob_prog = await client.post(
        "/api/programs/generate",
        json={"goal": "bulk", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 70},
    )
    bob_id = bob_prog.json()["id"]

    # Alice cannot see Bob's Program.
    client.set_user(alice)
    assert (await client.get(f"/api/programs/{bob_id}")).status_code == 404
    assert (await client.get("/api/programs")).json() == []


async def test_activate_archived_program(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)

    first = (await client.post(
        "/api/programs/generate",
        json={"goal": "bulk", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 70},
    )).json()
    await client.post(
        "/api/programs/generate",
        json={"goal": "strength", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 75},
    )
    # Re-activate the first (now archived).
    resp = await client.post(f"/api/programs/{first['id']}/activate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    # It is now the single active Program.
    active = await client.get("/api/programs/active")
    assert active.json()["id"] == first["id"]


async def test_delete_program(client, db_session) -> None:
    alice = await _user(db_session)
    await _seed_kb(db_session)
    client.set_user(alice)
    prog = (await client.post(
        "/api/programs/generate",
        json={"goal": "bulk", "experience": "intermediate",
              "days_per_week": 4, "session_minutes": 70},
    )).json()
    resp = await client.delete(f"/api/programs/{prog['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/programs/{prog['id']}")).status_code == 404


# --------------------------------------------------------------------------- #
# Auth gating (override only get_db; let real get_current_user 401 with no header)
# --------------------------------------------------------------------------- #


async def test_programs_require_auth(db_session) -> None:
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/programs/presets")
    app.dependency_overrides.clear()
    assert resp.status_code == 401
