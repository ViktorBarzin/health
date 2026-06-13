"""Export streaming core — the bounded-memory engine behind the archive.

The key engineering constraint (ADR-0006 / Task #19): prod holds ~6.6M
``health_records`` for one user, so the export must NOT load a record type into a
single list. These tests prove the core:

* uses a **server-side cursor** (SQLAlchemy ``session.stream(...)``) and yields
  rows in bounded **chunks** rather than materializing them all, and
* exports a few-thousand-row table correctly end-to-end (every row written once,
  no chunk dropped at a boundary).

The per-user / API-shape behavior lives in ``test_export_api.py``; this file is
the low-level streaming contract.
"""

import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.models.health_record import HealthRecord
from app.models.user import User
from app.services import export_archive

pytestmark = pytest.mark.asyncio

UTC = timezone.utc


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _bulk_health_records(db, user_id: int, n: int) -> None:
    """Insert ``n`` HeartRate samples for a user, one per second.

    ``time`` is part of the PK ``(time, user_id, metric_type)``, so each sample
    gets a distinct second to keep all ``n`` rows.
    """
    base = datetime(2026, 1, 1, tzinfo=UTC)
    db.add_all(
        HealthRecord(
            time=base + timedelta(seconds=i),
            user_id=user_id,
            metric_type="HeartRate",
            value=float(60 + (i % 40)),
            unit="count/min",
        )
        for i in range(n)
    )
    await db.flush()


async def test_iter_record_chunks_uses_server_side_cursor(
    db_session, monkeypatch
) -> None:
    """The chunk iterator must go through session.stream() (server-side cursor).

    We spy on AsyncSession.stream to assert the streaming path — not a buffering
    ``execute().all()`` — is what feeds the export.
    """
    alice = await _make_user(db_session, "alice@example.com")
    await _bulk_health_records(db_session, alice.id, 50)

    spec = export_archive.spec_by_name("health_records")
    calls = {"stream": 0}

    original_stream = type(db_session).stream

    async def _spy_stream(self, statement, *args, **kwargs):
        calls["stream"] += 1
        return await original_stream(self, statement, *args, **kwargs)

    monkeypatch.setattr(type(db_session), "stream", _spy_stream)

    rows = []
    async for chunk in export_archive.iter_record_chunks(
        db_session, spec, alice.id, chunk_size=20
    ):
        rows.append(chunk)

    assert calls["stream"] == 1, "must open exactly one server-side cursor"
    # 50 rows at chunk_size=20 → chunks of 20, 20, 10 (never one list of 50).
    assert [len(c) for c in rows] == [20, 20, 10]
    assert sum(len(c) for c in rows) == 50


async def test_iter_record_chunks_never_buffers_whole_table(db_session) -> None:
    """No single chunk holds the entire table — chunking is real, not cosmetic."""
    alice = await _make_user(db_session, "alice@example.com")
    await _bulk_health_records(db_session, alice.id, 5000)

    spec = export_archive.spec_by_name("health_records")
    max_chunk = 0
    total = 0
    async for chunk in export_archive.iter_record_chunks(
        db_session, spec, alice.id, chunk_size=1000
    ):
        max_chunk = max(max_chunk, len(chunk))
        total += len(chunk)
        assert len(chunk) <= 1000

    assert total == 5000
    assert max_chunk <= 1000


async def test_build_export_zip_streams_thousands_of_rows(db_session) -> None:
    """A few-thousand-row table round-trips through the streamed ZIP intact."""
    alice = await _make_user(db_session, "alice@example.com")
    await _bulk_health_records(db_session, alice.id, 3000)

    # Drain the async byte generator into a buffer (the endpoint streams it).
    buf = io.BytesIO()
    async for chunk in export_archive.stream_export_zip(db_session, alice):
        buf.write(chunk)
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        import csv

        raw = zf.read("csv/health_records.csv").decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(raw)))
    # Every one of the 3000 rows is present (no boundary drops), header excluded.
    assert len(rows) == 3000


async def test_chunk_size_is_bounded_constant() -> None:
    """The default chunk size is a sane bounded constant (memory guard)."""
    assert 0 < export_archive.DEFAULT_CHUNK_SIZE <= 50_000


async def test_jsonb_fields_roundtrip_as_structures_not_repr_strings(
    db_session,
) -> None:
    """Every JSONB column exports as a JSON structure, not a Python-repr string.

    Regression (two coupled bugs): (1) streaming a whole ORM entity through a
    server-side cursor returns JSONB columns as a Python-repr ``str``, so the
    export must project explicit columns; and (2) the value coercion must pass
    dict/list through unchanged — ``str(dict)`` would emit ``{'a': 1}`` (invalid
    JSON), corrupting both the JSON document and the CSV cell. This sweeps EVERY
    JSONB-bearing table: workout.metadata, program.provenance, program_day.slots,
    custom_exercise.instructions/images, and the gym_profile lists.
    """
    import csv
    import io
    import json
    import zipfile
    from datetime import datetime

    from app.models.exercise import Exercise
    from app.models.gym_profile import GymProfile
    from app.models.program import Program, ProgramDay
    from app.models.workout import Workout

    alice = await _make_user(db_session, "alice@example.com")
    meta = {"hr": {"avg": 150, "max": 180}, "tags": ["a,b", "c"]}
    prov = {"rep_range": {"principle_key": "rep-scheme", "min": 8, "max": 12}}
    slots = [{"muscle": "chest"}, {"muscle": "triceps"}]
    instructions = ["step, one", 'step "two"']
    images = ["http://cdn/x.jpg"]
    equipment = ["barbell", "cable"]

    db_session.add(
        Workout(
            user_id=alice.id, time=datetime(2026, 1, 1, tzinfo=UTC),
            activity_type="Run", metadata_=meta,
        )
    )
    program = Program(
        user_id=alice.id, name="P", goal="bulk", experience="intermediate",
        days_per_week=3, session_minutes=60, mesocycle_weeks=4, total_weeks=5,
        deload_week=5, rep_range_low=8, rep_range_high=12, effort_rir=2,
        status="active", provenance=prov,
    )
    db_session.add(program)
    await db_session.flush()
    db_session.add(
        ProgramDay(program_id=program.id, day_index=0, name="D", slots=slots)
    )
    db_session.add(
        Exercise(
            slug="my-ex", name="My Ex", user_id=alice.id, source="custom",
            instructions=instructions, images=images,
        )
    )
    db_session.add(
        GymProfile(
            user_id=alice.id, bar_weights_kg=[20.0], plate_weights_kg=[25.0],
            equipment=equipment,
        )
    )
    await db_session.flush()

    buf = io.BytesIO()
    async for chunk in export_archive.stream_export_zip(db_session, alice):
        buf.write(chunk)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        doc = json.loads(zf.read("export.json"))
        members = {n: zf.read(n).decode("utf-8") for n in zf.namelist()}

    r = doc["records"]
    # JSON document: each JSONB field is a real structure, equal to its input.
    assert r["workouts"][0]["metadata"] == meta
    assert isinstance(r["workouts"][0]["metadata"], dict)
    assert r["programs"][0]["provenance"] == prov
    assert r["program_days"][0]["slots"] == slots
    assert isinstance(r["program_days"][0]["slots"], list)
    assert r["custom_exercises"][0]["instructions"] == instructions
    assert r["custom_exercises"][0]["images"] == images
    assert r["gym_profile"]["equipment"] == equipment

    # CSV mirror: each JSONB cell is valid JSON that re-parses to the same value.
    def _first(name: str) -> dict:
        return next(iter(csv.DictReader(io.StringIO(members[name]))))

    assert json.loads(_first("csv/workouts.csv")["metadata"]) == meta
    assert json.loads(_first("csv/programs.csv")["provenance"]) == prov
    assert json.loads(_first("csv/program_days.csv")["slots"]) == slots
    assert (
        json.loads(_first("csv/custom_exercises.csv")["instructions"])
        == instructions
    )
    assert json.loads(_first("csv/gym_profile.csv")["equipment"]) == equipment


async def test_registry_covers_every_required_record_type() -> None:
    """The spec registry includes every record type the archive must contain."""
    names = {spec.name for spec in export_archive.RECORD_SPECS}
    required = {
        "sessions",
        "sets",
        "workouts",
        "workout_route_points",
        "health_records",
        "category_records",
        "activity_summaries",
        "programs",
        "program_days",
        "program_muscle_volumes",
        "personal_records",
        "custom_exercises",
    }
    assert required <= names
