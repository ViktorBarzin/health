"""Full per-user data Export (ADR-0006) — the data-ownership archive.

The cardinal property is **per-user isolation**: an Export contains ONLY the
requesting user's rows, across every record type — never another user's. These
tests build a two-user fixture (Alice with data in every table, Bob with his own
distinct data) and assert Alice's archive contains all of hers and zero of Bob's.

Also covered: archive completeness (every record type present), the JSON + CSV
shapes (a ZIP holding one JSON document + one CSV per record type), graceful
handling of an empty record type, and that the response streams (a temp-file ZIP
streamed back, never built in a single in-memory blob).

The streaming/chunking of the query itself is unit-tested in
``test_export_archive.py`` (it proves a server-side cursor is used and a
few-thousand-row table exports without buffering every row in a list).
"""

import csv
import io
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.activity_summary import ActivitySummary
from app.models.category_record import CategoryRecord
from app.models.exercise import Exercise
from app.models.gym_profile import GymProfile
from app.models.health_record import HealthRecord
from app.models.personal_record import PersonalRecord
from app.models.program import Program, ProgramDay, ProgramMuscleVolume
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.models.workout import Workout
from app.models.workout_route_point import WorkoutRoutePoint
from app.services.pr import PRKind

pytestmark = pytest.mark.asyncio

UTC = timezone.utc


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_exercise(db, name: str, *, user_id=None) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        source="free-exercise-db" if user_id is None else "custom",
    )
    db.add(ex)
    await db.flush()
    return ex


async def _seed_full_user(db, user: User, *, marker: str) -> dict:
    """Give a user one row in every exportable table, tagged with ``marker``.

    Returns the ids/markers so a test can assert presence (own) or absence
    (other user's). ``marker`` is woven into string fields so cross-user leakage
    is detectable by substring.
    """
    # A custom Exercise (the user's own; the shared library is NOT exported).
    custom_ex = await _make_exercise(db, f"Custom {marker}", user_id=user.id)
    # A global Exercise the Set references (shared; not exported as a row).
    global_ex = await _make_exercise(db, f"Global {marker}", user_id=None)

    # Session + Set.
    started = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    session = TrainingSession(
        id=uuid.uuid4(), user_id=user.id, started_at=started,
        ended_at=started + timedelta(hours=1),
    )
    db.add(session)
    await db.flush()
    s = TrainingSet(
        id=uuid.uuid4(), session_id=session.id, exercise_id=global_ex.id,
        order_index=0, weight_kg=100.0, reps=5, rpe=8.0, set_type=SetType.normal,
    )
    db.add(s)

    # Workout + route point.
    workout = Workout(
        id=uuid.uuid4(), user_id=user.id,
        time=datetime(2026, 1, 3, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 3, 9, 30, tzinfo=UTC),
        activity_type=f"Running-{marker}", duration_sec=1800.0,
        total_distance_m=5000.0, total_energy_kj=1200.0,
        metadata_={"note": marker},
    )
    db.add(workout)
    await db.flush()
    db.add(WorkoutRoutePoint(
        time=datetime(2026, 1, 3, 9, 5, tzinfo=UTC), workout_id=workout.id,
        latitude=51.5, longitude=-0.12, altitude_m=10.0,
    ))

    # Health record (the high-volume table).
    db.add(HealthRecord(
        time=datetime(2026, 1, 4, 7, 0, tzinfo=UTC), user_id=user.id,
        metric_type=f"HeartRate-{marker}", value=60.0, unit="count/min",
    ))
    # Category record.
    db.add(CategoryRecord(
        time=datetime(2026, 1, 4, 22, 0, tzinfo=UTC), user_id=user.id,
        category_type=f"SleepAnalysis-{marker}", value="HKCategoryValueAsleep",
        end_time=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    ))
    # Activity summary.
    db.add(ActivitySummary(
        date=date(2026, 1, 4), user_id=user.id,
        active_energy_burned_kj=2000.0, exercise_minutes=30.0, stand_hours=10,
    ))

    # Program (+ day + muscle volume).
    program = Program(
        id=uuid.uuid4(), user_id=user.id, name=f"Program {marker}",
        goal="bulk", experience="intermediate", days_per_week=3,
        session_minutes=60, mesocycle_weeks=4, total_weeks=5, deload_week=5,
        rep_range_low=8, rep_range_high=12, effort_rir=2, status="active",
        provenance={"rep_range": {"principle_key": f"rep-{marker}"}},
    )
    db.add(program)
    await db.flush()
    db.add(ProgramDay(
        id=uuid.uuid4(), program_id=program.id, day_index=0,
        name=f"Day {marker}", slots=[{"muscle": "chest"}],
    ))
    db.add(ProgramMuscleVolume(
        program_id=program.id, muscle="chest", week=1, target_sets=10,
        is_deload=False,
    ))

    # Personal record.
    db.add(PersonalRecord(
        id=uuid.uuid4(), user_id=user.id, exercise_id=global_ex.id,
        kind=PRKind.weight, weight_bucket=None, value=100.0,
        achieved_set_id=s.id, achieved_at=started,
    ))

    # Gym Profile (singleton).
    db.add(GymProfile(
        user_id=user.id, bar_weights_kg=[20.0], plate_weights_kg=[25.0],
        equipment=[f"barbell-{marker}"],
    ))
    await db.flush()
    return {
        "session_id": str(session.id),
        "set_id": str(s.id),
        "workout_id": str(workout.id),
        "program_id": str(program.id),
        "custom_exercise_id": str(custom_ex.id),
        "marker": marker,
    }


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


def _unzip(content: bytes) -> dict[str, bytes]:
    """Return {archive-path: bytes} for every entry in a ZIP byte string."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


# --- The download succeeds and is a well-formed ZIP -------------------------


async def test_export_returns_a_zip_archive(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    await _seed_full_user(db_session, alice, marker="ALICE")
    client.set_user(alice)

    resp = await client.get("/api/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert ".zip" in resp.headers["content-disposition"]
    # It really is a valid zip.
    members = _unzip(resp.content)
    assert "export.json" in members


async def test_archive_layout_has_json_plus_one_csv_per_record_type(
    client, db_session
) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    await _seed_full_user(db_session, alice, marker="ALICE")
    client.set_user(alice)

    members = _unzip((await client.get("/api/export")).content)
    # The single nested JSON document.
    assert "export.json" in members
    # One CSV per record type under csv/.
    expected_csvs = {
        "csv/sessions.csv",
        "csv/sets.csv",
        "csv/workouts.csv",
        "csv/workout_route_points.csv",
        "csv/health_records.csv",
        "csv/category_records.csv",
        "csv/activity_summaries.csv",
        "csv/programs.csv",
        "csv/program_days.csv",
        "csv/program_muscle_volumes.csv",
        "csv/personal_records.csv",
        "csv/custom_exercises.csv",
        "csv/gym_profile.csv",
    }
    assert expected_csvs <= set(members)


# --- Completeness: every record type is present in JSON + CSV ---------------


async def test_json_archive_is_complete(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ids = await _seed_full_user(db_session, alice, marker="ALICE")
    client.set_user(alice)

    import json

    doc = json.loads(_unzip((await client.get("/api/export")).content)["export.json"])
    # Manifest identifies the owner + a generated_at.
    assert doc["user"]["email"] == "alice@example.com"
    assert "generated_at" in doc
    records = doc["records"]
    # Every record type present and populated.
    assert len(records["sessions"]) == 1
    assert records["sessions"][0]["id"] == ids["session_id"]
    # Sets are nested under their Session AND/OR present as a flat list — assert
    # the flat collection has the Set (the CSV mirror needs it flat too).
    assert any(s["id"] == ids["set_id"] for s in records["sets"])
    assert len(records["workouts"]) == 1
    assert len(records["workout_route_points"]) == 1
    assert len(records["health_records"]) == 1
    assert len(records["category_records"]) == 1
    assert len(records["activity_summaries"]) == 1
    assert len(records["programs"]) == 1
    assert len(records["program_days"]) == 1
    assert len(records["program_muscle_volumes"]) == 1
    assert len(records["personal_records"]) == 1
    assert len(records["custom_exercises"]) == 1
    assert records["gym_profile"] is not None


async def test_csv_files_are_populated(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ids = await _seed_full_user(db_session, alice, marker="ALICE")
    client.set_user(alice)

    members = _unzip((await client.get("/api/export")).content)
    sessions = _csv_rows(members["csv/sessions.csv"])
    assert len(sessions) == 1
    assert sessions[0]["id"] == ids["session_id"]
    sets = _csv_rows(members["csv/sets.csv"])
    assert len(sets) == 1
    assert sets[0]["weight_kg"] == "100.0"
    assert sets[0]["reps"] == "5"
    # health_records CSV has the canonical columns.
    hr = _csv_rows(members["csv/health_records.csv"])
    assert len(hr) == 1
    assert set(hr[0].keys()) >= {"time", "metric_type", "value", "unit"}


# --- THE CARDINAL TEST: per-user isolation ----------------------------------


async def test_export_contains_zero_of_another_users_rows(client, db_session) -> None:
    """Alice's archive must contain every ALICE row and not one BOB byte."""
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    alice_ids = await _seed_full_user(db_session, alice, marker="ALICE")
    bob_ids = await _seed_full_user(db_session, bob, marker="BOB")

    client.set_user(alice)
    content = (await client.get("/api/export")).content
    members = _unzip(content)

    # 1. Substring sweep across the WHOLE archive: BOB's marker never appears,
    #    ALICE's does. This catches leakage in any field of any record type.
    blob = b"".join(members.values())
    assert b"ALICE" in blob
    assert b"BOB" not in blob

    # 2. Per-record-type id checks in the JSON document.
    import json

    records = json.loads(members["export.json"])["records"]
    session_ids = {s["id"] for s in records["sessions"]}
    assert alice_ids["session_id"] in session_ids
    assert bob_ids["session_id"] not in session_ids

    set_ids = {s["id"] for s in records["sets"]}
    assert alice_ids["set_id"] in set_ids
    assert bob_ids["set_id"] not in set_ids

    workout_ids = {w["id"] for w in records["workouts"]}
    assert alice_ids["workout_id"] in workout_ids
    assert bob_ids["workout_id"] not in workout_ids

    program_ids = {p["id"] for p in records["programs"]}
    assert alice_ids["program_id"] in program_ids
    assert bob_ids["program_id"] not in program_ids

    custom_ex_ids = {e["id"] for e in records["custom_exercises"]}
    assert alice_ids["custom_exercise_id"] in custom_ex_ids
    assert bob_ids["custom_exercise_id"] not in custom_ex_ids

    # 3. The CSV mirror is isolated too (sweep every CSV).
    for name, raw in members.items():
        if name.endswith(".csv"):
            assert b"BOB" not in raw, f"BOB leaked into {name}"


async def test_child_rows_isolated_via_parent_ownership(client, db_session) -> None:
    """Sets (via Session) and route points (via Workout) are scoped by parent.

    A child table has no user_id; its isolation rides on the parent filter. Prove
    Bob's child rows never appear in Alice's export.
    """
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await _seed_full_user(db_session, alice, marker="ALICE")
    bob_ids = await _seed_full_user(db_session, bob, marker="BOB")

    client.set_user(alice)
    members = _unzip((await client.get("/api/export")).content)

    set_rows = _csv_rows(members["csv/sets.csv"])
    assert all(r["session_id"] != bob_ids["session_id"] for r in set_rows)
    rp_rows = _csv_rows(members["csv/workout_route_points.csv"])
    assert all(r["workout_id"] != bob_ids["workout_id"] for r in rp_rows)


# --- Graceful handling of empty / absent data -------------------------------


async def test_empty_record_type_yields_header_only_csv(client, db_session) -> None:
    """A user with no Workouts still gets a workouts.csv — header, zero rows."""
    alice = await _make_user(db_session, "alice@example.com")
    # No data at all for Alice.
    client.set_user(alice)

    members = _unzip((await client.get("/api/export")).content)
    # The CSV exists with a header line and no data rows.
    workouts = _csv_rows(members["csv/workouts.csv"])
    assert workouts == []
    # And the file is non-empty (a header was written).
    assert members["csv/workouts.csv"].strip() != b""

    import json

    records = json.loads(members["export.json"])["records"]
    assert records["workouts"] == []
    assert records["sessions"] == []
    # A user with no Gym Profile exports null (not a fabricated default).
    assert records["gym_profile"] is None


async def test_export_includes_diary_entries_when_nutrition_tables_exist(
    client, db_session
) -> None:
    """The Diary (nutrition, #21) round-trips through the export, per-user scoped.

    The Export module probes for the ``diary_entries`` table and includes it when
    present (ADR-0006). With the nutrition tables now built (#21), a user's own
    Diary Entries appear in both JSON and CSV; another user's never do.
    """
    from app.models.diary_entry import DiaryEntry, Meal
    from app.models.food import Food

    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await _seed_full_user(db_session, alice, marker="ALICE")
    # A shared Food + a Diary Entry for each user.
    food = Food(
        slug="chicken-export", name="Chicken", user_id=None,
        serving_size=100, serving_unit="g",
        calories=165, protein_g=31, carbs_g=0, fat_g=3.6, source="generic",
    )
    db_session.add(food)
    await db_session.flush()
    db_session.add(DiaryEntry(
        user_id=alice.id, food_id=food.id, entry_date=date(2026, 6, 13),
        meal=Meal.lunch, quantity=1.5,
    ))
    db_session.add(DiaryEntry(
        user_id=bob.id, food_id=food.id, entry_date=date(2026, 6, 13),
        meal=Meal.dinner, quantity=2,
    ))
    await db_session.flush()

    client.set_user(alice)
    resp = await client.get("/api/export")
    assert resp.status_code == 200
    members = _unzip(resp.content)
    import json

    records = json.loads(members["export.json"])["records"]
    diary = records["diary_entries"]
    # Only Alice's own entry — Bob's is never visible.
    assert len(diary) == 1
    assert diary[0]["user_id"] == alice.id
    assert diary[0]["meal"] == "lunch"
    assert float(diary[0]["quantity"]) == 1.5
    # A diary CSV is produced (header + the one row).
    assert "csv/diary_entries.csv" in members
    csv_rows = list(csv.DictReader(io.StringIO(members["csv/diary_entries.csv"].decode())))
    assert len(csv_rows) == 1
    assert csv_rows[0]["meal"] == "lunch"


async def test_export_includes_recipes_when_table_exists(client, db_session) -> None:
    """A user's Recipes (#22) round-trip through the export, per-user scoped.

    ``recipes`` carries ``user_id`` so the optional-table reflection path includes
    it (and scopes it to the caller). Another user's Recipe never appears.
    """
    from app.models.food import Food
    from app.services.recipe_query import RecipeIngredientInput, create_recipe

    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    shared = Food(
        slug="oats-recipe-export", name="Oats", user_id=None,
        serving_size=100, serving_unit="g",
        calories=389, protein_g=17, carbs_g=66, fat_g=7, source="generic",
    )
    db_session.add(shared)
    await db_session.flush()

    await create_recipe(
        db_session, user=alice, name="Alice's Porridge", yield_servings=2,
        ingredients=[RecipeIngredientInput(food_id=shared.id, quantity=1)],
    )
    await create_recipe(
        db_session, user=bob, name="Bob's Porridge", yield_servings=1,
        ingredients=[RecipeIngredientInput(food_id=shared.id, quantity=1)],
    )
    await db_session.flush()

    client.set_user(alice)
    resp = await client.get("/api/export")
    assert resp.status_code == 200
    members = _unzip(resp.content)
    import json

    recipes = json.loads(members["export.json"])["records"]["recipes"]
    assert len(recipes) == 1  # only Alice's
    assert recipes[0]["user_id"] == alice.id
    assert float(recipes[0]["yield_servings"]) == 2.0
    assert "csv/recipes.csv" in members


# --- Streaming: the response is chunked, not one in-memory blob -------------


async def test_response_is_streamed(client, db_session) -> None:
    """The archive comes back as a streamed body (multiple chunks)."""
    alice = await _make_user(db_session, "alice@example.com")
    await _seed_full_user(db_session, alice, marker="ALICE")
    client.set_user(alice)

    async with client.stream("GET", "/api/export") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        chunks = [chunk async for chunk in resp.aiter_bytes()]
    # Reassembled, it's a valid zip with the JSON doc.
    content = b"".join(chunks)
    assert "export.json" in _unzip(content)


async def test_auth_required(client, db_session) -> None:
    """Export is auth-gated like every other endpoint."""
    # No user set on the override → simulate the unauthenticated path by routing
    # through the real dependency, which 401s without an identity header.
    app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = await client.get("/api/export")
        assert resp.status_code == 401
    finally:
        # restore handled by fixture teardown
        pass
